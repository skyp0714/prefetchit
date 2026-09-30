# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1166.181 | 3.360 | 5.881 | 5946.986 | 5865.176 | 85.490 |
| split75 | 1186.201 | 3.302 | 5.778 | 5834.154 | 5751.008 | 85.271 |
| latency_t1 | 1190.073 | 3.291 | 5.831 | 5834.539 | 5755.091 | 85.610 |
| extra_t1 | 1187.666 | 3.297 | 5.798 | 5834.421 | 5754.145 | 85.423 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1238.897 | 1116.797 | 122.100 |
| original / Native 3 | 1813.830 | 628.816 | 1185.015 |
| original / Nginx | 590.428 | 465.872 | 124.556 |
| original / Jaeger | 359.411 | 338.670 | 20.741 |
| original / Other | 1944.419 | 1048.197 | 896.222 |
| split75 / MongoDB 3 | 1133.608 | 1009.841 | 123.767 |
| split75 / Native 3 | 1819.006 | 633.932 | 1185.074 |
| split75 / Nginx | 571.286 | 445.609 | 125.678 |
| split75 / Jaeger | 357.563 | 336.051 | 21.512 |
| split75 / Other | 1952.690 | 1056.262 | 896.428 |
| latency_t1 / MongoDB 3 | 1134.830 | 1009.825 | 125.005 |
| latency_t1 / Native 3 | 1814.847 | 630.523 | 1184.323 |
| latency_t1 / Nginx | 573.038 | 446.799 | 126.239 |
| latency_t1 / Jaeger | 362.004 | 340.394 | 21.610 |
| latency_t1 / Other | 1949.820 | 1055.453 | 894.368 |
| extra_t1 / MongoDB 3 | 1135.582 | 1011.929 | 123.653 |
| extra_t1 / Native 3 | 1815.540 | 633.018 | 1182.522 |
| extra_t1 / Nginx | 574.284 | 448.498 | 125.787 |
| extra_t1 / Jaeger | 358.063 | 337.056 | 21.007 |
| extra_t1 / Other | 1950.952 | 1056.468 | 894.484 |

split75 Native-3 plus Mongo-3 user time: 28.18% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
