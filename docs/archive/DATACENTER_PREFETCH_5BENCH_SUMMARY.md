# Datacenter Prefetch Search Summary

Date: 2026-07-09

Goal: find at least five distinct datacenter-style workloads where high L2I
MPKI can be reduced or hidden by either control-flow data-structure prefetching
or PGO-guided code-target prefetch insertion. FeedSim is counted as one
workload.

## Counted Successes

| # | workload | benchmark origin / source | method | config | baseline metric | prefetch metric | speedup | baseline L2I MPKI | prefetch L2I MPKI | notes |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | FeedSim | DCPerf `feedsim` ranking workload | static CF data-structure prefetch | i50m/i100m, q20/q40, t2/t4 | varies | varies | mostly 1.11x-1.50x | 3.0-7.1 | 0.8-1.8 | Prefetches future `ICacheBuster` method target. See `FEEDSIM_PREFETCH_CASE_STUDY.md`. |
| 2 | Django | DCPerf `django_workload` | static generated `ICache_Buster` prefetch | 120s, ib=1M | 14.22 QPS | 33.55 QPS (`d16`) | 2.36x | 84.46 | 46.95 | Prefetches future generated method pointer in `ICacheBuster`. |
| 3 | SetAlgebra | MicroSuite `SetAlgebra` | PGO-guided injection | depth 32, 120s, cov25 | 11160 QPS | 13388 QPS | 1.20x | 24.53 | 20.22 | Best PGO coverage was 25%; higher coverage over-injected. |
| 4 | Router | MicroSuite `Router` | PGO-guided injection | p2_d2_r1, depth 32, 120s, cov100_noomp | 1090 QPS | 3251 QPS | 2.98x | 85.10 | 93.77 | Large QPS gain despite MPKI not dropping; likely hides miss latency / changes work retired. |
| 5 | memcached | standalone memcached 1.6.14 service | static CF data-structure prefetch | 2048 conns, 8 workers, 120s, 5 reps | mean 41577.93 QPS | mean 47847.28 QPS | mean 1.15x, median paired 1.22x | mean 10.75 | mean 9.35 | Prefetches `conn` function-pointer targets: `try_read_command`, `read`, `sendmsg`, `write`. 4/5 reps positive; 3/5 reps exceed 10%. |

## Additional 5-10% Improvements Observed

These rows are not counted as distinct 10%+ successes. They are kept because
they may still be useful for paper discussion, sensitivity plots, or future
follow-up experiments.

| workload | benchmark origin / source | method | config | baseline metric | prefetch metric | speedup | baseline L2I MPKI | prefetch L2I MPKI | result / caveat |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| FeedSim | DCPerf `feedsim` ranking workload | static CF data-structure prefetch | `i100m_q40_t2`, rep2 | 1.04 QPS | 1.11 QPS (`d64`) | 1.067x | 6.70 | 1.65 | Same workload as counted FeedSim success; one paired rep landed in the 5-10% band. Result: `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_combined.csv`. |
| HDSearch | MicroSuite `HDSearch` | PGO-guided injection | synthetic input, `w8_t111`, 30s, `cov75` | 4083.63 QPS | 4351.40 QPS | 1.066x | 79.51 | 77.30 | Screen only. The 120s confirm had many failed responses and mid-tier segfaults, so this is not counted. Result: `llvm_prefetchit/results/datacenter_goal_20260708/hdsearch_synth_pgo_screen_30s/summary.csv`. |
| memcached | standalone memcached 1.6.14 service | static parser-target prefetch | 512 conns, 4 workers, 60s, `getpf` | 55148.97 QPS | 59943.78 QPS | 1.087x | 10.67 | 11.13 | Screen result only. Result: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_allpf_screen_60s/service_screen.csv`. |
| memcached | standalone memcached 1.6.14 service | static parser-target prefetch | 2048 conns, 8 workers, 120s, rep1 `getpf` | 52177.51 QPS | 55054.57 QPS | 1.055x | 8.51 | 8.17 | Single paired rep; later combined/all-target evaluation was stronger but noisier. Result: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_c2048_w8_confirm_120s/service_screen.csv`. |
| memcached | standalone memcached 1.6.14 service | static parser-target prefetch | memtier text, 8 threads, 100 clients, pipeline 1, 8 workers, 30s | 743232.36 ops/s | 781764.65 ops/s | 1.052x | 0.30 | 0.25 | Low-MPKI memtier screen, useful mainly as throughput sensitivity evidence. Result: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_memtier_getpf_screen2_30s/summary.csv`. |
| memcached | standalone memcached 1.6.14 service | static parser-target prefetch | memtier validation screen, 30s, `static_getpf` | 477282.17 ops/s | 504326.82 ops/s | 1.057x | 6.16 | 5.87 | Short validation screen. Result: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_memtier_valid_screen_30s/summary.csv`. |
| memcached | standalone memcached 1.6.14 service | PGO-guided injection | 512 conns, 4 workers, 120s, `cov100` | 56461.95 QPS | 59625.43 QPS | 1.056x | 10.55 | 10.33 | PGO variant showed only mid-single-digit gain and was not robust enough to count. Result: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_pgo_lwppin_512_screen_120s/service_screen.csv`. |
| Router | MicroSuite `Router` | PGO-guided injection | `p2_d1_r1`, depth 64, 60s, `cov100_noomp` | 10511 QPS | 11128 QPS | 1.059x | 21.21 | 22.68 | Config-sweep row. A different high-MPKI Router config produced the counted 2.98x result. Result: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_router_pgo_config_sweep2_60/combined.csv`. |

