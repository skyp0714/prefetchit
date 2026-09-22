# Static COND Target Selection Algorithm V1

This document describes the profile-free static analysis used to rank likely
COND-branch instruction-miss targets. PGO/LBR samples are used only to evaluate
whether the static ranking overlaps measured COND miss targets.

## Problem

For RET misses, the target is structurally clear: the instruction after a call.
For COND misses, the target is the actual destination reached by a conditional
branch. Without running the program, the compiler does not know which branch
directions are dynamically hot.

The static objective is therefore not to exactly predict dynamic frequency. The
objective is to rank branch-target cachelines that are structurally likely to be
I-side cold:

```text
conditional branch -> explicit taken target cacheline
```

## Target Unit

The target unit is:

```text
(target_function, target_cacheline64)
```

where `target_cacheline64 = target_addr & ~0x3f`.

The candidate generator scans direct conditional branches and emits the explicit
taken target. Fallthrough targets are not emitted by default because LBR COND
records correspond to taken conditional branches in the measured traces.

This also matches the frontend-prefetching intuition:

1. The fallthrough/next-line path is usually already spatially close to the
   current fetch stream and often shares the current or next cacheline.
2. The predicted/likely path has a better chance of being fetched by normal
   frontend mechanisms such as FDIP.
3. The useful prefetch target is therefore the non-fallthrough taken edge,
   especially when it enters a sparse side block or a far-away code region.

The algorithm cannot know true branch likelihood without profile data, so it
uses static approximations:

| Dynamic idea | Static approximation |
|---|---|
| Unlikely side target | Explicit taken target of a guard-like conditional branch |
| Target not in fetch stream | Non-fallthrough successor only |
| Sparse/cold block | Low branch density after the target |
| Far jump target | Span-oriented tail ranking |

## Static Inputs

| Input | Source | Use |
|---|---|---|
| Function boundaries and sizes | `llvm-nm -S -n --defined-only --demangle` | Function footprint and cacheline count |
| Conditional branches | `llvm-objdump -d --demangle --no-show-raw-insn --section=.text` | Candidate target edges |
| Local branch density | Disassembly windows around target | Side-exit / sparse-target detection |
| Backedges | Backward conditional branches | Loop-depth estimate |
| Loop reachability | Calls inside static loop regions | Profile-free hotness proxy |

No PGO sample count, function name allowlist, source line, or target address
from the trace is used in candidate generation.

## Candidate Features

For each conditional branch target:

| Feature | Meaning |
|---|---|
| `direction` | Forward/backward relative to branch source |
| `span_bytes` | Static distance from branch source to target |
| `target_position` | Target offset divided by function size |
| `branch_before_4k` | Branch count in 4KB before target |
| `branch_after_4k` | Branch count in 4KB after target |
| `branch_before_16k` | Branch count in 16KB before target |
| `branch_after_16k` | Branch count in 16KB after target |
| `target_incoming_cacheline_edges` | Static incoming branch edges to same cacheline |
| `loop_depth_est` | Number of static backedge regions covering target |
| `loop_hot_distance` | Distance from static loop-reachable roots |

## Insight From PGO COND Samples

The PGO trace was used only to inspect feature distributions and evaluate
ranking quality. The strongest general pattern was:

1. Most high-sample COND targets are explicit taken targets.
2. High-sample targets are usually forward branches.
3. Many high-sample targets have short source-to-target span.
4. The target block often has sparse immediate successor-side branch activity.
5. Very long span/backedge targets were over-ranked by the first static rules.

This led to a two-stage ranking:

```text
stage 1: tail-sparse prefix
stage 2: span-oriented tail
```

## Stage 1: Tail-Sparse Prefix

The first 10k targets are selected by the `tail-sparse` score:

```text
score =
    hotness_and_function_size_common_terms
  + forward_taken_bonus
  + target_position_bonus
  + sparse_after_target_bonus
  + short_span_bonus
  + modest_branch_before_bonus
  - after_target_branch_density_penalty
  - long_span_penalty
```

This captures high-value guard/side-exit style targets near sparse blocks.
It intentionally excludes fallthrough/next-line targets.

## Stage 2: Span Tail

After the first 10k tail-sparse targets, the remaining candidates are appended
from a span-oriented ranking. This improves broad coverage at larger K without
damaging the high-value prefix.

This stage is where far-away jump targets are brought in aggressively. The
reason it is not used as the first-stage ranking is empirical: span-only ranking
over-ranked many very long static edges and hurt small-K recall. It is useful as
a coverage tail, not as the high-priority prefix.

The resulting hybrid order is:

```text
hybrid = top 10k(tail-sparse) + remaining(span order) + remaining(tail-sparse order)
```

Duplicates are removed by `(target_function, target_cacheline64)`.

## Current Results

Evaluation used three baseline qsort L2I PEBS/LBR traces:

```text
llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace01/l2_miss
llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace02/l2_miss
llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace03/l2_miss
```

Ground truth:

| Metric | Value |
|---|---:|
| Resolved COND samples | 47,577 |
| Unique COND target cachelines | 19,221 |

Hybrid `tail10k + span` coverage:

| Top K | Weighted recall | Unique recall | Hit samples |
|---:|---:|---:|---:|
| 1,000 | 5.91% | 1.90% | 2,810 |
| 5,000 | 12.75% | 7.49% | 6,065 |
| 10,000 | 18.67% | 12.95% | 8,885 |
| 25,000 | 26.62% | 22.12% | 12,663 |
| 50,000 | 56.49% | 54.93% | 26,877 |
| 100,000 | 80.57% | 81.61% | 38,331 |
| 150,000 | 100.00% | 99.99% | 47,576 |

## Interpretation

Top high-sample targets can be ranked very highly using static structure. The
remaining COND samples are widely distributed across many similar branch targets
with nearly identical static features. That limits top-5k recall without using
dynamic information.

The practical static target selection should therefore use coverage-based K
rather than a very small top-K:

| Coverage goal | Static K |
|---|---:|
| Fast small test | 10k |
| Moderate coverage | 50k |
| High coverage | 100k |
| Near-superset of measured COND targets | 150k |

## Anti-Overfitting Constraints

The current algorithm deliberately avoids:

1. Hard-coded symbol names.
2. Hard-coded source files or source lines.
3. PGO-derived target allowlists.
4. PGO-derived sample counts in scoring.
5. Manual target address ranges.

The PGO trace is used only to validate the static ranking and to motivate
general features such as taken-only candidates, sparse target blocks, and
two-stage ranking.
