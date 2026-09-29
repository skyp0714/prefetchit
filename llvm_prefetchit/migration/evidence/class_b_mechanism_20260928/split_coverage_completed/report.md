# Continuation-aware placement: fresh full Media C4

4 exploratory paired blocks. Each arm uses a fresh full stack, 50 s warmup and 60 s clean ROI. Individual paired-log t95 intervals; no multiplicity correction. Prespecified trial orders are retained in screen/protocol.json.

| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| original | 1167.11 | 3.3566 | 5.8813 | 5933.53 | 85.45% |
| fixed_split | 1187.45 | 3.2984 | 5.8219 | 5860.60 | 85.83% |
| split75_nop | 1161.30 | 3.3741 | 5.8950 | 5969.22 | 85.48% |
| split75 | 1189.55 | 3.2927 | 5.7853 | 5831.23 | 85.55% |

| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |
|---|---:|---:|---:|---:|
| fixed_split / original | 1.01743x [1.00300, 1.03208] | +1.735% [+0.259, +3.189] | +1.011% [-0.303, +2.307] | +1.229% [+0.889, +1.568] |
| split75_nop / original | 0.99501x [0.95382, 1.03798] | -0.520% [-4.958, +3.730] | -0.227% [-2.193, +1.701] | -0.601% [-1.719, +0.504] |
| split75 / original | 1.01917x [0.97275, 1.06781] | +1.908% [-2.879, +6.473] | +1.632% [+0.307, +2.939] | +1.725% [+0.414, +3.019] |
| split75 / split75_nop | 1.02428x [1.01678, 1.03184] | +2.416% [+1.701, +3.126] | +1.855% [-0.071, +3.744] | +2.312% [+1.821, +2.801] |
| split75 / fixed_split | 1.00171x [0.96599, 1.03875] | +0.176% [-3.580, +3.796] | +0.627% [+0.323, +0.931] | +0.502% [-0.480, +1.475] |

| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |
|---|---:|---:|---:|
| fixed_split / original | +49.499% [+49.153, +49.843] | +7.362% [+6.193, +8.516] | +17.169% [+16.800, +17.538] |
| split75_nop / original | -4.913% [-5.984, -3.853] | -3.385% [-3.912, -2.859] | -5.944% [-6.625, -5.267] |
| split75 / original | +62.866% [+62.307, +63.417] | +9.391% [+8.994, +9.786] | +25.453% [+25.122, +25.783] |
| split75 / split75_nop | +64.605% [+64.288, +64.919] | +12.357% [+11.828, +12.883] | +29.635% [+29.331, +29.938] |
| split75 / fixed_split | +26.468% [+25.640, +27.287] | +2.190% [+1.087, +3.281] | +10.001% [+9.401, +10.596] |

PMU windows follow the clean ROI and cover three MongoDBs only; each window has its own request denominator. CPU and latency still cover the whole stack, including MovieId. No inference of maximum throughput, prefetch accuracy, or queue occupancy. Existing campaigns are not pooled.