## Important Artifacts

FeedSim:
- Case study: `FEEDSIM_PREFETCH_CASE_STUDY.md`
- Results: `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_combined.csv`
- LBR profiles: `llvm_prefetchit/results/tailbench_crossmodule_20260707/feedsim_i50m_profiles`

Django:
- Generator patch: `benchmarks/dcperf/packages/django_workload/templates/gen_icache_buster.py`
- Results: `llvm_prefetchit/results/datacenter_goal_20260708/django_eval_120s_i1m`
- Built libraries: `llvm_prefetchit/work/datacenter_goal_20260708/django/icb_base`, `icb_d16`, `icb_d64`

SetAlgebra:
- Results: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_set_pgo_eval_120`
- Plans: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_set_pgo_plans`
- Profiles: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_set_pgo_profiles`
- Best plan branch-type mix, sample-weighted: COND 50.18%, UNCOND 23.68%, CALL 19.56%, RET 3.62%, IND 2.95%.
- Target overlap, weighted Jaccard: rep1/2 0.986, rep1/3 0.175, rep2/3 0.177. Rep3 had far fewer samples.

Router:
- Results: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_router_p2d2r1_d32_confirm_120`
- Plans: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_router_pgo_plans`
- Profiles: `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_router_pgo_profiles`
- Best plan branch-type mix, sample-weighted: COND 42.44%, CALL 26.31%, RET 14.59%, UNCOND 7.33%, IND 6.75%, IND_CALL 2.58%.
- Target overlap, weighted Jaccard: rep1/2 0.983, rep1/3 0.992, rep2/3 0.991.

memcached:
- Static-allpf source copy: `llvm_prefetchit/work/datacenter_goal_20260708/memcached/static_allpf/memcached.c`
- Confirmed results: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_allpf_c2048_w8_confirm_120s/service_screen.csv`
- 120s paired speedups: 1.288x, 1.287x, 0.936x, 1.221x, 1.032x.
- Screen that found the config: `llvm_prefetchit/results/datacenter_goal_20260708/memcached_allpf_screen_60s/service_screen.csv`

## Static Technique Applicability

Static control-flow data-structure prefetch worked well for FeedSim, Django,
and memcached. In all three, the program stores future control-flow in an
explicit data structure:

- FeedSim/Django: generated `ICacheBuster` method-pointer array.
- memcached: per-connection function pointers in `struct conn`.

The same simple static idea did not carry over to all PGO wins:

- Router: a naive static `ProcessRequest` prefetch variant was slower than
  baseline. PGO-guided code-target injection was the successful method.
- SetAlgebra: static `ProcessRequest` prefetch did not explain the PGO win.
  The useful PGO targets included `ProcessResponses`, `GetTimeInMicro`,
  STL map/tree, protobuf/gRPC paths, and service code.

## Not Counted

- HDSearch: high MPKI and short synthetic-input screen showed potential, but
  120s runs produced many failed responses and mid-tier segmentation faults.
  Result kept at `llvm_prefetchit/results/datacenter_goal_20260708/hdsearch_synth_cov75_w4_confirm_120s/summary.csv`.
- Recommend: high MPKI, but best measured PGO gain was about 3.9%.
- TailBench Silo/Shore/Masstree/Xapian/Moses: some high MPKI, but PGO/static
  variants stayed around neutral to low single-digit speedups.
- FleetBench proto arena: high MPKI, but PGO/static variants were around
  neutral or slower.
- Redis, HAProxy, Postgres, RocksDB/LevelDB, nginx, video transcode, WAMR/wasm3,
  QuickJS, DCPerf TAO: low MPKI or no robust speedup.
- WDL: local benchmark binaries were missing, so earlier screen only measured
  startup failures and was not meaningful.

## Disk Notes

Raw perf/LBR data was kept minimal where possible. Most durable artifacts are
CSV summaries, selected plans, and built binaries under:

- `llvm_prefetchit/results/datacenter_goal_20260708`
- `llvm_prefetchit/work/datacenter_goal_20260708`
