# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1181.518 | 3.316 | 5.821 | 5894.859 | 5807.319 | 85.764 |
| call256_nop | 1180.121 | 3.320 | 5.846 | 5898.700 | 5816.178 | 85.794 |
| call256 | 1190.663 | 3.290 | 5.802 | 5849.306 | 5766.749 | 85.821 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1240.906 | 1118.988 | 121.917 |
| original / Native 3 | 1805.842 | 630.281 | 1175.561 |
| original / Nginx | 554.283 | 430.506 | 123.776 |
| original / Jaeger | 353.650 | 333.214 | 20.436 |
| original / Other | 1940.179 | 1045.829 | 894.350 |
| call256_nop / MongoDB 3 | 1254.685 | 1130.644 | 124.041 |
| call256_nop / Native 3 | 1806.353 | 627.637 | 1178.716 |
| call256_nop / Nginx | 543.224 | 419.115 | 124.109 |
| call256_nop / Jaeger | 357.948 | 334.764 | 23.184 |
| call256_nop / Other | 1936.489 | 1047.408 | 889.082 |
| call256 / MongoDB 3 | 1179.293 | 1055.713 | 123.581 |
| call256 / Native 3 | 1809.874 | 630.767 | 1179.108 |
| call256 / Nginx | 555.652 | 431.340 | 124.312 |
| call256 / Jaeger | 361.247 | 340.242 | 21.004 |
| call256 / Other | 1943.240 | 1047.479 | 895.761 |

Original Native-3 plus Mongo-3 user time: 29.67% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
