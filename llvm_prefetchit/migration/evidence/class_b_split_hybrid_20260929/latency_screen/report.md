# Long frontend-stall targets with fixed supplemental slots: fresh full Media C4

Four balanced blocks: fresh full Media compose-review C4 including MovieId, eight workload CPUs, 50s warmup, 60s clean ROI. 28 separate post-ROI PMU windows include long frontend stalls. No performance-based retry/exclusion; no pooling with earlier campaigns.

Retarget only existing supplemental T1 displacements using long frontend-stall samples, preserving code size, call sites, hint count and every original split75 T1 hint. latency_t1 and extra_t1 have identical layout/opcodes outside the changed displacements and restore to the same recorded incremental-NOP hash. Directly compare the full policy to original and split75; isolate target selection versus extra_t1. Do not infer E2E benefit by multiplying previous ratios.

| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| original | 1166.18 | 3.3598 | 5.8813 | 5946.99 | 85.49% |
| split75 | 1186.20 | 3.3016 | 5.7784 | 5834.15 | 85.27% |
| extra_t1 | 1187.67 | 3.2972 | 5.7980 | 5834.42 | 85.42% |
| latency_t1 | 1190.07 | 3.2906 | 5.8308 | 5834.54 | 85.61% |

| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |
|---|---:|---:|---:|---:|
| split75 / original | 1.01720x [0.99845, 1.03630] | +1.729% [-0.172, +3.594] | +1.749% [+0.631, +2.855] | +1.895% [+0.595, +3.179] |
| extra_t1 / original | 1.01845x [0.97818, 1.06039] | +1.858% [-2.258, +5.809] | +1.417% [+0.566, +2.261] | +1.890% [+0.337, +3.420] |
| extra_t1 / split75 | 1.00123x [0.97126, 1.03213] | +0.132% [-2.975, +3.145] | -0.338% [-1.837, +1.140] | -0.005% [-0.618, +0.605] |
| latency_t1 / original | 1.02049x [0.98795, 1.05411] | +2.058% [-1.233, +5.241] | +0.859% [-0.089, +1.798] | +1.889% [+0.902, +2.865] |
| latency_t1 / split75 | 1.00324x [0.97110, 1.03645] | +0.335% [-3.011, +3.572] | -0.906% [-1.349, -0.465] | -0.007% [-0.584, +0.567] |
| latency_t1 / extra_t1 | 1.00200x [0.96434, 1.04114] | +0.203% [-3.773, +4.026] | -0.567% [-1.878, +0.728] | -0.002% [-0.682, +0.674] |

| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |
|---|---:|---:|---:|
| split75 / original | +62.385% [+62.030, +62.737] | +9.136% [+8.415, +9.851] | +25.020% [+24.093, +25.936] |
| extra_t1 / original | +61.972% [+61.230, +62.700] | +8.963% [+7.995, +9.921] | +24.002% [+22.966, +25.024] |
| extra_t1 / split75 | -1.098% [-3.193, +0.955] | -0.190% [-0.808, +0.424] | -1.358% [-2.305, -0.419] |
| latency_t1 / original | +62.301% [+61.663, +62.929] | +9.234% [+8.441, +10.020] | +24.674% [+24.326, +25.022] |
| latency_t1 / split75 | -0.222% [-2.258, +1.773] | +0.108% [-0.714, +0.923] | -0.461% [-1.558, +0.623] |
| latency_t1 / extra_t1 | +0.866% [-0.402, +2.119] | +0.298% [-1.075, +1.651] | +0.884% [-0.078, +1.837] |

| Arm | Mongo3 retired L1I/request | DSB-to-MITE penalty cycles/request | I-cache stall cycles/request |
|---|---:|---:|---:|
| original | 14,797.27 | 49,761.15 | 614,708.64 |
| split75 | 16,029.05 | 48,012.23 | 461,826.72 |
| extra_t1 | 15,979.21 | 47,640.19 | 466,663.11 |
| latency_t1 | 16,033.16 | 48,244.82 | 463,262.10 |

L1I and L2 retired-event populations are collected in separate windows. Their ratio is descriptive; subtracting them is not an exclusive critical-path attribution. DSB-switch penalty is not a BTB occupancy measurement.

Individual paired-log t95 intervals, no multiplicity correction. Two-block screens are exploratory. E2E precedes PMU; no E2E inference from code misses. LATE_SWPF zero-control values are retained as absolute counts, not undefined percentage ratios. Service-summed PMU counts combine separate request-normalized windows.

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Raw metric fractions retain up to 2% closure error from 8-bit metric accounting; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.
