# LLVM Frontend Prefetch Insertion Design

## Goal

The immediate goal is to build an optimized Verilator binary by inserting
frontend prefetch instructions at profile-guided branch sites. The current
experiment uses `prefetcht1` by default, with `prefetcht2` available as a
lower-priority cache hint. This avoids the fragile source-patching path where
manual `RIP + displacement` calculations can drift after recompilation.

The longer-term goal is to turn the same machinery into a proper LLVM pass that
can be driven automatically by profiling output.

## Profiling Input

The profiling flow records PEBS samples for a frontend miss event and attaches
LBR history:

```bash
perf record -e <frontend-miss-event>:upp -b -c <period> -o l2miss.data -- <verilator run>
perf script -i l2miss.data -F ip,sym,brstack > lbr_symbolic_dump.txt
perf script -i l2miss.data -F ip,brstack       > lbr_raw_dump.txt
```

For each sample:

- `LBR[0].to` is treated as the miss target.
- `LBR[d].from` for `d in [1, depth]` is treated as a possible injection site.
- Branch flags classify the candidate as `COND`, `UNCOND`, `CALL`, `RET`,
  `IND`, or `IND_CALL`.

`tools/prefetchit_trace_to_plan.py` can consume one or more trace directories.
It aggregates all samples before target selection, then combines them with `nm`
and `llvm-addr2line` to recover:

- target containing symbol, source location, representative address, 64B
  cacheline, and sample count;
- candidate site function, file, line, branch type, LBR depth, address, 64B
  cacheline, and coverage.

The output is a `prefetchit.plan.v1` JSON file plus CSV summaries.

## Candidate Selection Algorithm

The old flow selected `top_k` targets by `function:file:line`. That was too
coarse: many Verilator machine PCs share one generated source line, so a plan
could validate at source-line granularity while prefetching the wrong
instruction cacheline.

The current flow instead selects target keys at containing-symbol plus 64B
cacheline granularity. It can still use `--top-k` for compatibility, but the
preferred experiments use cumulative target coverage:

```text
samples = aggregate(all PEBS/LBR trace runs)
targets = hottest target symbol+cacheline keys until cumulative samples
          reaches --target-coverage-pct, e.g. 50%, 75%, or 100%

for each target in targets:
    samples = all PEBS samples whose LBR[0].to resolves to target
    candidates = all LBR[d].from sites for d = 1..max_depth
    if --selection-mode all-paths:
        emit every resolved candidate site, sorted by sample count
    else:
        use greedy/top-sites/per-depth selection for bounded experiments
```

`all-paths` deliberately emits multiple injection sites for one target. A single
miss target can be reached through several hot branch paths, so a one-site
policy can miss most dynamic paths even when the target is correct.

The plan records cumulative coverage after every selected site. That coverage is
the main sanity check for whether the pass is actually seeing enough dynamic
paths.

The converter can also attach a target-block-relative byte-offset span:

```text
--prefetch-byte-offsets 0,64,128,192
```

This is intentionally more aggressive than one exact source-line prefetch.
PEBS gives us a precise machine PC, but an IR pass usually anchors by debug
line. Generated Verilator code can map many machine instructions to one line, so
prefetching several nearby cachelines from the LLVM target block is a practical
way to cover sampled-PC/source-line ambiguity without falling back to brittle
binary patching.

## LLVM Pass Input

The plan root carries the prefetch policy, and each plan entry has two anchors:

```json
{
  "prefetch": {
    "mnemonic": "prefetcht1",
    "byte_offsets": [0, 64, 128, 192]
  },
  "injections": [
    {
      "prefetch_mnemonic": "prefetcht1",
      "target": {
        "mangled": "...",
        "function": "...",
        "file": "...",
        "line": 123,
        "addr": "0x...",
        "cacheline64": "0x...",
        "symbol_offset": "0x..."
      },
      "site": {
        "mangled": "...",
        "function": "...",
        "file": "...",
        "line": 456,
        "branch_type": "COND",
        "lbr_depth": 8,
        "addr": "0x...",
        "cacheline64": "0x...",
        "symbol_offset": "0x..."
      }
    }
  ]
}
```

The pass resolves functions by mangled IR name first, then falls back to
demangled/source names. Source matching uses debug metadata and accepts full
path, suffix path, or generated-source-relative path matches.

`file:line` is the common case today. If the plan later includes `column` or
`discriminator`, the pass also requires those debug-location fields to match.
That gives us a clean upgrade path when several basic blocks share the same
source line.

The plan already carries symbol offsets and cachelines so validation can detect
source-line false positives. A future MachineFunction pass should consume those
fields directly and anchor by machine offset instead of debug line.

