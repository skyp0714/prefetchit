# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| split75 | 1191.927 | 3.285 | 5.824 | 5834.115 | 5755.344 | 85.748 |
| extra_nop | 1177.458 | 3.326 | 5.845 | 5866.948 | 5788.305 | 85.187 |
| extra_it0 | 1178.004 | 3.324 | 5.813 | 5847.056 | 5766.786 | 84.916 |
| extra_t1 | 1182.133 | 3.314 | 5.783 | 5874.168 | 5793.971 | 85.600 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| split75 / MongoDB 3 | 1133.271 | 1008.813 | 124.458 |
| split75 / Native 3 | 1817.863 | 631.370 | 1186.493 |
| split75 / Nginx | 574.387 | 446.067 | 128.320 |
| split75 / Jaeger | 358.568 | 337.226 | 21.342 |
| split75 / Other | 1950.025 | 1055.064 | 894.961 |
| extra_nop / MongoDB 3 | 1136.259 | 1011.550 | 124.709 |
| extra_nop / Native 3 | 1818.954 | 633.528 | 1185.426 |
| extra_nop / Nginx | 593.373 | 467.847 | 125.526 |
| extra_nop / Jaeger | 361.246 | 339.550 | 21.696 |
| extra_nop / Other | 1957.116 | 1061.347 | 895.769 |
| extra_it0 / MongoDB 3 | 1138.198 | 1013.691 | 124.507 |
| extra_it0 / Native 3 | 1820.397 | 639.233 | 1181.164 |
| extra_it0 / Nginx | 569.598 | 445.331 | 124.268 |
| extra_it0 / Jaeger | 359.625 | 338.713 | 20.912 |
| extra_it0 / Other | 1959.236 | 1061.136 | 898.101 |
| extra_t1 / MongoDB 3 | 1135.402 | 1010.548 | 124.854 |
| extra_t1 / Native 3 | 1813.798 | 631.276 | 1182.522 |
| extra_t1 / Nginx | 614.677 | 488.703 | 125.974 |
| extra_t1 / Jaeger | 359.658 | 338.356 | 21.302 |
| extra_t1 / Other | 1950.634 | 1057.020 | 893.614 |

split75 Native-3 plus Mongo-3 user time: 28.11% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
