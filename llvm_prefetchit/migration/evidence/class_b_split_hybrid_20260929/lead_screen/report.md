# Residual targets and earlier placement: fresh full Media C4

Fresh full Media compose-review C4 including MovieId. 8 workload CPUs, 50s warmup, 60s clean ROI; all PMU follows. Four balanced blocks; no performance-based exclusions or retries. Compare within this campaign only.

residual_t1 replaces target displacements using first-half residual observations, with fixed code addresses, per-site hint counts and exact NOP. It changes target coverage rather than layout or total hint emission. lead512 selects >=512 accumulated retired LBR cycles under split75 site/hint budgets; different paths/coverage/emission may confound timing, so its own NOP is included. Neither measures instruction-fetch issue lead directly.

| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| split75 | 1178.75 | 3.3225 | 5.7974 | 5842.80 | 84.97% |
| residual_t1 | 1201.15 | 3.2594 | 5.8762 | 5827.36 | 86.20% |
| lead512_nop | 1156.09 | 3.3897 | 5.8973 | 6010.53 | 85.63% |
| lead512 | 1180.48 | 3.3175 | 5.7913 | 5848.65 | 85.11% |

| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |
|---|---:|---:|---:|---:|
| residual_t1 / split75 | 1.01893x [0.99306, 1.04547] | +1.905% [-0.708, +4.451] | -1.354% [-3.130, +0.392] | +0.264% [-0.219, +0.745] |
| lead512_nop / split75 | 0.98066x [0.95471, 1.00732] | -2.009% [-4.846, +0.751] | -1.716% [-3.870, +0.393] | -2.867% [-4.271, -1.482] |
| lead512 / split75 | 1.00147x [0.99618, 1.00678] | +0.149% [-0.423, +0.719] | +0.107% [-0.933, +1.136] | -0.100% [-0.217, +0.017] |
| lead512 / lead512_nop | 1.02121x [0.99900, 1.04392] | +2.116% [-0.075, +4.260] | +1.792% [+0.714, +2.858] | +2.690% [+1.373, +3.989] |
| lead512 / residual_t1 | 0.98286x [0.95747, 1.00892] | -1.790% [-4.540, +0.887] | +1.441% [+0.043, +2.820] | -0.366% [-0.793, +0.060] |

| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |
|---|---:|---:|---:|
| residual_t1 / split75 | +3.501% [+2.248, +4.738] | -0.333% [-0.963, +0.292] | +0.311% [-0.819, +1.429] |
| lead512_nop / split75 | -174.609% [-177.819, -171.437] | -13.676% [-13.717, -13.636] | -39.518% [-40.111, -38.928] |
| lead512 / split75 | -19.734% [-21.638, -17.860] | -0.989% [-1.873, -0.114] | -2.133% [-3.408, -0.874] |
| lead512 / lead512_nop | +56.398% [+55.310, +57.460] | +11.160% [+10.378, +11.936] | +26.796% [+25.854, +27.726] |
| lead512 / residual_t1 | -24.078% [-26.339, -21.858] | -0.654% [-1.514, +0.199] | -2.452% [-3.297, -1.613] |

| Arm | Mongo3 retired L1I/request | DSB-to-MITE penalty cycles/request | I-cache stall cycles/request |
|---|---:|---:|---:|
| split75 | 16,011.82 | 47,811.16 | 459,861.81 |
| residual_t1 | 16,038.52 | 48,120.85 | 458,271.19 |
| lead512_nop | 15,983.57 | 48,101.19 | 642,084.02 |
| lead512 | 15,854.30 | 47,939.65 | 470,194.34 |

L1I and L2 retired-event populations are collected in separate windows. Their ratio is descriptive; subtracting them is not an exclusive critical-path attribution. DSB-switch penalty is not a BTB occupancy measurement.

Individual paired-log t95 intervals, no multiplicity correction. Two-block screens are exploratory. E2E precedes PMU; no E2E inference from code misses. LATE_SWPF zero-control values are retained as absolute counts, not undefined percentage ratios. Service-summed PMU counts combine separate request-normalized windows.

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Raw metric fractions retain up to 2% closure error from 8-bit metric accounting; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.
