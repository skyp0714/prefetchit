# Static COND Prefetch Target Selection

Profile-free (static-analysis-only) selection of conditional-branch
instruction-prefetch targets. Companion to `static_return_prefetch/` (RET
targets) and consumed by the LLVM pass in `llvm_prefetchit/`. PEBS/LBR traces
are used **only for offline evaluation** against the profiled oracle — the
candidate generator and ranker never read profile data.

## Algorithm (V1, see `docs/static_cond_algorithm_v1.md`)

- Target unit: `(target_function, target_cacheline64)` for the explicit taken
  target of each direct conditional branch (fallthrough excluded — it is
  usually already in the fetch stream / covered by FDIP).
- Static inputs only: `llvm-nm` function boundaries, `llvm-objdump`
  disassembly, local branch density, backedges, loop reachability.
- Features per candidate: direction (fwd/back), span bytes, target position,
  branch density before/after target (4KB/16KB windows), incoming edges, loop
  depth, loop hotness distance.
- Two-stage hybrid ranking:
  1. **Tail-sparse prefix** (first 10k): guard/side-exit targets near sparse
     blocks, forward, short-span.
  2. **Span-oriented tail**: remaining candidates ranked by span distance for
     coverage at large K.

## Layout

| Path | Content |
|---|---|
| `tools/static_cond_target_candidates.py` | Candidate generation from a binary |
| `tools/hybridize_cond_candidates.py` | Two-stage hybrid ranking |
| `tools/ensemble_cond_candidates.py` | Ranking ensembles |
| `tools/evaluate_static_cond_targets.py` | Scoring vs LBR COND-miss oracle |
| `tools/static_cond_candidates_to_plan.py` | Emit `prefetchit.plan.v1` JSON for the LLVM pass |
| `tools/sweep_static_cond_algorithms.py` | Full pipeline sweep |
| `scripts/run_cond_static_target_sweep.sh` | Entry point: generation → hybridization → evaluation |
| `docs/` | Algorithm notes (V1, sample-IP update) |
| `results/` | (gitignored, ~3.3G) sweep outputs |

## Current oracle-recall on Verilator qsort COND traces

47,577 resolved COND samples, 19,221 unique target cachelines:

| Top-K static candidates | Weighted recall |
|---:|---:|
| 10k | 18.7% |
| 50k | 56.5% |
| 100k | 80.6% |

## Verify

```bash
./scripts/run_cond_static_target_sweep.sh
```
