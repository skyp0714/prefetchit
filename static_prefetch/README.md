# Static Return Prefetch Target Selection

This directory is intentionally separate from the LLVM prefetch pass. It builds
profile-free return-target candidates from the compiled Verilator binary and uses
PEBS/LBR traces only for offline evaluation.

Initial scope:

1. Generate static return target candidates from direct call return addresses.
2. Score candidates using caller/callee footprint, loop/backedge context, call
   density, and estimated call-chain depth/RAS overflow.
3. Evaluate overlap against profiled RET miss targets at cacheline granularity.
4. Evaluate profile-free injection-site policies against PEBS/LBR traces:
   target topK is chosen from static cost ranking, while LBR is used only to
   validate whether the selected static site appears on the profiled miss path.

The static generator does not read profiling data.

## Headline result (Verilator qsort, real-machine runs)

Static nested top-5000 targets + `spread-distance-64k` sites, budget 8
(38,505 injections, byte offsets 0/64): runtime 293.5s vs baseline 343.2s =
**16.96% speedup**, L2I MPKI 58.76 → 52.57. The LBR/PGO oracle plan reaches
18.87%, so the profile-free selection captures ~90% of the oracle gain.
See `docs/static_return_algorithm_v2.md` for the V2 cost model
(caller/callee footprint, RAS-overflow depth, layout distance, nested
re-ranking of hot-callee contexts).

## Injection-Site Policy Evaluation

Main script:

```bash
python3 static_return_prefetch/tools/static_injection_site_experiment.py \
  --binary benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig \
  --targets static_return_prefetch/results/final_static_return_targets.csv \
  --trace-dir llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace01/l2_miss \
  --trace-dir llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace02/l2_miss \
  --trace-dir llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace03/l2_miss \
  --top-k 1000,10000,50000,100000 \
  --site-budget-list 1,2,4,8,16 \
  --skip-site-csv \
  --out-dir static_return_prefetch/results/site_budget_sweep_v1
```

Implemented site policies:

| Policy | Static rule |
|---|---|
| `callsite` | Site is the call instruction whose fall-through address is the selected return target. |
| `distance-4k` / `distance-16k` / `distance-64k` | Sites are preceding branch instructions in the target function within the static byte window. |
| `same-func-calls-4k` / `same-func-calls-16k` | Sites are preceding call instructions in the target function within the static byte window. |
| `caller-chain-d1` / `caller-chain-d2` | Sites are reverse-call-graph callsites that enter the target function, to depth 1 or 2. |
| `callee-ret` | Sites are return instructions inside the callee. |
| `callee-calls-d1` / `callee-calls-d2` | Sites are call instructions inside the callee call graph to depth 1 or 2. |
| `mixed-call-ret-d1` | Combines callsite, callee returns, and depth-1 callee calls under the per-target site budget. |

Important outputs:

- `site_policy_metrics.csv`: complete topK x strategy x budget metrics.
- `site_policy_summary.md`: compact interpretation and recommended policies.
- `site_coverage_vs_site_pairs_budget8.png`: site coverage vs injection-pair cost.
- `site_coverage_vs_topk_budget_sweep.png`: target topK/budget sweep.
