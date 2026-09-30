# Split75: frontend versus backend diagnosis

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Top-down summary windows must pass the 2% closure/subset quality limits. Rejected raw windows are retained separately; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.

Each record is normalized by its own completed-request window. Mongo3 sums separately observed request-normalized counters before taking slot ratios. Reported percentages average per-block ratios. CPU-pool and service values overlap; do not add them.

Clean throughput, mean/p99 latency and whole CPU/request are in report.md. These are separate post-ROI diagnostics.

Maximum absolute raw level-1 closure error: 1.200% of slots. Raw values are retained, without forcing the sum to 100%. Hardware metrics use 8-bit fractions and kernel accounting clamps negative fraction-derived deltas; tiny differences below this precision should not be interpreted.

Top-down quality exclusions: 0 scope/trial records (including aggregate scopes). Raw counters remain in records; invalid windows are excluded only from these top-down averages and paired comparisons, not from clean endpoint metrics or other PMU events. Valid trial counts are recorded in topdown.json.

| Scope / policy | Retiring | Bad speculation | Frontend | Fetch latency | Fetch bandwidth | Backend | Memory bound | Core bound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mongo3 / split75 | 13.531% | 10.426% | 66.778% | 58.370% | 8.409% | 9.614% | 4.463% | 5.151% |
| mongo3 / residual_t1 | 13.571% | 10.438% | 66.870% | 58.372% | 8.498% | 9.699% | 4.447% | 5.251% |
| mongo3 / lead512_nop | 11.812% | 9.243% | 70.857% | 63.502% | 7.355% | 8.493% | 3.889% | 4.603% |
| mongo3 / lead512 | 13.476% | 10.382% | 67.077% | 58.727% | 8.350% | 9.651% | 4.470% | 5.181% |
| pool_u / split75 | 12.859% | 9.105% | 66.146% | 57.715% | 8.431% | 12.160% | 7.049% | 5.111% |
| pool_u / residual_t1 | 12.931% | 9.081% | 66.161% | 57.790% | 8.371% | 12.134% | 6.998% | 5.135% |
| pool_u / lead512_nop | 12.685% | 8.983% | 66.579% | 58.564% | 8.015% | 12.035% | 6.815% | 5.221% |
| pool_u / lead512 | 12.931% | 9.032% | 65.965% | 57.632% | 8.333% | 12.378% | 7.169% | 5.209% |
| pool_k / split75 | 17.917% | 7.549% | 32.696% | 23.383% | 9.313% | 41.863% | 27.782% | 14.081% |
| pool_k / residual_t1 | 17.917% | 7.476% | 32.757% | 23.456% | 9.301% | 41.911% | 27.893% | 14.019% |
| pool_k / lead512_nop | 17.917% | 7.562% | 32.720% | 23.370% | 9.350% | 41.850% | 27.818% | 14.031% |
| pool_k / lead512 | 17.942% | 7.475% | 32.745% | 23.382% | 9.363% | 41.887% | 27.782% | 14.105% |

| Scope / policy | FE slots/request | BE slots/request | Execution-stall cycles/request | L1D-load stall | L3-load stall | Store stall |
|---|---:|---:|---:|---:|---:|---:|
| mongo3 / split75 | 8,202,351.2 | 1,183,652.4 | 1,332,376.2 | 425,828.9 | 1,648.3 | 12,097.3 |
| mongo3 / residual_t1 | 8,238,745.8 | 1,197,878.1 | 1,337,195.5 | 430,744.8 | 1,694.9 | 12,469.9 |
| mongo3 / lead512_nop | 9,868,183.8 | 1,185,048.8 | 1,616,440.9 | 458,448.3 | 1,623.8 | 11,299.9 |
| mongo3 / lead512 | 8,320,963.7 | 1,200,191.7 | 1,350,167.1 | 427,386.5 | 1,611.4 | 12,217.2 |
| pool_u / split75 | 25,566,952.1 | 4,704,780.9 | 4,343,064.1 | 1,753,444.6 | 34,658.1 | 20,869.5 |
| pool_u / residual_t1 | 25,590,608.4 | 4,695,618.9 | 4,365,295.0 | 1,774,772.9 | 42,828.8 | 21,142.7 |
| pool_u / lead512_nop | 27,183,714.3 | 4,916,665.1 | 4,610,719.9 | 1,757,363.9 | 33,244.2 | 20,188.8 |
| pool_u / lead512 | 25,695,281.5 | 4,823,142.9 | 4,345,329.8 | 1,744,332.1 | 33,125.2 | 20,773.8 |
| pool_k / split75 | 10,235,895.3 | 13,105,669.2 | 3,125,111.5 | 1,705,561.2 | 5,473.1 | 65,005.2 |
| pool_k / residual_t1 | 10,202,256.7 | 13,053,737.4 | 3,117,921.4 | 1,704,737.0 | 5,481.5 | 65,181.6 |
| pool_k / lead512_nop | 10,205,944.3 | 13,053,865.0 | 3,110,306.7 | 1,696,135.8 | 5,421.3 | 65,456.9 |
| pool_k / lead512 | 10,255,123.3 | 13,118,005.9 | 3,131,092.4 | 1,706,752.9 | 6,482.8 | 65,266.8 |

Level-2 percentages are subsets: do not add them to their level-1 parent. Fetch latency is not a measurement of prefetch lead time. Memory stall counters may overlap frontend starvation. A changing percentage alone does not establish that absolute backend cost grew. Controlled timing/placement changes are required to test insufficient lead.

Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/) and [Intel top-down method](https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-0/top-down-microarchitecture-analysis-method.html).
