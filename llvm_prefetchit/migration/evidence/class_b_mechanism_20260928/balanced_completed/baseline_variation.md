# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1158.29 | 3.3827 | 5.9688 | 5934.88 | 84.66% |
| 1 | 1163.81 | 3.3666 | 5.9237 | 5925.69 | 85.03% |
| 2 | 1195.60 | 3.2749 | 5.8658 | 5905.68 | 86.96% |
| 3 | 1165.41 | 3.3619 | 5.7874 | 5919.41 | 85.07% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1170.7753 | 1.438% | 3.187% |
| pool_util_pct | 85.4281 | 1.213% | 2.692% |
| mean_ms | 3.3465 | 1.451% | 3.219% |
| p99_ms | 5.8864 | 1.331% | 3.082% |
| stack_cpu | 5921.4116 | 0.207% | 0.493% |
