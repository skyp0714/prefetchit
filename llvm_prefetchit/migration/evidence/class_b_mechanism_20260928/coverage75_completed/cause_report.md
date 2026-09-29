# Call-path implementation: request performance and remaining misses

Full paired E2E results: [screen report](screen_report.md).

| Policy / original | Throughput speedup | Whole-stack CPU reduction | p99 reduction |
|---|---:|---:|---:|
| wide75_nop | 0.97596× [0.95875, 0.99347] | -0.972% | -0.405% |
| wide75 | 1.01023× [0.96581, 1.05670] | +1.892% | +0.323% |
| cost75_nop | 0.97591× [0.94617, 1.00658] | -1.199% | -0.420% |
| cost75 | 1.00082× [0.99074, 1.01102] | +1.351% | +0.690% |

| Arm / MongoDB service | User CPU µs/request | Retired L2/request | I-cache stall cycles/request | T1/T2 instructions/request | Unknown-branch cycles (%) | DSB/(DSB+MITE) (%) |
|---|---:|---:|---:|---:|---:|---:|
| original / user-review-mongodb | 483.211 | 2360.519 | 264604.076 | 0.000 | 29.526 | 66.082 |
| original / movie-review-mongodb | 481.845 | 2335.841 | 262707.727 | 0.000 | 29.251 | 66.919 |
| original / review-storage-mongodb | 150.806 | 817.012 | 89699.713 | 0.000 | 38.601 | 21.045 |
| call256 / user-review-mongodb | 455.780 | 1564.344 | 233497.969 | 8414.213 | 26.412 | 65.973 |
| call256 / movie-review-mongodb | 456.457 | 1544.583 | 233547.263 | 8431.845 | 26.104 | 66.800 |
| call256 / review-storage-mongodb | 142.065 | 579.679 | 79685.602 | 2266.162 | 36.512 | 20.691 |
| wide75_nop / user-review-mongodb | 495.864 | 2396.107 | 273322.088 | 0.000 | 31.272 | 65.330 |
| wide75_nop / movie-review-mongodb | 494.139 | 2392.812 | 273891.893 | 0.000 | 30.947 | 66.082 |
| wide75_nop / review-storage-mongodb | 155.954 | 837.604 | 93919.170 | 0.000 | 40.620 | 20.294 |
| wide75 / user-review-mongodb | 446.590 | 1145.032 | 218412.211 | 11830.120 | 25.451 | 65.797 |
| wide75 / movie-review-mongodb | 445.569 | 1115.272 | 216161.589 | 11824.918 | 25.117 | 66.576 |
| wide75 / review-storage-mongodb | 139.780 | 490.058 | 77057.228 | 3021.074 | 35.610 | 20.247 |
| cost75_nop / user-review-mongodb | 496.091 | 2480.839 | 278237.627 | 0.000 | 31.367 | 65.539 |
| cost75_nop / movie-review-mongodb | 495.361 | 2467.117 | 277186.256 | 0.000 | 31.004 | 66.379 |
| cost75_nop / review-storage-mongodb | 156.969 | 867.594 | 95345.873 | 0.000 | 40.645 | 20.541 |
| cost75 / user-review-mongodb | 447.022 | 1163.389 | 219031.318 | 2965.220 | 25.694 | 65.847 |
| cost75 / movie-review-mongodb | 446.345 | 1159.354 | 219569.059 | 2954.063 | 25.447 | 66.765 |
| cost75 / review-storage-mongodb | 139.038 | 494.479 | 77316.687 | 875.337 | 35.183 | 20.549 |

| Residual service | Main-image samples | On selected target line | Matching hint observed | Matching hint with retired age ≥512 |
|---|---:|---:|---:|---:|
| user-review-mongodb | 40168 | 16110 | 14094 | 5523 |
| movie-review-mongodb | 39619 | 15967 | 14085 | 5688 |
| review-storage-mongodb | 17170 | 6979 | 4878 | 2382 |

Arm counters are averages of separate service/window request-normalized observations. The residual capture and heldout baseline use different diagnostic seeds/windows, and their request normalization brackets perf startup/teardown. No E2E claim or exclusive cause partition follows from these counters. An observed retired hint is not proof of early issue, accepted request, fill or residency. Finite LBR history changes with added jumps; absence is not proof that no hint executed. T1_T2_EXECUTED is speculative and includes original software prefetches; it is not a count of accepted fills.
