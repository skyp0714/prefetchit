# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1167.105 | 3.357 | 5.881 | 5933.535 | 5857.592 | 85.452 |
| fixed_split | 1187.449 | 3.298 | 5.822 | 5860.600 | 5782.416 | 85.826 |
| split75 | 1189.550 | 3.293 | 5.785 | 5831.227 | 5754.016 | 85.552 |
| split75_nop | 1161.298 | 3.374 | 5.895 | 5969.216 | 5888.629 | 85.477 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1240.942 | 1117.598 | 123.344 |
| original / Native 3 | 1812.835 | 629.376 | 1183.459 |
| original / Nginx | 574.414 | 448.597 | 125.817 |
| original / Jaeger | 358.771 | 337.693 | 21.078 |
| original / Other | 1946.573 | 1049.424 | 897.149 |
| fixed_split / MongoDB 3 | 1158.744 | 1033.705 | 125.039 |
| fixed_split / Native 3 | 1819.825 | 632.926 | 1186.899 |
| fixed_split / Nginx | 573.249 | 446.424 | 126.824 |
| fixed_split / Jaeger | 358.608 | 337.166 | 21.443 |
| fixed_split / Other | 1950.174 | 1053.212 | 896.962 |
| split75 / MongoDB 3 | 1132.159 | 1006.697 | 125.461 |
| split75 / Native 3 | 1817.150 | 632.897 | 1184.253 |
| split75 / Nginx | 571.792 | 444.690 | 127.101 |
| split75 / Jaeger | 359.631 | 338.774 | 20.857 |
| split75 / Other | 1950.495 | 1056.096 | 894.399 |
| split75_nop / MongoDB 3 | 1280.938 | 1155.677 | 125.261 |
| split75_nop / Native 3 | 1815.660 | 629.545 | 1186.115 |
| split75_nop / Nginx | 566.870 | 440.829 | 126.041 |
| split75_nop / Jaeger | 356.527 | 335.782 | 20.745 |
| split75_nop / Other | 1949.221 | 1053.511 | 895.710 |

Original Native-3 plus Mongo-3 user time: 29.44% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