## Insertion Point

For the injection site, the pass searches the resolved function for instructions
with matching debug location. It prefers an instruction whose IR opcode matches
the LBR branch type:

- `COND`: conditional branch or switch;
- `UNCOND`: unconditional branch;
- `CALL` / `IND_CALL`: call-like instruction;
- `RET`: return;
- `IND`: indirect branch or indirect call-like instruction.

The prefetch inline asm is inserted immediately before that branch/call/return.
This means we prefetch at the callsite/branch site, not after entering the
callee. That is the key behavior needed for the current “prefetch before branch”
experiment.

## Target Addressing

The current default is exact target-symbol addressing. The trace-to-plan tool
records the sampled target as containing text symbol plus symbol offset and
64B cacheline:

```json
"target": {
  "mangled": "_Z...",
  "addr": "0x...",
  "symbol_offset": "0x1234",
  "cacheline64": "0x..."
}
```

For `prefetch.operand = pc-relative-symbol-offset`, the pass emits inline asm
that names that exact symbol offset:

```llvm
call void asm sideeffect "prefetcht1 _Z...+0x1234(%rip)", ""()
call void asm sideeffect "prefetcht1 _Z...+0x1274(%rip)", ""()
```

LLVM/MC then owns relocation and RIP-relative displacement encoding. This mode
is stricter than debug-line target anchoring because the prefetch target is the
sampled symbol offset/cacheline, not the first IR instruction that happened to
match a source line.

The older fallback is target-block addressing:

1. It finds the target instruction by function + debug source location.
2. If that instruction is not already the first real instruction in its basic
   block, it splits the basic block immediately before the target instruction.
3. It creates `blockaddress(@target_function, %prefetchit.target...)`.
4. It emits inline asm with an immediate label operand. If the plan requested
   multiple byte offsets, it emits one prefetch per offset:

```llvm
call void asm sideeffect "prefetcht1 ${0:c}(%rip)", "i"(
  ptr blockaddress(@target_function, %prefetchit.target)
)
call void asm sideeffect "prefetcht1 ${0:c}+64(%rip)", "i"(
  ptr blockaddress(@target_function, %prefetchit.target)
)
```

LLVM lowers this to assembly such as:

```asm
prefetcht1 .Ltmp42(%rip)
prefetcht1 .Ltmp42+64(%rip)
```

This is the rigorous part: LLVM owns label creation, layout, relocation, and
RIP-relative displacement encoding. The pass only says “prefetch the label at
this target basic block, optionally plus cacheline-sized offsets.”

## Layout Compensation For Symbol+Offset Targets

`symbol+offset` targets are offsets in the *baseline* binary. Every prefetch
the pass injects earlier in the same function (7 bytes each for a rip-relative
`prefetcht1`) pushes the code after it forward, so the k-th injected site in a
function would otherwise see its continuation `7·(prefetches before it)` bytes
later than the operand says. On the Verilator RET/callsite plan (985 sites in
one 7.8 MB `eval_nba__0`) this left only 13 of 1968 prefetches on the planned
cacheline and the plan had no effect (2026-09-15 restore).

The pass therefore defers emission until all sites in the module are resolved
and adds, per target, the bytes of all injected prefetches whose plan site
offset precedes the target offset in the target's function
(`-prefetchit-layout-compensation`, default on; the log reports
`layout_shift_applied` and `layout_shift_max_bytes`). Blockaddress and GOT
operands are label/PLT relative and need no shift. That compensation is only the first-order term: the injected asm also changes
codegen inside the function (alignment, scheduling, register allocation), and
on `eval_nba__0` the residual drift was −18…−1067 B and non-monotonic (only 36%
of targets within a cacheline). The exact fix is post-link:
`tools/reanchor_prefetch_targets.py` anchors every target on the **k-th call
instruction of its function** (the pass never adds or removes calls; both
binaries have 103,256 calls in `eval_nba__0`), keeps the target's delta from
that call, and patches only the prefetch `disp32` fields (layout unchanged, so
NOP twins stay valid). After re-anchoring, 1968/1968 static prefetches sit
exactly on their continuation (+0 / +64). `tools/check_prefetch_drift.py`
reports this and is the first thing to run when a plan shows no MPKI change;
`scripts/static/run_verilator_repro.sh` runs resolve → re-anchor → drift gate
for every variant.

## Site Anchoring When Several Sites Share A Source Line

