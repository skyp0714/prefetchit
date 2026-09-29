# Original full Media C4: user/kernel frontend diagnostics

| Metric | User mean [range] | Kernel mean [range] |
|---|---:|---:|
| Cycles/request | 6599678.319 [6504073.963, 6695282.675] | 5212833.650 [5162265.934, 5263401.365] |
| Retired L2 events/request | 12191.455 [12155.456, 12227.453] | 2616.513 [2603.002, 2630.024] |
| Speculative code-read misses/request | 135160.760 [134638.534, 135682.986] | 45301.337 [45020.915, 45581.759] |
| I-cache data-stall cycles (%) | 22.083 [21.834, 22.331] | 10.946 [10.900, 10.992] |
| Instruction page-walk active cycles (%) | 8.018 [8.007, 8.029] | 0.574 [0.569, 0.578] |
| Frontend bound (%) | 67.659 [67.251, 68.068] | 32.474 [32.356, 32.592] |
| Retired ITLB events/request | 8558.109 [8542.598, 8573.621] | 1206.605 [1199.134, 1214.076] |
| Retired branch misprediction (%) | 5.052 [4.980, 5.124] | 2.062 [2.054, 2.070] |
| Unknown-branch bubble cycles (%) | 29.224 [29.129, 29.319] | 7.679 [7.658, 7.700] |
| DSB share of DSB + MITE uops (%) | 55.867 [55.096, 56.639] | 12.210 [12.180, 12.240] |

Separate user/kernel windows on workload CPUs 32-39. Values are two-repeat diagnostic means/ranges, not confidence intervals. Per-window requests/instructions/cycles are the denominators. Overlapping frontend events do not partition stall causes. Unknown-branch bubbles are not a direct count of absent BTB entries or missed FDIP opportunities. DSB share excludes other uop sources. No E2E inference.

Event definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).
