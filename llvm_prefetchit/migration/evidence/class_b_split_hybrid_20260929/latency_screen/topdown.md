# Split75: frontend versus backend diagnosis

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Top-down summary windows must pass the 2% closure/subset quality limits. Rejected raw windows are retained separately; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.

Each record is normalized by its own completed-request window. Mongo3 sums separately observed request-normalized counters before taking slot ratios. Reported percentages average per-block ratios. CPU-pool and service values overlap; do not add them.

Clean throughput, mean/p99 latency and whole CPU/request are in report.md. These are separate post-ROI diagnostics.

Maximum absolute raw level-1 closure error: 1.110% of slots. Raw values are retained, without forcing the sum to 100%. Hardware metrics use 8-bit fractions and kernel accounting clamps negative fraction-derived deltas; tiny differences below this precision should not be interpreted.

Top-down quality exclusions: 0 scope/trial records (including aggregate scopes). Raw counters remain in records; invalid windows are excluded only from these top-down averages and paired comparisons, not from clean endpoint metrics or other PMU events. Valid trial counts are recorded in topdown.json.

| Scope / policy | Retiring | Bad speculation | Frontend | Fetch latency | Fetch bandwidth | Backend | Memory bound | Core bound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mongo3 / original | 12.462% | 9.619% | 69.477% | 62.028% | 7.449% | 8.916% | 4.141% | 4.775% |
| mongo3 / split75 | 13.860% | 10.372% | 66.555% | 58.084% | 8.470% | 9.777% | 4.544% | 5.233% |
| mongo3 / extra_t1 | 13.712% | 10.428% | 66.660% | 58.173% | 8.486% | 9.839% | 4.492% | 5.347% |
| mongo3 / latency_t1 | 13.843% | 10.411% | 66.447% | 58.006% | 8.440% | 9.905% | 4.647% | 5.258% |
| pool_u / original | 12.661% | 8.934% | 66.737% | 58.674% | 8.064% | 11.962% | 6.827% | 5.135% |
| pool_u / split75 | 12.968% | 9.044% | 65.793% | 57.435% | 8.358% | 12.452% | 7.256% | 5.196% |
| pool_u / extra_t1 | 12.908% | 9.081% | 66.429% | 58.023% | 8.407% | 11.803% | 6.766% | 5.037% |
| pool_u / latency_t1 | 12.992% | 9.044% | 65.647% | 57.302% | 8.345% | 12.562% | 7.292% | 5.270% |
| pool_k / original | 18.039% | 7.463% | 32.610% | 23.272% | 9.338% | 41.986% | 27.893% | 14.093% |
| pool_k / split75 | 17.929% | 7.573% | 32.818% | 23.468% | 9.350% | 41.789% | 27.733% | 14.057% |
| pool_k / extra_t1 | 18.015% | 7.488% | 32.794% | 23.456% | 9.338% | 41.777% | 27.721% | 14.056% |
| pool_k / latency_t1 | 17.929% | 7.488% | 32.855% | 23.529% | 9.326% | 41.765% | 27.770% | 13.995% |

| Scope / policy | FE slots/request | BE slots/request | Execution-stall cycles/request | L1D-load stall | L3-load stall | Store stall |
|---|---:|---:|---:|---:|---:|---:|
| mongo3 / original | 9,439,957.3 | 1,214,185.9 | 1,550,361.3 | 451,719.6 | 1,675.8 | 12,299.0 |
| mongo3 / split75 | 8,212,955.9 | 1,210,772.2 | 1,335,142.2 | 427,720.0 | 1,704.1 | 12,853.2 |
| mongo3 / extra_t1 | 8,261,196.8 | 1,223,666.1 | 1,340,835.7 | 428,651.5 | 1,720.6 | 12,972.5 |
| mongo3 / latency_t1 | 8,219,290.3 | 1,229,317.0 | 1,336,619.3 | 429,953.9 | 1,727.6 | 13,061.7 |
| pool_u / original | 26,794,424.3 | 4,809,329.4 | 4,548,279.0 | 1,758,125.4 | 31,805.7 | 21,217.5 |
| pool_u / split75 | 25,605,835.0 | 4,847,189.0 | 4,329,755.4 | 1,741,511.4 | 32,355.6 | 21,732.5 |
| pool_u / extra_t1 | 25,562,060.8 | 4,543,479.5 | 4,361,031.6 | 1,766,544.0 | 44,712.9 | 21,897.0 |
| pool_u / latency_t1 | 25,519,595.9 | 4,887,048.0 | 4,359,842.1 | 1,774,449.9 | 41,222.4 | 21,773.1 |
| pool_k / original | 10,137,960.4 | 13,053,309.1 | 3,116,316.0 | 1,699,231.7 | 5,645.9 | 66,158.3 |
| pool_k / split75 | 10,259,633.4 | 13,064,436.0 | 3,117,095.8 | 1,702,162.9 | 5,872.1 | 64,549.2 |
| pool_k / extra_t1 | 10,216,295.1 | 13,015,166.0 | 3,100,487.0 | 1,691,435.8 | 5,859.9 | 64,868.8 |
| pool_k / latency_t1 | 10,226,257.2 | 12,999,980.3 | 3,095,048.7 | 1,692,195.3 | 5,811.8 | 64,925.2 |

Level-2 percentages are subsets: do not add them to their level-1 parent. Fetch latency is not a measurement of prefetch lead time. Memory stall counters may overlap frontend starvation. A changing percentage alone does not establish that absolute backend cost grew. Controlled timing/placement changes are required to test insufficient lead.

Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/) and [Intel top-down method](https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-0/top-down-microarchitecture-analysis-method.html).