Generated Verilator code maps many call instructions to one source line. The
pass resolves a site by (function, file, line, branch type) and used to pile
every plan site of that line onto the first IR candidate (the per-site use
counter only rotated *identical* plan entries). With 1,000 sites this was
harmless (100% of prefetches at the planned call); with 5,000 sites only 52%
were. The pass now ranks the plan's sites of a location by their baseline
symbol offset and maps rank *k* to the *k*-th IR candidate (IR order follows
layout order in generated code); `ranked_sites` in the log counts the sites
resolved this way. Exact machine-level site anchoring still needs a
post-ISel/MachineFunction pass (open item).

## Prefetch Mnemonics

Supported mnemonics are:

- `prefetcht1`: default; intended to bring the target at least to L2.
- `prefetcht2`: weaker locality hint, useful as a lower-overhead comparison.
- `prefetcht0` / `prefetchnta`: supported for experiments.
- `prefetchit0` / `prefetchit1`: supported when the toolchain and CPU enable
  instruction prefetch instructions.

The converter writes the mnemonic into the plan with `--prefetch-mnemonic`.
The pass can override it with `-prefetchit-mnemonic=<mnemonic>` for A/B runs
without regenerating the plan.

## Compiler Pipeline Placement

When run explicitly with `opt -passes=prefetchit-inject`, the pass runs exactly
where requested.

When loaded as a clang pass plugin:

- at `-O1` or higher, it runs at the optimizer-last extension point;
- at `-O0`, it runs at pipeline start.

Optimizer-last is preferred for this experiment because it reduces the chance
that later IR passes clone, delete, sink, or hoist the inserted side-effecting
inline asm. For maximum binary-level exactness, the final production version may
move to a MachineFunction pass after instruction selection, but the current IR
pass is already much safer than source-level text insertion.

## Current Status Against Requested Goals

- Cacheline-level target validation: implemented. Assembly validation enforces
  exact target address/cacheline matches for `pc-relative-symbol-offset` plans.
- Symbol+offset/cacheline target planning: implemented. Target keys are sampled
  PC containing-symbol plus 64B cacheline, and emitted operands use
  `symbol+offset(%rip)`.
- Optimized residual trace analysis: implemented in the overnight/final compare
  scripts for the best `prefetcht1` and same-plan `prefetchit1` binaries.
- RET/CALL/COND timing policy split: implemented in the plan generator via
  `--branch-depth-policy` and used by later aggressive batches.
- Exact target support in the compiler: implemented at IR-plugin level through
  symbol-offset inline asm and assembly validation.
- Exact site support in the compiler: partially implemented. Plans record
  `site.addr` and `site.symbol_offset`, but the active IR pass still anchors
  insertion by debug location plus branch type. A future MachineFunction or
  post-isel pass should consume the recorded site symbol offset directly to
  remove any remaining source-line ambiguity.

## Validation

Every optimized binary should pass these checks:

1. Pass log: `injected > 0`, and missing target/site counts are understood.
2. IR check: inline asm contains the requested mnemonic. Exact target mode
   should contain `symbol+offset(%rip)`; fallback mode should contain
   `blockaddress`.
3. Assembly check: `objdump` or `llc` output contains
   `prefetcht1 symbol+offset(%%rip)` or `.L...(%%rip)` fallback targets.
4. Runtime check: the optimized Verilator binary completes the same workload
   without segfaults or simulator errors.
5. Assembly target check: `pc-relative-symbol-offset` plans require objdump
   target operands to land in planned 64B target cachelines, including requested
   byte-offset spans. Older `pc-relative-blockaddress` span plans report this
   ratio but do not enforce it, because they intentionally prefetch adjacent
   target-block-relative cachelines.
6. Profile check: MPKI/runtime tables have no `nan`, zero dummy values, or
   missing perf counters.
7. Trace check: optimized-binary PEBS/LBR traces should show whether the same
   miss targets remain hot. If they remain identical, the prefetch is either too
   late, on the wrong path, ineffective for I-side demand fetch, or adding too
   much instruction footprint.

## Known Limits

The target PC is now exact when the plan has `mangled + symbol_offset`. The
insertion site is still IR/debug-location based. If several machine instructions
share one source line, the pass chooses the preferred branch/call/return
instruction at that debug location and rotates among matching instructions for
duplicate sites. Exact final-machine-PC site anchoring still belongs in a
MachineFunction or post-ISel implementation.

Unresolved `line 0` targets can still be targeted when `mangled` and
`symbol_offset` are available. If both source line and symbol offset are missing,
the pass cannot insert precisely.

## Plan-Free Modes: Sequential Lookahead And Callee-Entry Burst (2026-09-16)

