# Clean-ROI CPU accounting and request performance

| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |
|---|---:|---:|---:|---:|---:|---:|
| original | 1168.698 | 3.352 | 5.882 | 5933.217 | 5845.111 | 85.386 |
| cost75_split | 1174.021 | 3.337 | 5.875 | 5861.839 | 5782.801 | 84.864 |
| hybrid_nop | 1128.811 | 3.473 | 5.958 | 6122.221 | 6042.345 | 85.251 |
| early_t1 | 1161.249 | 3.374 | 5.910 | 5984.781 | 5900.272 | 85.645 |
| hybrid_it0 | 1153.493 | 3.397 | 5.907 | 5994.387 | 5916.831 | 85.312 |
| hybrid_sparse_nop | 1147.888 | 3.413 | 5.890 | 6005.445 | 5925.563 | 85.024 |
| hybrid_sparse | 1171.376 | 3.344 | 5.792 | 5885.669 | 5811.448 | 85.092 |
| hybrid_sparse_mixed | 1176.333 | 3.330 | 5.861 | 5887.589 | 5806.256 | 85.372 |

| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |
|---|---:|---:|---:|
| original / MongoDB 3 | 1242.270 | 1120.677 | 121.593 |
| original / Native 3 | 1814.001 | 630.616 | 1183.384 |
| original / Nginx | 575.557 | 450.112 | 125.445 |
| original / Jaeger | 357.115 | 336.144 | 20.972 |
| original / Other | 1944.274 | 1047.289 | 896.984 |
| cost75_split / MongoDB 3 | 1159.023 | 1034.197 | 124.826 |
| cost75_split / Native 3 | 1818.944 | 635.947 | 1182.997 |
| cost75_split / Nginx | 570.813 | 445.996 | 124.817 |
| cost75_split / Jaeger | 356.938 | 335.745 | 21.194 |
| cost75_split / Other | 1956.122 | 1059.029 | 897.093 |
| hybrid_nop / MongoDB 3 | 1383.718 | 1254.995 | 128.723 |
| hybrid_nop / Native 3 | 1821.665 | 632.536 | 1189.129 |
| hybrid_nop / Nginx | 597.765 | 474.415 | 123.350 |
| hybrid_nop / Jaeger | 356.290 | 335.069 | 21.221 |
| hybrid_nop / Other | 1962.783 | 1057.460 | 905.323 |
| early_t1 / MongoDB 3 | 1266.068 | 1137.564 | 128.504 |
| early_t1 / Native 3 | 1824.866 | 636.003 | 1188.863 |
| early_t1 / Nginx | 572.738 | 445.734 | 127.005 |
| early_t1 / Jaeger | 358.747 | 337.723 | 21.024 |
| early_t1 / Other | 1962.362 | 1058.554 | 903.808 |
| hybrid_it0 / MongoDB 3 | 1270.856 | 1139.691 | 131.165 |
| hybrid_it0 / Native 3 | 1828.217 | 636.852 | 1191.365 |
| hybrid_it0 / Nginx | 568.918 | 442.359 | 126.559 |
| hybrid_it0 / Jaeger | 358.245 | 337.081 | 21.164 |
| hybrid_it0 / Other | 1968.151 | 1060.746 | 907.405 |
| hybrid_sparse_nop / MongoDB 3 | 1289.201 | 1162.027 | 127.174 |
| hybrid_sparse_nop / Native 3 | 1824.736 | 635.033 | 1189.704 |
| hybrid_sparse_nop / Nginx | 572.641 | 447.997 | 124.644 |
| hybrid_sparse_nop / Jaeger | 357.367 | 335.971 | 21.397 |
| hybrid_sparse_nop / Other | 1961.499 | 1058.670 | 902.829 |
| hybrid_sparse / MongoDB 3 | 1173.232 | 1047.572 | 125.659 |
| hybrid_sparse / Native 3 | 1823.961 | 636.259 | 1187.702 |
| hybrid_sparse / Nginx | 569.413 | 444.940 | 124.473 |
| hybrid_sparse / Jaeger | 360.155 | 337.574 | 22.581 |
| hybrid_sparse / Other | 1958.908 | 1058.178 | 900.730 |
| hybrid_sparse_mixed / MongoDB 3 | 1169.378 | 1044.940 | 124.437 |
| hybrid_sparse_mixed / Native 3 | 1825.932 | 635.163 | 1190.769 |
| hybrid_sparse_mixed / Nginx | 576.719 | 450.328 | 126.391 |
| hybrid_sparse_mixed / Jaeger | 358.510 | 337.782 | 20.728 |
| hybrid_sparse_mixed / Other | 1957.051 | 1058.448 | 898.603 |

Original Native-3 plus Mongo-3 user time: 29.52% of whole-stack CPU time. This includes all user work, not just frontend stalls.

Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. Tables average per-trial statistics; p99 is not pooled across requests.
