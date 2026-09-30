# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1207.32 | 3.2426 | 5.7662 | 5806.83 | 86.40% |
| 1 | 1179.04 | 3.3213 | 5.7895 | 5840.09 | 84.87% |
| 2 | 1181.87 | 3.3135 | 5.7583 | 5838.06 | 84.92% |
| 3 | 1176.57 | 3.3289 | 5.7995 | 5851.64 | 84.89% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1186.2006 | 1.201% | 2.592% |
| pool_util_pct | 85.2706 | 0.885% | 1.802% |
| mean_ms | 3.3016 | 1.206% | 2.615% |
| p99_ms | 5.7784 | 0.335% | 0.714% |
| stack_cpu | 5834.1541 | 0.329% | 0.768% |