The PEBS/LBR analysis of the Verilator simulator (`static_prefetch/tools/ret/
miss_stream_characterization.py`) showed that the branch type of an L2I miss
sample only labels the last taken branch: the miss IP is usually *not* the
branch target (RET: 30% on the continuation line, 25% more than 16 lines
later; COND 68% of samples are short forward hops). About 64k lines miss per
simulated cycle, i.e. the ~4 MB of generated code executed per cycle streams
through L2 line by line, and a stage-1 microbenchmark
(`icache_microbenchmark/microbench/seq_stream/`) confirmed that the hardware
prefetchers do not hide a sequential *code* stream (MPKI 71, IPC 0.41 on a
pure 16 MB straight-line function) while `prefetcht1 D(%rip)` every 64 B
removes the misses (3.3x at D = 4–8 KB).

The pass therefore has two plan-free, profile-free modes that need no plan
file, no symbol+offset targets and hence no layout compensation or
re-anchoring:

```text
-prefetchit-seq-distance=D        (env PREFETCHIT_SEQ_DISTANCE)   bytes ahead; 0 = off
-prefetchit-seq-stride-insns=K    (PREFETCHIT_SEQ_STRIDE_INSNS)   one site every K IR instructions
-prefetchit-seq-lines=L           (PREFETCHIT_SEQ_LINES)          D, D+64, ... per site
-prefetchit-seq-functions=RE      (PREFETCHIT_SEQ_FUNCTIONS)      mangled-name regex (default all)
-prefetchit-seq-exclude=RE        (PREFETCHIT_SEQ_EXCLUDE)
-prefetchit-seq-min-insns=N       (PREFETCHIT_SEQ_MIN_INSNS)
-prefetchit-callee-burst-lines=L  (PREFETCHIT_CALLEE_BURST_LINES) prefetch callee+0..64*(L-1) before direct calls
-prefetchit-callee-burst-lead=K   (PREFETCHIT_CALLEE_BURST_LEAD)  K IR instructions before the call
-prefetchit-callee-burst-min-callee-insns=N
```

*Sequential lookahead* inserts `call void asm sideeffect "prefetcht1 D(%rip)"`
before every K-th non-PHI/non-EH/non-debug instruction of the selected
functions. The operand is a constant rip-relative displacement (`0F 18 15
disp32`, 7 bytes), so in the final layout it always means "the line D bytes
ahead of this instruction" — the software equivalent of a next-N-line
instruction prefetcher for straight-line generated code. Because IR
instructions are not bytes, the actual spacing is calibrated on the binary:
on Verilator's generated code K = 20 gives a 71 B median spacing (p10 31,
p90 125), K = 40 gives 138 B (IR:machine ≈ 1.39, 4.8 B per instruction).
`scripts/static/build_verilator_variant.sh` reports the operand check and the
spacing distribution of every seq build. (Note: `check_prefetch_drift.py`
assumes callsite plans with byte offsets 0/64; a 4-offset plan such as the RET
v3 plan legitimately reports ~50% "within ±64 B" — verify the delta histogram
instead, as done for `ret_v3_s256_l4`: 24.5% each at +0/+64/+128/+192.)

*Callee-entry burst* inserts `prefetcht1 callee+64*l(%rip)` for the first L
lines of every direct callee defined in the module and matching the regexes,
K instructions before the call (within the block). It covers the first D
bytes of a callee that the caller's rip-relative stream cannot reach. On
Verilator it matters little because 61% of consecutive `nba_sequent`
callees of `eval_nba__0` are laid out adjacently (89% within 4 KB), so the
callee's own lookahead reaches the next callee.

Both modes coexist with a plan (`runPlan` first, then burst, then seq). The
NOP-twin tool patches these prefetches like any other, so the layout-controlled
A/B protocol is unchanged. Measured (Verilator DualMegaBoom qsort, 3.8 GHz,
3 interleaved reps, `results/static_overhaul_20260916/summarize_all.py`):
D = 4096, K = 20 + 4-line burst → **1.148x vs base, 1.230x vs its NOP twin**,
L2I MPKI 56.9 → 14.0; D = 8192, K = 40 + 8-line burst → 1.145x at +4.2%
instructions; burst alone 1.034x. The twin costs about the instruction increase
(+6.4% → −5.7%), so after D ≥ 4 KB the tuning axis is issue density. The same
binary gives 1.143x on dhrystone/median/towers and 1.139x on the full 538,240-
cycle qsort run; arcilator DualMegaBoom (LLVM IR → pass → clang) gets 1.543x /
1.683x vs twin at K = 10 (MPKI 79 → 35).
