# Static RET-Prefetch Algorithm V2

This document describes the current profile-free static algorithm used to find
RET-miss prefetch targets and injection sites for the Verilator simulator. The
runtime profiles are used only for evaluation and validation, not for scoring
the static candidates.

## Goal

The pass inserts `prefetcht1` instructions that fetch return-continuation
instruction cachelines before a later `RET` transfers control back to those
continuations.

The target unit is a 64-byte instruction cacheline containing the instruction
immediately after a statically visible call instruction:

```text
caller:
    call callee
target:
    next instruction after call
```

If the callee or deeper nested callees execute enough code before returning,
the caller continuation may miss in the I-side hierarchy. The static algorithm
tries to predict these return-continuation cachelines without using PEBS/LBR
sample counts.

## Inputs

The algorithm consumes only binary-level static information:

| Input | Source | Purpose |
|---|---|---|
| Text symbols | `llvm-nm -S -n --defined-only --demangle` | Function boundaries and sizes |
| Disassembly | `llvm-objdump -d --demangle --no-show-raw-insn --section=.text` | Calls, branches, returns, loop-like backedges |
| RAS size | Parameter, default `32` | Estimate whether deep call paths can exceed return-address-stack capacity |
| Verilator steady-state roots | Default eval/eval_nba symbols | Prefer simulation-loop code over one-shot initialization/finalization code |

The PEBS/LBR trace is used later only to compute target recall and injection-site
coverage against measured RET-miss samples.

## Target Candidate Generation

The generator scans every text function and records direct callsites. For each
callsite, it emits one candidate target:

| Field | Meaning |
|---|---|
| `target_function` | Caller function containing the return continuation |
| `target_addr` | Address of the instruction immediately after the call |
| `target_cacheline64` | `target_addr & ~0x3f` |
| `call_addr` | Address of the call that creates this return target |
| `callee_function` | Static callee symbol, or unresolved/external callee |

Duplicate targets are collapsed at `(target_function, target_cacheline64)`.
When multiple callsites map to the same cacheline, the highest-scoring callsite
keeps the representative metadata.

## Static Cost Model

For every callsite, the base score estimates whether the continuation cacheline
is likely to be absent when the callee returns. The main terms are:

| Term | Intuition |
|---|---|
| Caller footprint | Larger caller functions have more return-continuation lines that can be cold |
| Callee footprint | Larger callees execute more instruction footprint before returning |
| Caller fanout | More callsites imply more divergent return paths |
| Caller/callee backedges | Loop-like code increases dynamic residency pressure |
| Layout distance | Farther callee/caller layout distance weakens locality |
| Root hotness | Functions reachable from the steady-state Verilator loop are favored |
| RAS overflow estimate | Deep static call chains beyond `ras_size` increase RET risk |
| One-shot penalty | Initialization/finalization functions are strongly deprioritized |
| External call handling | Unresolved calls are retained with a conservative synthetic footprint |

The current combined score is:

```text
score =
    hot_bonus
  + 4.5 * log2(caller_cachelines + 1)
  + 5.5 * log2(callee_cachelines + 1)
  + 1.2 * log2(caller_call_count + 1)
  + 1.5 * loop_bonus
  + 2.5 * log2(layout_distance_kb + 1)
  + 35.0 * min(ras_overflow, 8)
  + 0.7 * log2(depth_down + 1)
  + 0.1 * continuation_position
  - one_shot_penalty
  - external_penalty
```

For the current best static experiments, the first-stage ordering uses the
`nested` mode, which starts from footprint-style callsite risk and then expands
into nested callees.

## Nested Re-Ranking

The main correction in V2 is that hot RET misses were often not located in the
outer caller's immediate continuation. Instead, they appeared in helper
functions reached from hot generated Verilator functions.

The nested re-ranking procedure is:

1. Sort all static candidates by the base static score.
2. Take the first `nested_base_count` callsites as hot parent callsites.
3. Treat each hot parent callee as a hot function context.
4. For each hot callee, collect return-continuation targets inside that callee.
5. Score those nested targets using parent hotness plus local helper/external
   call risk.
6. Optionally interleave hot callees round-robin so top-K is not dominated by
   one generated helper family.
7. Append the remaining base-order candidates.

The nested local score is:

```text
nested_score =
    parent_hot_score
  + external_call_bonus
  + small_helper_bonus
  + local_base_score
  + layout_distance_bonus
```

This is still profile-free. It uses only call graph structure, code size, call
resolution status, and layout distance.

## Hybrid Tail Re-Ranking

An additional V2 repair path preserves the original high-confidence prefix and
changes only the low-priority tail. This was added because top-25k/top-50k
recall missed many PGO RET samples even though the missing samples had clear
static structure.

The hybrid tail mode:

1. Preserve the first `prefix_count` candidates from the original static order.
2. Deduplicate by `(target_function, target_cacheline64)`.
3. Re-rank the remaining tail by structural risk.
4. Append the re-ranked tail after the preserved prefix.

