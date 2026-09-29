# Call-path frontend diagnostic

Request performance is measured separately in the [completed E2E comparison](../coverage75_completed/screen_report.md).

6 fresh stacks and 90 fully scheduled windows. Each counter window has its own completed-request denominator.

| Scope / arm | Retired ITLB/request | Walk-active cycles/request | Critical DSB/request | ANY_ANT/request | MISP_ANT/request |
|---|---:|---:|---:|---:|---:|
| mongo_user / original | 1,449.03 | 79,396.60 | 40,894.52 | 38,441.42 | 3,886.70 |
| mongo_user / cost75_nop | 1,485.22 | 80,164.56 | 42,482.85 | 38,085.71 | 3,940.79 |
| mongo_user / cost75 | 1,436.37 | 38,545.18 | 42,504.58 | 38,130.41 | 3,917.15 |
| mongo_movie / original | 1,437.93 | 79,524.57 | 40,781.75 | 38,108.51 | 3,872.42 |
| mongo_movie / cost75_nop | 1,468.17 | 81,222.19 | 42,385.63 | 38,107.58 | 3,930.74 |
| mongo_movie / cost75 | 1,436.25 | 40,452.26 | 42,311.11 | 38,512.35 | 3,916.31 |
| mongo_storage / original | 488.75 | 33,924.40 | 11,084.15 | 7,922.19 | 1,268.38 |
| mongo_storage / cost75_nop | 501.02 | 33,439.92 | 11,468.58 | 7,911.54 | 1,266.45 |
| mongo_storage / cost75 | 482.49 | 17,896.99 | 11,456.86 | 7,925.81 | 1,268.56 |
| pool_user / original | 8,507.64 | 510,785.66 | 278,595.71 | 332,934.03 | 20,231.54 |
| pool_user / cost75_nop | 8,637.10 | 522,063.91 | 282,053.90 | 334,409.03 | 20,586.53 |
| pool_user / cost75 | 8,512.07 | 430,043.31 | 281,543.85 | 332,565.33 | 20,505.99 |
| pool_kernel / original | 1,222.81 | 29,617.16 | 361,419.10 | 284,479.22 | 4,559.00 |
| pool_kernel / cost75_nop | 1,214.94 | 30,729.38 | 362,992.48 | 285,057.29 | 4,687.97 |
| pool_kernel / cost75 | 1,229.22 | 29,650.30 | 361,926.64 | 284,251.28 | 4,624.40 |

| Scope / T1 versus its NOP | Retired ITLB reduction | Walk-active reduction | Critical DSB reduction | ANY_ANT reduction | MISP_ANT reduction |
|---|---:|---:|---:|---:|---:|
| mongo_user | +3.29% | +51.92% | -0.05% | -0.10% | +0.60% |
| mongo_movie | +2.17% | +50.20% | +0.18% | -1.02% | +0.37% |
| mongo_storage | +3.70% | +46.48% | +0.10% | -0.18% | -0.17% |
| pool_user | +1.45% | +17.63% | +0.18% | +0.55% | +0.39% |
| pool_kernel | -1.20% | +3.52% | +0.29% | +0.28% | +1.35% |

Separate request-normalized diagnostic windows, not E2E timing or an exclusive cause partition. ANY_ANT and MISP_ANT describe particular conditional-branch conditions, not all BTB misses. Do not divide MISP_ANT by ANY_ANT as a misprediction probability: the published ANY_ANT definition excludes mispredicted branches. CPU-pool and service scopes overlap. Critical DSB and ITLB events can overlap cache/branch costs. The cost75 candidate is fixed independently of performance outcomes.

Ranges in summary.json describe two repetitions, not confidence intervals. Individual paired-log intervals and zero-count absolute records are retained in complete.json and rows.json. No multiplicity correction.

Event semantics follow the [Intel Granite Rapids PMU reference](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

Request spans: all six 200-trace sets have 177–200 incomplete parent graphs. Do not infer critical paths or E2E effects. See request_paths.json and the verified compressed raw records.
