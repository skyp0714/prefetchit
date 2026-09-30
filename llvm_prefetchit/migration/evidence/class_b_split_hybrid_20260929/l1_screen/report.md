# L1I-guided supplement with old T1 retained: fresh full Media C4

Four balanced blocks, fresh full Media compose-review C4 including MovieId. Eight workload CPUs, 50s warmup and 60s clean ROI. Same 25 post-ROI PMU windows; no performance-based retries/exclusions. Do not pool with previous campaigns.

Add at most one L1I-trained hint at each selected existing stub, retaining all original split75 T1 hints and original call sites. extra_it0/extra_t1/extra_nop have identical layout and targets; only new-slot bytes differ. Split75 versus incremental NOP measures layout/instruction overhead. No timestamp/epoch gate. The single IT0 at each selected stub is also the only added IT0 in its static 32B region; fetch-queue occupancy is not observed.

| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| split75 | 1191.93 | 3.2852 | 5.8236 | 5834.12 | 85.75% |
| extra_nop | 1177.46 | 3.3264 | 5.8448 | 5866.95 | 85.19% |
| extra_t1 | 1182.13 | 3.3138 | 5.7832 | 5874.17 | 85.60% |
| extra_it0 | 1178.00 | 3.3244 | 5.8128 | 5847.06 | 84.92% |

| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |
|---|---:|---:|---:|---:|
| extra_nop / split75 | 0.98788x [0.95064, 1.02657] | -1.254% [-5.324, +2.658] | -0.362% [-1.663, +0.923] | -0.560% [-2.310, +1.161] |
| extra_t1 / split75 | 0.99168x [0.94063, 1.04550] | -0.859% [-6.457, +4.444] | +0.696% [-0.379, +1.758] | -0.682% [-2.671, +1.269] |
| extra_t1 / extra_nop | 1.00385x [0.97742, 1.03099] | +0.390% [-2.344, +3.051] | +1.054% [-0.477, +2.561] | -0.121% [-1.697, +1.430] |
| extra_it0 / split75 | 0.98839x [0.96932, 1.00783] | -1.201% [-3.233, +0.792] | +0.185% [-0.807, +1.167] | -0.222% [-0.452, +0.007] |
| extra_it0 / extra_nop | 1.00052x [0.98030, 1.02115] | +0.053% [-2.074, +2.136] | +0.545% [-1.105, +2.167] | +0.336% [-1.319, +1.964] |
| extra_it0 / extra_t1 | 0.99668x [0.96131, 1.03336] | -0.339% [-4.111, +3.297] | -0.514% [-2.480, +1.414] | +0.457% [-1.560, +2.433] |

| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |
|---|---:|---:|---:|
| extra_nop / split75 | -0.707% [-2.142, +0.708] | -0.427% [-1.582, +0.714] | -1.030% [-1.528, -0.535] |
| extra_t1 / split75 | -0.902% [-2.569, +0.737] | -0.195% [-1.578, +1.168] | -1.223% [-1.522, -0.925] |
| extra_t1 / extra_nop | -0.194% [-0.559, +0.170] | +0.231% [-0.100, +0.561] | -0.191% [-0.966, +0.577] |
| extra_it0 / split75 | -2.508% [-3.826, -1.207] | +0.191% [-0.922, +1.292] | -1.359% [-2.151, -0.572] |
| extra_it0 / extra_nop | -1.788% [-3.161, -0.434] | +0.616% [+0.484, +0.747] | -0.325% [-1.557, +0.892] |
| extra_it0 / extra_t1 | -1.591% [-2.865, -0.333] | +0.386% [-0.020, +0.789] | -0.134% [-0.646, +0.377] |

| Arm | Mongo3 retired L1I/request | DSB-to-MITE penalty cycles/request | I-cache stall cycles/request |
|---|---:|---:|---:|
| split75 | 15,986.30 | 48,213.54 | 459,431.27 |
| extra_nop | 15,966.52 | 47,778.94 | 463,885.81 |
| extra_t1 | 15,972.70 | 47,613.07 | 464,868.72 |
| extra_it0 | 16,051.86 | 48,100.96 | 465,169.22 |

L1I and L2 retired-event populations are collected in separate windows. Their ratio is descriptive; subtracting them is not an exclusive critical-path attribution. DSB-switch penalty is not a BTB occupancy measurement.

Individual paired-log t95 intervals, no multiplicity correction. Two-block screens are exploratory. E2E precedes PMU; no E2E inference from code misses. LATE_SWPF zero-control values are retained as absolute counts, not undefined percentage ratios. Service-summed PMU counts combine separate request-normalized windows.

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Raw metric fractions retain up to 2% closure error from 8-bit metric accounting; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.