The best recall-oriented tail mode currently uses external/helper risk first:

```text
tail_score =
    base_score
  + 75 * is_external_or_unresolved_call
  + 25 * is_external_call_in_large_caller
  + 20 * verilator_phase_score(target_function)
  + 5  * log2(layout_distance_kb + 1)
```

This improves high-K recall substantially, but it did not improve runtime in the
latest measurements. The best runtime result still came from the lower-K nested
candidate list plus spread-distance site selection.

## Injection-Site Selection

After selecting target cachelines, a separate static policy chooses where to
insert prefetches. The output is a target/site plan consumed by the LLVM
prefetch insertion pass.

Supported static site policies:

| Strategy | Meaning |
|---|---|
| `callsite` | Insert before the call that creates the return target |
| `callee-ret` | Insert near returns inside the callee |
| `distance-Nk` | Use nearest branches before the target within the same function and `N` KB |
| `spread-distance-Nk` | Use branches before the target, but spread selected sites across the whole `N` KB window |
| `same-func-calls-Nk` | Use prior callsites in the same target function within `N` KB |
| `callee-calls-dD` | Use calls inside the callee call tree up to depth `D` |
| `caller-chain-dD` | Use caller-chain callsites up to depth `D` |
| `mixed-call-ret-d1` | Combine callsite, callee returns, and callee callsites |

The current best static runtime point used:

```text
target selection: nested top-5000
site strategy: spread-distance-64k
site budget: 8
target offsets: 0 and 64 bytes
planned injections: 38505
planned prefetches: 77010
```

The spread policy performed better than simply taking the closest branches. The
reason is timing: using only nearest sites often issues the prefetch too late,
while spreading sites across a 64 KB backward window gives earlier opportunities
on divergent paths.

## LLVM Pass Interface

The static tools emit a JSON prefetch plan with entries equivalent to:

```json
{
  "site_function": "...",
  "site_addr": "0x...",
  "target_function": "...",
  "target_addr": "0x...",
  "prefetch_kind": "prefetcht1"
}
```

The LLVM pass resolves each machine function and inserts a target-specific
prefetch at the selected machine-level site. Target correctness is validated
after compilation by checking:

| Validation | Requirement |
|---|---|
| Assembly count | `prefetcht1` appears in optimized assembly |
| Site mapping | Insertions map to intended site functions/addresses within tolerance |
| Target mapping | Prefetch operand resolves to intended target address/cacheline |
| Numeric output | Runtime/MPKI data contain no NaN, zero, or dummy values |

## Evaluation Metrics

The profile-based evaluator reports:

| Metric | Meaning |
|---|---|
| Target weighted recall | Fraction of RET-miss samples whose target cacheline was selected |
| Site weighted coverage | Fraction of RET-miss samples whose selected target also had at least one selected site on the sample LBR path |
| Conditional site coverage | Site coverage divided by target-hit samples |
| Runtime | Wall-clock runtime from detailed profile iterations |
| L2I MPKI | L2 instruction-miss MPKI from perf frontend events |

## Current Measured Behavior

The latest measured comparison shows:

| Scheme | Runtime | Speedup vs baseline | L2I MPKI | Notes |
|---|---:|---:|---:|---|
| Baseline | 343.241 s | 0.00% | 58.756 | No prefetch |
| PGO RET 100% | 288.747 s | 18.87% | 53.143 | Uses measured LBR RET targets/sites |
| Static nested top5000 spread64 b8 | 293.463 s | 16.96% | 52.565 | Best static runtime result |
| Static hybrid top25k mixed b8 | 317.482 s | 8.11% | 56.379 | Higher recall but worse runtime |

The main conclusion is that recall alone is not enough. The static algorithm
must control timing and instruction overhead. The best static result came from a
moderate target set with earlier, spread-out sites, not from the largest recall
target set.

## Known Limitations

1. Indirect calls and unresolved calls are modeled with synthetic size; they are
   retained but not precisely resolved.
2. Static reachability does not provide dynamic path frequency, so extra
   low-value prefetches can pollute the cache or add instruction overhead.
3. The current site policies use static branch/call positions, not exact dynamic
   LBR path probabilities.
4. Large top-K hybrid lists improve PGO target recall but can hurt runtime due
   to over-injection.

## Recommended Next Sweep

Use the best runtime point as the center:

```text
nested top5000, spread-distance-64k, budget 8, offsets 0+64
```

Then sweep one variable at a time:

| Variable | Candidate values |
|---|---|
| Site budget | 4, 6, 8, 10, 12 |
| Distance window | 32 KB, 48 KB, 64 KB, 96 KB |
| Target offsets | `0` vs `0+64` |
| Target count | 3000, 4000, 5000, 7500 |
| Site filter | all branches, call-only, cond-only, call+cond |

The objective is to keep the L2I MPKI reduction of `spread64_b8` while reducing
static instruction overhead.
