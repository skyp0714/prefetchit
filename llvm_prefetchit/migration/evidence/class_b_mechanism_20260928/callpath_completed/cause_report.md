# Call-path implementation: request performance and remaining misses

Full paired E2E results: [screen report](screen_report.md).

| Policy / original | Throughput speedup | Whole-stack CPU reduction | p99 reduction |
|---|---:|---:|---:|
| call256_nop | 0.99881× [0.98934, 1.00836] | -0.065% | -0.427% |
| call256 | 1.00770× [0.67998, 1.49337] | +0.773% | +0.337% |

| Arm / MongoDB service | User CPU µs/request | Retired L2/request | I-cache stall cycles/request | T1/T2 instructions/request | Unknown-branch cycles (%) | DSB/(DSB+MITE) (%) |
|---|---:|---:|---:|---:|---:|---:|
| original / user-review-mongodb | 484.657 | 2369.183 | 265665.185 | 0.000 | 29.633 | 65.956 |
| original / movie-review-mongodb | 482.579 | 2346.010 | 264161.651 | 0.000 | 29.286 | 66.814 |
| original / review-storage-mongodb | 151.610 | 819.461 | 90606.407 | 0.000 | 38.955 | 20.864 |
| call256_nop / user-review-mongodb | 489.369 | 2400.584 | 270067.726 | 0.000 | 30.269 | 65.712 |
| call256_nop / movie-review-mongodb | 487.789 | 2375.371 | 267140.917 | 0.000 | 29.999 | 66.418 |
| call256_nop / review-storage-mongodb | 153.319 | 839.864 | 91164.964 | 0.000 | 39.646 | 20.628 |
| call256 / user-review-mongodb | 456.172 | 1559.641 | 232833.776 | 8395.248 | 26.606 | 66.001 |
| call256 / movie-review-mongodb | 457.135 | 1556.625 | 234230.313 | 8451.898 | 26.146 | 66.722 |
| call256 / review-storage-mongodb | 142.268 | 585.477 | 80675.279 | 2253.932 | 36.665 | 20.279 |

| Residual service | Main-image samples | On selected target line | Matching hint observed | Matching hint with retired age ≥512 |
|---|---:|---:|---:|---:|
| user-review-mongodb | 55489 | 11571 | 10280 | 4928 |
| movie-review-mongodb | 54296 | 11327 | 10167 | 4723 |
| review-storage-mongodb | 20382 | 4220 | 2950 | 1463 |

Arm counters are averages of separate service/window request-normalized observations. The residual capture and heldout baseline use different diagnostic seeds/windows, and their request normalization brackets perf startup/teardown. No E2E claim or exclusive cause partition follows from these counters. An observed retired hint is not proof of early issue, accepted request, fill or residency. Finite LBR history changes with added jumps; absence is not proof that no hint executed. T1_T2_EXECUTED is speculative and includes original software prefetches; it is not a count of accepted fills.
