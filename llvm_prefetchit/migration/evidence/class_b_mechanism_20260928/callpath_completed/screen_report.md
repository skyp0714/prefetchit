# Fresh-stack backend screen

6 valid fresh-stack trials. Control: `original`. Individual paired-log 95% t intervals; exploratory comparisons without multiplicity correction.

| Policy / control | Throughput speedup [95% CI] | Mean latency reduction | p99 reduction | Whole-stack CPU reduction |
|---|---:|---:|---:|---:|
| call256_nop / original | 0.99881× [0.98934, 1.00836] | -0.121% [-1.346, +1.089] | -0.427% [-9.706, +8.067] | -0.065% [-1.589, +1.435] |
| call256 / original | 1.00770× [0.67998, 1.49337] | +0.778% [-48.035, +33.495] | +0.337% [-7.450, +7.559] | +0.773% [-7.880, +8.732] |
| call256 / call256_nop | 1.00891× [0.67435, 1.50945] | +0.897% [-49.666, +34.378] | +0.760% [-0.552, +2.056] | +0.838% [-6.192, +7.403] |

| Policy / control | Native-3 retired L2 reduction | Review-Mongo-2 retired L2 reduction | Review-Mongo-2 code-read miss reduction | Review-Mongo-2 I-cache data-stall reduction |
|---|---:|---:|---:|---:|
| call256_nop / original | +0.076% [-12.340, +11.120] | -1.289% [-2.615, +0.021] | -1.556% [-3.744, +0.585] | -1.393% [-1.490, -1.297] |
| call256 / original | +1.058% [+0.221, +1.888] | +33.910% [+32.713, +35.086] | +4.840% [+2.723, +6.910] | +11.846% [+6.310, +17.054] |
| call256 / call256_nop | +0.982% [-10.387, +11.181] | +34.751% [+32.698, +36.741] | +6.298% [+6.233, +6.363] | +13.057% [+7.685, +18.116] |

Service sums combine separate PMU windows, normalized by each window's completed requests. They are not simultaneous global miss fractions.

Clean E2E precedes all PMU windows. Equal initial data and warmup/ROI duration do not imply identical completed request counts.

| Policy / control | Three MongoDBs retired L2 reduction | Three MongoDBs code-read miss reduction | Three MongoDBs I-cache data-stall reduction |
|---|---:|---:|---:|
| call256_nop / original | -1.466% [-2.121, -0.816] | -1.556% [-3.644, +0.490] | -1.280% [-2.230, -0.339] |
| call256 / original | +33.117% [+31.048, +35.124] | +4.800% [+2.576, +6.973] | +11.717% [+4.685, +18.230] |
| call256 / call256_nop | +34.084% [+31.606, +36.472] | +6.259% [+6.002, +6.515] | +12.832% [+6.764, +18.506] |
