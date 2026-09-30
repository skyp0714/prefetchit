# Split75 plus early IT0: fresh full Media C4

4 exploratory paired blocks. Each arm uses a fresh full stack, 50 s warmup and 60 s clean ROI. Individual paired-log t95 intervals; no multiplicity correction. Prespecified trial orders are retained in screen/protocol.json.

| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| original | 1171.48 | 3.3440 | 5.8637 | 5921.61 | 85.50% |
| split75 | 1187.17 | 3.2988 | 5.8202 | 5838.24 | 85.46% |
| early_t1 | 1190.93 | 3.2882 | 5.8306 | 5858.11 | 86.04% |
| early_it0 | 1185.37 | 3.3038 | 5.7957 | 5854.97 | 85.56% |

| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |
|---|---:|---:|---:|---:|
| split75 / original | 1.01340x [0.99623, 1.03087] | +1.351% [-0.393, +3.065] | +0.742% [-0.004, +1.482] | +1.408% [+1.213, +1.603] |
| early_t1 / original | 1.01657x [0.99342, 1.04025] | +1.673% [-0.671, +3.963] | +0.565% [-0.538, +1.656] | +1.072% [+0.786, +1.358] |
| early_t1 / split75 | 1.00313x [0.97608, 1.03092] | +0.326% [-2.510, +3.084] | -0.178% [-0.675, +0.316] | -0.341% [-0.736, +0.053] |
| early_it0 / original | 1.01186x [0.99835, 1.02556] | +1.203% [-0.166, +2.553] | +1.163% [-1.284, +3.551] | +1.125% [+0.894, +1.356] |
| early_it0 / split75 | 0.99848x [0.97553, 1.02198] | -0.151% [-2.574, +2.216] | +0.424% [-1.996, +2.787] | -0.287% [-0.479, -0.094] |
| early_it0 / early_t1 | 0.99537x [0.98347, 1.00741] | -0.479% [-1.728, +0.755] | +0.602% [-1.986, +3.123] | +0.054% [-0.441, +0.546] |

| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |
|---|---:|---:|---:|
| split75 / original | +62.268% [+61.370, +63.144] | +9.134% [+8.367, +9.894] | +24.757% [+23.783, +25.718] |
| early_t1 / original | +61.925% [+61.209, +62.629] | +7.067% [+6.212, +7.914] | +22.570% [+21.916, +23.218] |
| early_t1 / split75 | -0.908% [-2.098, +0.269] | -2.275% [-2.558, -1.993] | -2.907% [-4.188, -1.642] |
| early_it0 / original | +61.962% [+61.707, +62.216] | +7.692% [+7.200, +8.181] | +23.495% [+23.192, +23.797] |
| early_it0 / split75 | -0.810% [-3.063, +1.394] | -1.586% [-2.101, -1.074] | -1.677% [-3.092, -0.281] |
| early_it0 / early_t1 | +0.097% [-1.825, +1.982] | +0.673% [+0.215, +1.129] | +1.195% [-0.010, +2.386] |

Cache/prefetch PMU windows follow the clean ROI and cover three MongoDBs; separate top-down/memory windows additionally cover pool user and kernel execution; each window has its own request denominator. CPU and latency still cover the whole stack, including MovieId. No inference of maximum throughput, prefetch accuracy, or queue occupancy. Existing campaigns are not pooled.
