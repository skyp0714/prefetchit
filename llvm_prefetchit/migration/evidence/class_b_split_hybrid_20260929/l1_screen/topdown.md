# Split75: frontend versus backend diagnosis

Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Top-down summary windows must pass the 2% closure/subset quality limits. Rejected raw windows are retained separately; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.

Each record is normalized by its own completed-request window. Mongo3 sums separately observed request-normalized counters before taking slot ratios. Reported percentages average per-block ratios. CPU-pool and service values overlap; do not add them.

Clean throughput, mean/p99 latency and whole CPU/request are in report.md. These are separate post-ROI diagnostics.

Maximum absolute raw level-1 closure error: 1.243% of slots. Raw values are retained, without forcing the sum to 100%. Hardware metrics use 8-bit fractions and kernel accounting clamps negative fraction-derived deltas; tiny differences below this precision should not be interpreted.

Top-down quality exclusions: 0 scope/trial records (including aggregate scopes). Raw counters remain in records; invalid windows are excluded only from these top-down averages and paired comparisons, not from clean endpoint metrics or other PMU events. Valid trial counts are recorded in topdown.json.

| Scope / policy | Retiring | Bad speculation | Frontend | Fetch latency | Fetch bandwidth | Backend | Memory bound | Core bound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mongo3 / split75 | 13.548% | 10.402% | 66.774% | 58.331% | 8.443% | 9.768% | 4.456% | 5.312% |
| mongo3 / extra_nop | 13.565% | 10.481% | 66.806% | 58.319% | 8.486% | 9.723% | 4.465% | 5.258% |
| mongo3 / extra_t1 | 13.468% | 10.480% | 66.896% | 58.398% | 8.497% | 9.769% | 4.565% | 5.204% |
| mongo3 / extra_it0 | 13.568% | 10.397% | 67.094% | 58.591% | 8.503% | 9.618% | 4.463% | 5.155% |
| pool_u / split75 | 13.042% | 9.117% | 65.828% | 57.409% | 8.419% | 12.331% | 7.147% | 5.184% |
| pool_u / extra_nop | 13.008% | 9.227% | 66.170% | 57.726% | 8.444% | 11.901% | 6.729% | 5.172% |
| pool_u / extra_t1 | 13.176% | 9.314% | 65.316% | 56.958% | 8.358% | 12.427% | 7.072% | 5.356% |
| pool_u / extra_it0 | 12.943% | 9.056% | 66.148% | 57.741% | 8.407% | 12.135% | 6.951% | 5.184% |
| pool_k / split75 | 17.904% | 7.574% | 32.806% | 23.480% | 9.326% | 41.777% | 27.807% | 13.970% |
| pool_k / extra_nop | 17.905% | 7.574% | 32.757% | 23.407% | 9.350% | 41.875% | 27.818% | 14.056% |
| pool_k / extra_t1 | 18.002% | 7.598% | 32.794% | 23.419% | 9.375% | 41.765% | 27.684% | 14.081% |
| pool_k / extra_it0 | 17.929% | 7.500% | 32.745% | 23.418% | 9.326% | 41.863% | 27.806% | 14.057% |

| Scope / policy | FE slots/request | BE slots/request | Execution-stall cycles/request | L1D-load stall | L3-load stall | Store stall |
|---|---:|---:|---:|---:|---:|---:|
| mongo3 / split75 | 8,222,206.2 | 1,205,954.5 | 1,333,941.1 | 429,756.2 | 1,677.2 | 12,569.7 |
| mongo3 / extra_nop | 8,224,038.5 | 1,199,881.8 | 1,339,241.4 | 427,576.7 | 1,615.6 | 12,108.3 |
| mongo3 / extra_t1 | 8,246,990.4 | 1,206,829.9 | 1,338,748.4 | 430,298.0 | 1,661.9 | 12,108.7 |
| mongo3 / extra_it0 | 8,274,406.3 | 1,189,430.7 | 1,341,045.9 | 429,717.1 | 1,643.4 | 12,081.9 |
| pool_u / split75 | 25,521,357.8 | 4,784,713.9 | 4,318,572.0 | 1,740,648.7 | 33,015.3 | 20,982.5 |
| pool_u / extra_nop | 25,596,552.8 | 4,605,772.5 | 4,406,198.9 | 1,799,659.1 | 50,308.4 | 21,020.4 |
| pool_u / extra_t1 | 25,559,564.0 | 4,869,679.5 | 4,381,876.5 | 1,780,737.8 | 42,401.6 | 21,169.1 |
| pool_u / extra_it0 | 25,601,155.8 | 4,701,417.2 | 4,373,100.5 | 1,773,956.2 | 43,848.3 | 20,767.1 |
| pool_k / split75 | 10,217,788.0 | 13,012,728.6 | 3,118,758.3 | 1,705,955.4 | 5,657.5 | 65,181.0 |
| pool_k / extra_nop | 10,240,974.0 | 13,091,543.2 | 3,116,797.6 | 1,701,291.7 | 6,827.6 | 65,187.0 |
| pool_k / extra_t1 | 10,217,656.9 | 13,013,266.7 | 3,109,716.6 | 1,696,589.8 | 5,892.1 | 64,611.7 |
| pool_k / extra_it0 | 10,220,503.8 | 13,066,735.0 | 3,132,383.9 | 1,708,709.0 | 6,620.9 | 65,683.0 |

Level-2 percentages are subsets: do not add them to their level-1 parent. Fetch latency is not a measurement of prefetch lead time. Memory stall counters may overlap frontend starvation. A changing percentage alone does not establish that absolute backend cost grew. Controlled timing/placement changes are required to test insufficient lead.

Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/) and [Intel top-down method](https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-0/top-down-microarchitecture-analysis-method.html).
