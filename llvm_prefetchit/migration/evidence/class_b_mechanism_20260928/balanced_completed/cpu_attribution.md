# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1170.775 | 3.347 | 5.886 | 5921.412 | 5837.509 | 85.428 |
| call256 | 1177.811 | 3.325 | 5.790 | 5869.038 | 5789.328 | 85.234 |
| cost75_nop | 1176.141 | 3.330 | 5.863 | 5952.088 | 5868.277 | 86.273 |
| cost75 | 1185.030 | 3.305 | 5.815 | 5849.309 | 5769.236 | 85.456 |
| cost75_split | 1176.266 | 3.330 | 5.839 | 5861.915 | 5782.744 | 85.025 |
| cost75_it0 | 1160.733 | 3.375 | 5.822 | 5947.443 | 5872.484 | 85.205 |
| combined_nop | 1154.558 | 3.394 | 5.886 | 5974.040 | 5896.711 | 85.101 |
| combined | 1181.000 | 3.316 | 5.769 | 5830.895 | 5753.845 | 84.941 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1238.803 | 1116.651 | 122.153 |
| original / Native 3 | 1813.437 | 631.165 | 1182.272 |
| original / Nginx | 569.958 | 443.181 | 126.777 |
| original / Jaeger | 357.571 | 337.630 | 19.941 |
| original / Other | 1941.643 | 1049.754 | 891.889 |
| call256 / MongoDB 3 | 1176.434 | 1053.761 | 122.673 |
| call256 / Native 3 | 1818.135 | 635.364 | 1182.771 |
| call256 / Nginx | 566.293 | 440.554 | 125.739 |
| call256 / Jaeger | 359.175 | 337.531 | 21.644 |
| call256 / Other | 1949.002 | 1053.782 | 895.220 |
| cost75_nop / MongoDB 3 | 1274.571 | 1149.530 | 125.041 |
| cost75_nop / Native 3 | 1811.311 | 627.938 | 1183.373 |
| cost75_nop / Nginx | 571.797 | 443.553 | 128.244 |
| cost75_nop / Jaeger | 351.299 | 330.885 | 20.413 |
| cost75_nop / Other | 1943.111 | 1047.758 | 895.353 |
| cost75 / MongoDB 3 | 1155.841 | 1030.707 | 125.134 |
| cost75 / Native 3 | 1815.004 | 631.556 | 1183.448 |
| cost75 / Nginx | 568.993 | 443.683 | 125.311 |
| cost75 / Jaeger | 360.815 | 339.632 | 21.182 |
| cost75 / Other | 1948.656 | 1052.802 | 895.854 |
| cost75_split / MongoDB 3 | 1156.187 | 1032.403 | 123.784 |
| cost75_split / Native 3 | 1821.456 | 636.686 | 1184.770 |
| cost75_split / Nginx | 571.224 | 446.316 | 124.908 |
| cost75_split / Jaeger | 357.120 | 335.784 | 21.336 |
| cost75_split / Other | 1955.928 | 1056.017 | 899.911 |
| cost75_it0 / MongoDB 3 | 1250.898 | 1125.972 | 124.926 |
| cost75_it0 / Native 3 | 1816.245 | 632.832 | 1183.413 |
| cost75_it0 / Nginx | 571.942 | 447.005 | 124.936 |
| cost75_it0 / Jaeger | 360.093 | 338.788 | 21.305 |
| cost75_it0 / Other | 1948.266 | 1050.335 | 897.931 |
| combined_nop / MongoDB 3 | 1272.914 | 1148.317 | 124.597 |
| combined_nop / Native 3 | 1821.721 | 636.145 | 1185.575 |
| combined_nop / Nginx | 568.249 | 443.843 | 124.406 |
| combined_nop / Jaeger | 358.332 | 337.026 | 21.306 |
| combined_nop / Other | 1952.824 | 1052.705 | 900.119 |
| combined / MongoDB 3 | 1158.317 | 1033.902 | 124.416 |
| combined / Native 3 | 1790.555 | 607.374 | 1183.181 |
| combined / Nginx | 566.267 | 440.996 | 125.271 |
| combined / Jaeger | 361.743 | 340.428 | 21.314 |
| combined / Other | 1954.013 | 1055.946 | 898.067 |

Original Native-3 plus Mongo-3 user time: 29.52% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
