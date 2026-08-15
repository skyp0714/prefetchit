# PrefetchIT: Software Instruction Prefetching Experiments

This directory tree contains everything for an ongoing research project (paper in
preparation) on **software instruction prefetching**: injecting data-prefetch
instructions (`prefetcht1`, and the ISA's `prefetchit0/1`) at carefully chosen
sites so that soon-to-be-executed *code* cachelines are pulled into L2/L1I
before the frontend misses on them.

If you are an agent or a new contributor, read this file first, then the
README/docs inside the sub-repo you need.

## Research thesis

1. **Oracle**: an LBR/PEBS profile of frontend misses (`FRONTEND_RETIRED.L2_MISS`
   etc., with LBR call/branch history) gives near-perfect knowledge of *which*
   instruction cachelines miss and *which earlier branches* lead to them. A
   profile-guided ("PGO") plan built from this is the practical upper bound.
2. **Static analysis**: the interesting question is how close a *profile-free*
   static analysis of the binary can get to that oracle. The static algorithms
   must be justifiable in a general sense (structural features: code span,
   branch density, call-graph footprint, RAS-overflow depth, layout distance) —
   not overfit to one workload's profile.
3. **Manual/data-structure prefetch**: some programs store their future control
   flow in an explicit data structure (function-pointer arrays, per-connection
   dispatch fields). There, a small manual source change that prefetches the
   *future* pointer target beats any compiler heuristic. Case studies: FeedSim
   and Django (`ICacheBuster` method arrays), memcached (`struct conn` function
   pointers).

Headline results live in the four top-level notes:

| File | Content |
|---|---|
| `DATACENTER_BENCHMARK_ATTEMPT_MATRIX.md` | Full attempt matrix: every workload tried, manual/static vs PGO outcome, evidence CSV paths. **Start here for numbers.** |
| `DATACENTER_PREFETCH_5BENCH_SUMMARY.md` | The five counted 10%+ datacenter successes (FeedSim, Django, SetAlgebra, Router, memcached) with configs and artifact paths. |
| `DATACENTER_PREFETCH_SEARCH_20260708.md` | Earlier search log for the above. |
| `FEEDSIM_PREFETCH_CASE_STUDY.md` | Deep-dive on the FeedSim manual prefetch. |

## Component map

| Directory | Git repo | Purpose |
|---|---|---|
| `profiling/` | [frontend_profiling](https://github.com/skyp0714/frontend_profiling) | Frontend profiling harness: PEBS/LBR sampling of `FRONTEND_RETIRED.*` events on Intel Granite Rapids (Xeon 6787P), latency profiling, MPKI screens, trace symbolization/reports. Produces the traces that everything downstream consumes. |
| `llvm_prefetchit/` | [llvm_prefetchit_injection](https://github.com/skyp0714/llvm_prefetchit_injection) | The LLVM 19 pass (`prefetchit-inject`, `lib/PrefetchITPass.cpp`) plus the whole plan pipeline: `tools/prefetchit_trace_to_plan.py` (LBR trace → JSON plan), plan filtering/merging tools, per-workload build & evaluation scripts, and 43G of experiment `results/`. |
| `static_cond_prefetch/` | local repo (create GitHub remote) | Profile-free selection of **conditional-branch** prefetch targets from binary-only features (two-stage tail-sparse + span ranking). LBR traces are used only as offline validation oracle. |
| `static_return_prefetch/` | local repo (create GitHub remote) | Profile-free selection of **return-continuation** prefetch targets (static cost model: caller/callee footprint, RAS overflow, layout distance; nested re-ranking) plus injection-site policies (`spread-distance-Nk` etc.). Best result: 16.96% speedup on Verilator qsort vs 18.87% for the PGO oracle. |
| `icache_microbenchmark/` | [icache_microbenchmark](https://github.com/skyp0714/icache_microbenchmark) | Microbenchmark on Xeon 6787P isolating prefetch instruction behavior: `prefetcht0/t1` vs `prefetchit0/1`, TLB-warmth gating, branch-window placement. Key finding: data-prefetch variants warm iTLB/STLB, `prefetchit` alone does not. |
| `benchmarks/` | third-party checkouts | ~105G of benchmark suites: DCPerf, TailBench, MicroSuite (in datacenter_sources), SPEC CPU2017/2026, DeathStarBench, FleetBench, gem5, chipyard, standalone services (memcached, redis, postgres, ...). Own patches live inside (e.g. `dcperf/packages/django_workload/templates/gen_icache_buster.py`). Not tracked by a top-level repo. |
| `worktrees/`, `build/` | gem5 worktrees/builds | gem5 simulator variants for simulation-side prefetch experiments (27G; regenerable). |
| `.tmp/` | – | perfmon/pmu-tools helper checkouts. |

## End-to-end data flow

```
                    (1) profiling/run_pebs_sampling.sh
 workload binary ─────────────────────────────────────►  PEBS+LBR trace (perf.data)
                                                          │ perf script / analyze_pebs_trace.sh
                                                          ▼
                    (2) llvm_prefetchit/tools/prefetchit_trace_to_plan.py
                        targets = hottest (symbol, 64B-cacheline) pairs to coverage %
                        sites   = LBR[d].from branches leading to each target
                                                          ▼
                                  prefetchit.plan.v1 JSON (targets + injection sites)
                                                          │
        static_cond_prefetch / static_return_prefetch ────┤   (alternative: profile-free
        generate plans from binary features only          │    plans, validated vs oracle)
                                                          ▼
                    (3) llvm_prefetchit pass: opt-19 -passes=prefetchit-inject
                        injects `prefetcht1 sym+off(%rip)` at plan sites
                                                          ▼
                    (4) rebuild workload, run paired A/B evaluation
                        (QPS / runtime / L2I MPKI via profiling scripts)
```

Manual case studies (FeedSim/Django/memcached) skip (2)–(3) and instead add
`__builtin_prefetch` of future function-pointer targets directly in source.

## Verifying the flows

- LLVM pass + plan tools: `llvm_prefetchit/tests/smoke/run_smoke.sh llvm_prefetchit/build`
  (builds a toy C file, injects, validates IR+asm) and `python3 -m pytest llvm_prefetchit/tests`.
- Profiling: `profiling/run_pebs_sampling.sh --help`-level checks need only bash;
  real runs need `sudo` + perf on the Granite Rapids host.
- Static selectors: `static_cond_prefetch/scripts/run_cond_static_target_sweep.sh`,
  `static_return_prefetch/scripts/run_ret_cost_v2_static_sweep.sh` (long; Verilator
  workload). Candidate generators can be run standalone on any binary.
- Microbenchmark: `make -C icache_microbenchmark/microbench/src` then
  `run_process_prefetch_experiment.py` (needs sudo for perf counters).

## Conventions

- Results are large and stay out of git (`results/`, `work/` are gitignored);
  durable conclusions get distilled into dated Markdown notes and small CSVs.
- Experiment result directories are named `<topic>_<yyyymmdd>/`.
- The evaluation machine is an Intel Xeon 6787P (Granite Rapids); perf events
  use raw `cpu/event=0xc6,...` encodings when ocperf is unavailable.
