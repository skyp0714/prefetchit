# Split75: frontend versus backend diagnosis

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Top-down summary windows must pass the 2% closure/subset quality limits. Rejected raw windows are retained separately; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.

Each record is normalized by its own completed-request window. Mongo3 sums separately observed request-normalized counters before taking slot ratios. Reported percentages average per-block ratios. CPU-pool and service values overlap; do not add them.

Clean throughput, mean/p99 latency and whole CPU/request are in report.md. These are separate post-ROI diagnostics.

Maximum absolute raw level-1 closure error: 1.445% of slots. Raw values are retained, without forcing the sum to 100%. Hardware metrics use 8-bit fractions and kernel accounting clamps negative fraction-derived deltas; tiny differences below this precision should not be interpreted.

Top-down quality exclusions: 0 scope/trial records (including aggregate scopes). Raw counters remain in records; invalid windows are excluded only from these top-down averages and paired comparisons, not from clean endpoint metrics or other PMU events. Valid trial counts are recorded in topdown.json.

| Scope / policy | Retiring | Bad speculation | Frontend | Fetch latency | Fetch bandwidth | Backend | Memory bound | Core bound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mongo3 / original | 12.079% | 9.491% | 70.095% | 62.695% | 7.401% | 8.721% | 4.019% | 4.702% |
| mongo3 / split75 | 13.498% | 10.436% | 67.015% | 58.563% | 8.452% | 9.570% | 4.379% | 5.191% |
| mongo3 / early_t1 | 13.270% | 10.247% | 65.721% | 57.500% | 8.220% | 11.289% | 5.524% | 5.765% |
| mongo3 / early_it0 | 13.274% | 10.289% | 65.793% | 57.447% | 8.346% | 11.261% | 5.453% | 5.808% |
| pool_u / original | 12.452% | 8.909% | 67.669% | 59.532% | 8.137% | 11.411% | 6.509% | 4.902% |
| pool_u / split75 | 12.785% | 9.105% | 66.590% | 58.207% | 8.383% | 11.778% | 6.728% | 5.050% |
| pool_u / early_t1 | 12.783% | 9.081% | 66.150% | 57.816% | 8.333% | 12.281% | 7.011% | 5.270% |
| pool_u / early_it0 | 12.958% | 9.032% | 65.360% | 57.064% | 8.296% | 13.018% | 7.637% | 5.381% |
| pool_k / original | 18.002% | 7.476% | 32.511% | 23.223% | 9.289% | 42.011% | 27.808% | 14.203% |
| pool_k / split75 | 17.929% | 7.561% | 32.769% | 23.407% | 9.363% | 41.863% | 27.819% | 14.044% |
| pool_k / early_t1 | 17.929% | 7.525% | 32.818% | 23.529% | 9.289% | 41.740% | 27.684% | 14.056% |
| pool_k / early_it0 | 17.978% | 7.463% | 32.696% | 23.382% | 9.314% | 41.936% | 27.807% | 14.129% |

| Scope / policy | FE slots/request | BE slots/request | Execution-stall cycles/request | L1D-load stall | L3-load stall | Store stall |
|---|---:|---:|---:|---:|---:|---:|
| mongo3 / original | 9,414,342.2 | 1,173,165.3 | 1,541,940.1 | 451,877.0 | 1,565.6 | 11,040.9 |
| mongo3 / split75 | 8,193,961.1 | 1,172,396.4 | 1,331,981.9 | 426,834.3 | 1,994.8 | 11,583.4 |
| mongo3 / early_t1 | 8,216,846.6 | 1,413,299.3 | 1,366,489.4 | 435,585.6 | 1,691.5 | 11,420.8 |
| mongo3 / early_it0 | 8,208,084.8 | 1,406,630.2 | 1,367,524.1 | 438,122.1 | 1,583.6 | 11,384.7 |
| pool_u / original | 26,716,005.7 | 4,506,385.8 | 4,566,628.8 | 1,785,847.5 | 42,449.2 | 19,818.0 |
| pool_u / split75 | 25,517,115.4 | 4,514,619.8 | 4,380,507.8 | 1,790,271.6 | 48,509.7 | 20,133.7 |
| pool_u / early_t1 | 25,513,326.2 | 4,741,308.4 | 4,400,279.0 | 1,779,241.0 | 42,114.1 | 19,940.0 |
| pool_u / early_it0 | 25,465,798.2 | 5,072,885.5 | 4,344,418.8 | 1,744,168.4 | 32,232.3 | 19,920.9 |
| pool_k / original | 10,139,821.2 | 13,102,613.4 | 3,107,839.5 | 1,694,427.3 | 5,971.4 | 65,697.8 |
| pool_k / split75 | 10,205,201.7 | 13,037,590.4 | 3,119,828.9 | 1,701,399.3 | 5,779.4 | 64,764.7 |
| pool_k / early_t1 | 10,253,644.2 | 13,041,424.4 | 3,129,938.9 | 1,704,996.7 | 5,704.8 | 64,685.1 |
| pool_k / early_it0 | 10,177,161.7 | 13,054,319.9 | 3,134,996.5 | 1,705,454.0 | 6,554.4 | 65,011.9 |

Level-2 percentages are subsets: do not add them to their level-1 parent. Fetch latency is not a measurement of prefetch lead time. Memory stall counters may overlap frontend starvation. A changing percentage alone does not establish that absolute backend cost grew. Controlled timing/placement changes are required to test insufficient lead.

Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/) and [Intel top-down method](https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-0/top-down-microarchitecture-analysis-method.html).
