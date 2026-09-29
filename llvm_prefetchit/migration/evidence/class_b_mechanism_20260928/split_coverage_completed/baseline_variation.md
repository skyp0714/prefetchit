# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1193.00 | 3.2819 | 5.8956 | 5904.89 | 86.84% |
| 1 | 1159.50 | 3.3774 | 5.8460 | 5935.24 | 84.94% |
| 2 | 1157.49 | 3.3851 | 5.8796 | 5948.28 | 84.98% |
| 3 | 1158.42 | 3.3820 | 5.9040 | 5945.72 | 85.04% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1167.1052 | 1.481% | 3.043% |
| pool_util_pct | 85.4516 | 1.086% | 2.226% |
| mean_ms | 3.3566 | 1.487% | 3.077% |
| p99_ms | 5.8813 | 0.435% | 0.985% |
| stack_cpu | 5933.5350 | 0.336% | 0.731% |
