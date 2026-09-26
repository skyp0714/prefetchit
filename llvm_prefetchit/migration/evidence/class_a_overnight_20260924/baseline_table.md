| Baseline / class | L2 code MPKI | Retiring | Bad spec | FE-bound | BE-bound | Setting |
|---|---:|---:|---:|---:|---:|---|
| A-1 Arcilator | 79.289 | 11.76% | 0.39% | 87.06% | 0.78% | 20k-cycle driver; no loaded RISC-V payload |
| A-1 Verilator | 57.237 | not collected | not collected | not collected | not collected | 100k-cycle qsort prefix |
| A-2 protobuf | 16.525 | not collected | not collected | not collected | not collected | ProtoArena,100iterations,seed0 |
| A-2 LLVM | 1.516 | not collected | not collected | not collected | not collected | Full two-input reference mix; count-weighted aggregate |
| A-3 FeedSim | 3.598 | 36.72% | 9.95% | 39.44% | 14.25% | Full v2,40QPS |
| A-3 Scylla / B regime | 12.527 | 15.74% | 5.96% | 54.02% | 25.64% | YCSB20kops/s + MySQL400TPS shared4cores |
| A-2 MySQL | 4.287 | 33.74% | 6.60% | 39.36% | 21.35% | Standalone durable OLTP400TPS |
