# static_prefetch — profile-free instruction-prefetch planning (stage 2)

One planner, one command, choose the branch kinds:

```bash
tools/static_plan.py --binary SIM --kinds ret       --out-dir work/ret  --output ret.plan.json
tools/static_plan.py --binary SIM --kinds cond      --out-dir work/cond --output cond.plan.json
tools/static_plan.py --binary SIM --kinds ret,cond  --out-dir work/both --output both.plan.json
```

The plan is `prefetchit.plan.v1` JSON, exactly what the LLVM pass consumes
(`opt-19 -passes=prefetchit-inject -prefetchit-plan=…`, or
`llvm_prefetchit/scripts/static/run_prefetcht1_l2_eval.sh EXTERNAL_PLAN=…`).
Selection reads only the binary (`llvm-nm`, `llvm-objdump`); PEBS/LBR traces
(`--trace-dir`, optional) are used only to score the choice against the
profile-guided oracle.

| kind | engine | target unit | best measured point (Verilator qsort) |
|---|---|---|---|
| `ret` | `tools/ret/` — return-continuation cost model (caller/callee footprint, RAS overflow, layout distance, nested re-ranking) + injection-site policies | cacheline after a direct call | `--ret-top-k 1000 --ret-site-strategy callsite --ret-site-budget 1`: **1.078x** with 1,000 sites, ≥ PGO (1.075x, 20k sites) |
| `cond` | `tools/cond/` — taken-target structural ranking (tail-sparse / fetch-gap / entry-window …) with sample-IP window | conditional branch source/taken cacheline (+window) | `--cond-mode fetch-gap --cond-top-k 100000`: 1.038x (COND misses in flattened code are mostly near; profile is needed for far lookahead) |
| `ret,cond` | merged via `llvm_prefetchit/tools/merge_prefetch_plans.py` | – | MPKI drops further (50.7) but injection overhead cancels the time gain (combo sweep, Aug 2026) |

History: `static_return_prefetch` and `static_cond_prefetch` were separate
repositories until 2026-09-15; both histories are in this repository
(`git log --all`). Algorithm notes: `docs/static_return_algorithm_v2.md`,
`docs/static_cond_algorithm_v1.md`, `docs/static_cond_sampleip_update.md`.

## Layout

| path | content |
|---|---|
| `tools/static_plan.py` | the driver (per-kind options: `--ret-*`, `--cond-*`) |
| `tools/ret/` | `static_return_target_candidates.py` → `static_injection_site_experiment.py` → `static_site_plan_to_prefetch_plan.py`; evaluators, nested re-ranker, `static_branch_target_plan.py` (generic branch-target planner), sweep/summary tools |
| `tools/cond/` | `static_cond_target_candidates.py` → (`hybridize_`/`ensemble_cond_candidates.py`) → `static_cond_candidates_to_plan.py`; `evaluate_static_cond_targets.py`, `sweep_static_cond_algorithms.py` |
| `scripts/` | `run_ret_static_vs_pgo_limit.sh`, `run_ret_cost_v2_static_sweep.sh`, `run_cond_static_target_sweep.sh` — the full sweeps (long; Verilator) |
| `results/` | ignored sweep outputs |

## Measured caveat (2026-09-15 rebuild)

On a freshly built DualMegaBoom simulator the `ret` family's reference point
(`top-1k callsite b1`) executes its prefetches ~5·10⁷ times per 100k
simulated cycles and does not move L2I MPKI: only 15% of the RET-miss
samples are produced by one of the 1,000 chosen calls (the 1,000 hottest
producing calls would cover 65%). The target *lines* are right (62% recall);
the chosen *call* per line is usually not the one that returns into it. The
planner needs a call-level hotness proxy (see the umbrella `docs/TODO.md`, item 1-A).
Evaluate plans with the producing-call metric, not "site anywhere in the LBR
history".

## Site policies (`--ret-site-strategy`)

`callsite` (the call creating the return target), `callee-ret`, `distance-Nk`,
`spread-distance-Nk`, `same-func-calls-Nk`, `caller-chain-dD`,
`callee-calls-dD`, `mixed-call-ret-d1`. Spread policies buy lead time on
divergent paths; the 1,000-callsite plan is the honest ceiling on Verilator.

## Verify

```bash
llvm_prefetchit/scripts/static/run_verilator_repro.sh   # traces → PGO + static plans → builds → NOP twins → 3.8 GHz A/B
```
