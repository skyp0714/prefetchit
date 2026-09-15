# Datacenter Benchmark Attempt Matrix

Date: 2026-07-10

This note separates three different meanings that were easy to mix together in
the previous summaries:

- Manual control-flow injection: source-level or generator-level
  `__builtin_prefetch`/prefetch insertion after identifying an explicit
  control-flow data structure such as a function-pointer array or dispatch
  field.
- Static compiler injection: LLVM `prefetchit` pass driven by statically chosen
  targets/injection sites, without LBR/PGO target selection.
- PGO compiler injection: L2I-miss/LBR profile -> plan -> LLVM `prefetchit`
  pass.

Bottom line: the datacenter search did not only run PGO. It also tried many
manual control-flow/source injections. However, the robust datacenter results
currently do not include a systematic static compiler-injection-pass sweep.
The positive non-PGO results below are manual/source-level control-flow
injections, not static compiler-pass results. PGO compiler-pass results are
listed separately as reference data.

## Non-PGO Attempts

This is the main table for static/manual work. PGO-only results are excluded
from the speedup column here and moved to the next section.

| benchmark set | workload / benchmark | max non-PGO perf change observed | injection class | best method / variant | evidence | notes |
|---|---|---:|---|---|---|---|
| DCPerf | FeedSim `LeafNodeRank` | +31.2% QPS aggregate, +7.4% to +31.2% across confirmed configs | manual control-flow injection | prefetch future `ICacheBuster::methods_` target, best confirmed `i50m_q20_t2` `d64` | `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_combined.csv` | Strong static/data-structure case. Not LLVM static compiler pass. |
| DCPerf | Django workload | +135.9% QPS | manual control-flow injection | generated `ICache_Buster` target prefetch, `d16` | `llvm_prefetchit/results/datacenter_goal_20260708/django_eval_120s_i1m` | Strong static/data-structure case. Not LLVM static compiler pass. |
| DCPerf | TAO / TaoBench direct | N/A, screen only | none | L2I screen | `llvm_prefetchit/results/datacenter_goal_20260708/taobench_direct_screen_30s/summary.csv` | L2I MPKI was very low, so no injection was pursued. |
| DCPerf | Video transcode | N/A, screen only | none | AOM/SVT/x264 L2I screen | `llvm_prefetchit/results/datacenter_goal_20260708/video_transcode_l2_screen/summary.csv` | L2I MPKI was low. |
| DCPerf | WDL / lzbench subbenchmarks | N/A, screen only | none | lzbench and WDL subbench screens | `llvm_prefetchit/results/datacenter_goal_20260708/wdl_lzbench_*`, `wdl_subbench_l2_screen` | lzbench MPKI was low; some official WDL subbench runs failed due missing/local binary issues. |
| DeathStarBench | UrlShorten service | -4.1% QPS | manual control-flow injection | `static_dispatch` | `llvm_prefetchit/results/datacenter_goal_20260708/dsb_url_eval_smoke/summary.csv` | Low-MPKI smoke; source static dispatch prefetch was slower. |
| DeathStarBench | UniqueId service | N/A, screen only | none | base smoke | `llvm_prefetchit/results/datacenter_goal_20260708/dsb_uniqueid_smoke_30s/summary.csv` | Low L2I MPKI. |
| DeathStarBench | Text/Social/Media service setup | N/A, build/config/screen only | none | local build and screen attempts | `llvm_prefetchit/results/datacenter_goal_20260708/dsb_*` | No positive injection result was produced. |
| MicroSuite | SetAlgebra | no valid positive non-PGO result | manual control-flow injection | `ProcessRequest` prefetch attempt | `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_set_process_pf_d32_120/summary.csv` | The comparable manual/static path did not explain the PGO win. |
| MicroSuite | Router | -8.0% QPS | manual control-flow injection | `ProcessRequest` prefetch | `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_router_static_base_120/summary.csv`, `microsuite_router_static_process_pf_120/summary.csv` | Manual static prefetch was slower; PGO was the successful method. |
| MicroSuite | Recommend | no positive non-PGO result recorded | none / screen only for non-PGO | config screens | `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_recommend_*` | Only PGO produced a small positive result. |
| MicroSuite | HDSearch | no valid positive non-PGO result | manual control-flow injection | process/window/static variants | `llvm_prefetchit/results/datacenter_goal_20260708/hdsearch_static_*`, `hdsearch_process_pf_w8_120s` | Static/manual runs were invalid or did not report valid QPS. |
| TailBench | Silo | -0.3% QPS | manual control-flow injection | function-target prefetch rebuild | `llvm_prefetchit/results/datacenter_goal_20260708/silo_fn_prefetch_eval_120s/runs.csv` | Pinned 120s rebuild was slightly slower. |
| TailBench | Xapian, Moses, Masstree, Shore, Sphinx, Img-DNN | N/A for non-PGO | none / PGO only | L2I screens and PGO sweeps | `llvm_prefetchit/results/datacenter_goal_20260708/tailbench_integrated_l2_screen*`, `llvm_prefetchit/results/tailbench_*` | No manual/static compiler positive result was produced. |
| FleetBench | Proto arena benchmark | +1.1% runtime | manual/static source variant | `static_d8s2` | `llvm_prefetchit/results/datacenter_goal_20260708/fleet_proto_static_sweep/summary.csv` | Small single benchmark improvement; not robust enough to count. |
| FleetBench | Built-in FleetBench microbenchmarks | N/A, screen only | none | all-benchmark L2I screen | `llvm_prefetchit/results/datacenter_goal_20260708/fleetbench_all_l2_screen/summary.csv` | Most MPKI values were very low. |
| Standalone service | memcached 1.6.14 | +28.8% best paired rep, +15.3% mean over 5 reps | manual control-flow injection | `allpf`: prefetch `conn` function-pointer targets | `llvm_prefetchit/results/datacenter_goal_20260708/memcached_allpf_c2048_w8_confirm_120s/service_screen.csv` | Strong manual static/data-structure case; noisy but 4/5 reps positive. |
| Standalone service | HAProxy | +0.1% QPS | manual control-flow injection | `taskpf` | `llvm_prefetchit/results/datacenter_goal_20260708/haproxy_taskpf_real_r200k_120s/summary.csv` | Effect was effectively neutral. |
| Standalone service | Redis | +0.47% QPS | manual control-flow injection | command-path prefetch `cmdpf` | `llvm_prefetchit/results/datacenter_goal_20260708/redis_cmdmix_cmdpf_screen_30s/summary.csv` | Low MPKI; negligible speedup. |
| Standalone service | PostgreSQL | +0.87% TPS | manual control-flow injection | `execpf_simple`; `fmgrpf` was +0.50%, expression variants slower | `llvm_prefetchit/results/datacenter_goal_20260708/postgres_execpf_eval_120s/combined.csv`, `postgres_fmgrpf_eval_120s/combined.csv`, `postgres_expr_static_eval_120s/combined.csv` | High MPKI but manual dispatch prefetch did not translate to meaningful TPS. |
| Standalone KV/DB | LevelDB / RocksDB | N/A, screen only | none | db_bench screens | `llvm_prefetchit/results/datacenter_goal_20260708/leveldb_l2_screen/summary.csv`, `rocksdb_l2_screen/summary.csv` | Low MPKI. |
| Standalone / web | nginx | N/A, screen only | none | base screen | `llvm_prefetchit/results/datacenter_goal_20260708/nginx_screen_base` | No durable injection result. |
| Interpreters / serverless | QuickJS, SQLite, WAMR, wasm3, Python serverless miniapps | N/A, screen only | none | L2I screens | `llvm_prefetchit/results/datacenter_goal_20260708/interpreter_l2_screen_233706`, `wamr_l2_screen`, `wasm3_eval`, `serverless_py_screen` | Low MPKI or no positive injection candidate. |
| Folly / CacheLib family | Folly microbenchmarks, CacheLib build probe | N/A, screen/build only | none | microbenchmark screens / build attempts | `llvm_prefetchit/results/datacenter_goal_20260708/folly_*`, `cachelib_*` | Mostly low MPKI or build/screen only. |

