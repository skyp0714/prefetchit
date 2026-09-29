# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1180.792 | 3.317 | 5.829 | 5901.788 | 5824.146 | 85.963 |
| call256 | 1198.212 | 3.268 | 5.807 | 5825.894 | 5738.864 | 85.949 |
| wide75_nop | 1152.366 | 3.401 | 5.853 | 5959.254 | 5873.764 | 84.605 |
| wide75 | 1192.913 | 3.283 | 5.811 | 5790.185 | 5701.200 | 85.019 |
| cost75_nop | 1152.317 | 3.401 | 5.854 | 5972.773 | 5888.594 | 84.812 |
| cost75 | 1181.720 | 3.314 | 5.789 | 5822.067 | 5744.254 | 84.850 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1238.102 | 1116.009 | 122.093 |
| original / Native 3 | 1807.102 | 629.222 | 1177.880 |
| original / Nginx | 564.703 | 438.435 | 126.268 |
| original / Jaeger | 353.897 | 333.674 | 20.223 |
| original / Other | 1937.984 | 1047.005 | 890.979 |
| call256 / MongoDB 3 | 1177.539 | 1054.440 | 123.099 |
| call256 / Native 3 | 1809.413 | 627.756 | 1181.657 |
| call256 / Nginx | 540.764 | 417.410 | 123.354 |
| call256 / Jaeger | 355.833 | 334.931 | 20.902 |
| call256 / Other | 1942.346 | 1048.581 | 893.764 |
| wide75_nop / MongoDB 3 | 1272.268 | 1146.069 | 126.199 |
| wide75_nop / Native 3 | 1817.752 | 632.593 | 1185.159 |
| wide75_nop / Nginx | 555.604 | 435.011 | 120.593 |
| wide75_nop / Jaeger | 359.024 | 337.366 | 21.658 |
| wide75_nop / Other | 1954.606 | 1055.710 | 898.897 |
| wide75 / MongoDB 3 | 1157.359 | 1032.069 | 125.290 |
| wide75 / Native 3 | 1812.380 | 634.160 | 1178.219 |
| wide75 / Nginx | 516.570 | 398.241 | 118.328 |
| wide75 / Jaeger | 354.694 | 333.538 | 21.156 |
| wide75 / Other | 1949.182 | 1054.576 | 894.606 |
| cost75_nop / MongoDB 3 | 1274.498 | 1148.599 | 125.899 |
| cost75_nop / Native 3 | 1819.513 | 634.326 | 1185.187 |
| cost75_nop / Nginx | 567.025 | 445.561 | 121.465 |
| cost75_nop / Jaeger | 356.308 | 334.775 | 21.533 |
| cost75_nop / Other | 1955.428 | 1053.752 | 901.676 |
| cost75 / MongoDB 3 | 1156.612 | 1032.548 | 124.064 |
| cost75 / Native 3 | 1817.275 | 635.485 | 1181.790 |
| cost75 / Nginx | 535.857 | 414.781 | 121.076 |
| cost75 / Jaeger | 359.736 | 337.752 | 21.984 |
| cost75 / Other | 1952.588 | 1055.551 | 897.037 |

Original Native-3 plus Mongo-3 user time: 29.57% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
