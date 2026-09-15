# Frontend Prefetch LLVM Pass

For a source-only restore on another server, start with
[`migration/README.md`](migration/README.md). It pins every first-party and
benchmark revision and preserves source changes that used to live only in local
benchmark checkouts.

This directory contains a standalone LLVM 19 pass for injecting frontend
prefetch instructions from PEBS/LBR profiling traces.

The current default mnemonic is `prefetcht1`, because the experiment only needs
to bring the missed instruction line at least as close as L2. The pass also
supports `prefetcht2`, `prefetcht0`, `prefetchnta`, `prefetchit0`, and
`prefetchit1`.

See `docs/design.md` for the profiling-to-pass design and validation plan.

## Pipeline

1. `tools/prefetchit_trace_to_plan.py` converts a PEBS/LBR trace into a compact
   JSON plan.
2. `lib/PrefetchITPass.cpp` consumes that plan and injects prefetches before
   selected branch/call/return sites.
3. The current default target operand is exact `symbol+offset(%rip)` from the
   sampled miss PC. LLVM/MC owns RIP-relative displacement encoding, so the pass
   does not manually compute PC-relative immediates. A `blockaddress` target
   mode remains as a fallback for older plans.

Example generated assembly:

```asm
prefetcht1 _Z35VTestDriver___024root___eval_nba__0P21VTestDriver___024root+0x5a5849(%rip)
prefetcht1 _Z35VTestDriver___024root___eval_nba__0P21VTestDriver___024root+0x5a5889(%rip)
```

## Build

```bash
cmake -S llvm_prefetchit -B llvm_prefetchit/build \
  -DLLVM_DIR=/usr/lib/llvm-19/lib/cmake/llvm
cmake --build llvm_prefetchit/build
```

## Aggregate Traces And Convert To Plans

The preferred flow now collects several PEBS/LBR traces and aggregates samples
before choosing targets. This reduces the chance that one sparse PEBS run
overfits a few singleton miss PCs.

```bash
TRACE_RUNS=3 TRACE_DURATION_SEC=60 TRACE_SAMPLE_PERIOD=100000 \
  llvm_prefetchit/scripts/run_l2_trace_aggregation.sh
```

This writes three coverage-based all-path plans:

- `cov50_allpaths_d4_16_o0`
- `cov75_allpaths_d4_16_o0`
- `cov100_allpaths_d4_16_o0`

Each target is identified at containing-symbol plus 64B cacheline granularity,
not only by `function:file:line`.

## Convert Trace To Plan Directly

```bash
python3 llvm_prefetchit/tools/prefetchit_trace_to_plan.py \
  --trace-dir results/trace/verilator-qsort-highrate/l2_miss \
  --trace-dir results/trace/verilator-qsort-highrate-repeat/l2_miss \
  --binary results/prefetchit_builds/binaries/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig-baseline \
  --top-k 999999 \
  --target-coverage-pct 75 \
  --depth 16 \
  --depth-min 4 \
  --site-budget-per-target 0 \
  --selection-mode all-paths \
  --prefetch-mnemonic prefetcht1 \
  --prefetch-byte-offsets 0,64,128,192 \
  --output /tmp/prefetchit.plan.json
```

Use `--prefetch-mnemonic prefetcht2` for an L3/LLC-biased prefetch hint, or
override at pass time with `-prefetchit-mnemonic=prefetcht2`.

## Run The Pass

```bash
opt-19 \
  -load-pass-plugin llvm_prefetchit/build/PrefetchITPass.so \
  -passes=prefetchit-inject \
  -prefetchit-plan=/path/to/prefetchit.plan.json \
  input.ll -S -o output.prefetch.ll
```

The plugin also registers itself for clang pass-plugin use. At `-O1` and above
it runs at the optimizer-last extension point so inserted inline asm is less
likely to be cloned, sunk, or otherwise reshaped by later IR optimization. At
`-O0` it runs at pipeline start.

Run the smoke test:

```bash
llvm_prefetchit/tests/smoke/run_smoke.sh llvm_prefetchit/build
```

The smoke test verifies both `prefetcht1` and `prefetcht2` lowering to
PC-relative assembly.

## Plan Format

The pass consumes JSON with schema `prefetchit.plan.v1`. The converter emits
one `injections` entry per selected `(target, site)` pair. Each entry carries:

- `target`: mangled function, demangled function, file, line, and representative
  binary address/cacheline/symbol-offset for the missed target instruction.
- `site`: mangled function, demangled function, file, line, LBR branch type,
  selected LBR depth, and representative binary address/cacheline/symbol-offset
  for the injection site.
- `prefetch_mnemonic`: optional per-injection mnemonic.
- coverage fields: observed samples, newly covered samples, and cumulative
  target coverage after site selection.
- `prefetch.byte_offsets`: target-block-relative cacheline span offsets. The
  default is `0`; aggressive experiments use values like `0,64,128,192` to
  cover sampled-PC/source-line ambiguity.

The pass matches functions by mangled IR name first. It then matches source
locations using debug metadata, accepting full-path or suffix-path matches.

Targets without source lines can be kept in the plan with
`--allow-unresolved-targets`. In exact `symbol+offset` mode, target source lines
are not required because the target is addressed by containing text symbol plus
sampled offset. The current IR pass still uses debug metadata for the injection
site; a future MachineFunction/post-isel pass should consume the recorded site
symbol offset directly for exact-PC site anchoring.

Assembly validation checks exact target addresses and exact 64B target
cachelines for `pc-relative-symbol-offset` plans, including multi-cacheline
offset spans. Older `blockaddress` span plans are reported separately because
they intentionally prefetch target-block-relative neighbor lines.
