# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| split75 | 1178.746 | 3.322 | 5.797 | 5842.801 | 5767.016 | 84.973 |
| residual_t1 | 1201.153 | 3.259 | 5.876 | 5827.358 | 5741.179 | 86.198 |
| lead512 | 1180.483 | 3.318 | 5.791 | 5848.654 | 5768.037 | 85.113 |
| lead512_nop | 1156.092 | 3.390 | 5.897 | 6010.533 | 5926.257 | 85.631 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| split75 / MongoDB 3 | 1133.962 | 1008.657 | 125.305 |
| split75 / Native 3 | 1821.822 | 634.449 | 1187.373 |
| split75 / Nginx | 572.770 | 447.437 | 125.333 |
| split75 / Jaeger | 359.295 | 337.903 | 21.392 |
| split75 / Other | 1954.953 | 1054.510 | 900.442 |
| residual_t1 / MongoDB 3 | 1134.456 | 1009.476 | 124.980 |
| residual_t1 / Native 3 | 1815.911 | 634.298 | 1181.613 |
| residual_t1 / Nginx | 574.268 | 447.098 | 127.170 |
| residual_t1 / Jaeger | 355.881 | 335.866 | 20.016 |
| residual_t1 / Other | 1946.842 | 1051.191 | 895.652 |
| lead512 / MongoDB 3 | 1142.701 | 1016.596 | 126.104 |
| lead512 / Native 3 | 1818.342 | 637.034 | 1181.308 |
| lead512 / Nginx | 573.149 | 448.621 | 124.529 |
| lead512 / Jaeger | 359.363 | 338.351 | 21.012 |
| lead512 / Other | 1955.099 | 1056.793 | 898.306 |
| lead512_nop / MongoDB 3 | 1276.286 | 1151.134 | 125.152 |
| lead512_nop / Native 3 | 1816.555 | 630.005 | 1186.550 |
| lead512_nop / Nginx | 613.531 | 486.508 | 127.023 |
| lead512_nop / Jaeger | 355.105 | 334.338 | 20.767 |
| lead512_nop / Other | 1949.057 | 1050.343 | 898.713 |

split75 Native-3 plus Mongo-3 user time: 28.12% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