## Static Compiler Injection Status

| category | status |
|---|---|
| Static compiler injection, non-PGO target/site lists | No robust datacenter result currently recorded. This was not systematically swept across the datacenter workloads. |
| Manual control-flow injection | Yes. This is what produced FeedSim, Django, and memcached positives, and it was also tried as negative controls on Router, SetAlgebra, HDSearch, Silo, HAProxy, Redis, PostgreSQL, DeathStarBench UrlShorten, and FleetBench proto. |
| PGO compiler injection | Yes. Results are reference-only in the next section. |

## PGO Compiler-Injection Reference

These use L2I/LBR profile-guided target/site selection and the LLVM
`prefetchit` pass. They are separated from the non-PGO table above.

| benchmark set | workload / benchmark | max PGO perf change observed | best PGO variant | evidence | caveat |
|---|---|---:|---|---|---|
| MicroSuite | Router | +198.3% QPS | `cov100_noomp`, `p2_d2_r1`, depth 32, 120s | `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_router_p2d2r1_d32_confirm_120/combined.csv` | Strongest PGO result; manual static `ProcessRequest` prefetch was slower. |
| MicroSuite | SetAlgebra | +20.0% QPS | `cov25`, depth 32, 120s | `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_set_pgo_eval_120` | Higher coverage over-injected. |
| MicroSuite | Recommend | +3.9% QPS | `cov50`, r4 depth 8, 120s | `llvm_prefetchit/results/datacenter_goal_20260708/microsuite_recommend_pgo_r4_eval_120/aggregate_clean.csv` | Useful as low-single-digit reference only. |
| MicroSuite | HDSearch | +6.6% QPS short screen | `cov75`, synthetic input, 30s | `llvm_prefetchit/results/datacenter_goal_20260708/hdsearch_synth_pgo_screen_30s/summary.csv` | Not counted: 120s confirm had failures/segfaults or no robust gain. |
| FleetBench | Proto arena benchmark | +0.8% runtime best quick run, +0.2% in cov sweep | `d4cov50` / `cov50` | `llvm_prefetchit/results/datacenter_goal_20260708/fleet_proto_noarena_quick/summary.csv`, `fleet_proto_eval_cov_sweep/summary.csv` | Neutral overall. |
| Standalone service | memcached | +5.6% QPS in 512-conn 120s run; +28.7% in a noisy single stress row | `cov100` | `llvm_prefetchit/results/datacenter_goal_20260708/memcached_pgo_lwppin_512_screen_120s/service_screen.csv`, `memcached_pgo_lwppin_stress_120s/service_screen.csv` | Manual all-target `conn` prefetch was the more defensible non-PGO result. |
| Standalone service | PostgreSQL | +0.18% TPS | global `cov25` | `llvm_prefetchit/results/datacenter_goal_20260708/postgres_pgo_global_cov25_eval_120s` | Effectively neutral. |
| TailBench | Silo | about +2-3% in short/quick PGO runs, near neutral in later screens | cross-module/coverage variants | `llvm_prefetchit/results/tailbench_pgo_20260706/eval_summary.csv`, `tailbench_crossmodule_20260707`, `datacenter_goal_20260708/tailbench_saturation_screen_20260708_214834` | Not robust and below target. |
| TailBench | Xapian, Moses, Masstree, Shore, Sphinx, Img-DNN | neutral to slower | coverage sweeps | `llvm_prefetchit/results/tailbench_*`, `llvm_prefetchit/results/datacenter_goal_20260708/tailbench_integrated_l2_screen*` | No meaningful positive result. |

## Reading This Table

- If the question is "did we only do PGO?", the answer is no.
- If the question is "did we already prove the LLVM static compiler-injection
  path on datacenter workloads?", the answer is also no. The successful
  datacenter static cases are currently manual/source-level control-flow
  injections.
- Therefore, the next clean step for the paper claim is to run the latest
  static target/site selection through the compiler pass on the manual-positive
  structures first: FeedSim/Django `ICacheBuster` and memcached `conn`
  function-pointer dispatch.
