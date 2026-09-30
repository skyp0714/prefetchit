# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1171.479 | 3.344 | 5.864 | 5921.610 | 5839.138 | 85.505 |
| split75 | 1187.174 | 3.299 | 5.820 | 5838.238 | 5759.149 | 85.463 |
| early_it0 | 1185.371 | 3.304 | 5.796 | 5854.975 | 5774.275 | 85.557 |
| early_t1 | 1190.925 | 3.288 | 5.831 | 5858.115 | 5779.640 | 86.037 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1236.664 | 1114.772 | 121.892 |
| original / Native 3 | 1809.805 | 628.085 | 1181.719 |
| original / Nginx | 573.541 | 446.783 | 126.758 |
| original / Jaeger | 357.222 | 335.463 | 21.759 |
| original / Other | 1944.379 | 1049.068 | 895.311 |
| split75 / MongoDB 3 | 1132.198 | 1007.784 | 124.414 |
| split75 / Native 3 | 1819.490 | 632.967 | 1186.523 |
| split75 / Nginx | 570.806 | 444.459 | 126.348 |
| split75 / Jaeger | 361.944 | 339.927 | 22.017 |
| split75 / Other | 1953.800 | 1057.987 | 895.812 |
| early_it0 / MongoDB 3 | 1153.170 | 1029.524 | 123.646 |
| early_it0 / Native 3 | 1820.647 | 631.766 | 1188.881 |
| early_it0 / Nginx | 566.904 | 440.671 | 126.234 |
| early_it0 / Jaeger | 359.059 | 337.566 | 21.494 |
| early_it0 / Other | 1955.195 | 1057.653 | 897.542 |
| early_t1 / MongoDB 3 | 1153.842 | 1027.788 | 126.055 |
| early_t1 / Native 3 | 1819.700 | 632.119 | 1187.581 |
| early_t1 / Nginx | 572.403 | 445.219 | 127.185 |
| early_t1 / Jaeger | 357.983 | 337.528 | 20.455 |
| early_t1 / Other | 1954.186 | 1056.260 | 897.926 |

original Native-3 plus Mongo-3 user time: 29.43% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
