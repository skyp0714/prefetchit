# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1155.47 | 3.3903 | 5.9464 | 5946.46 | 84.50% |
| 1 | 1154.30 | 3.3945 | 5.8713 | 5943.61 | 84.56% |
| 2 | 1196.32 | 3.2723 | 5.8289 | 5909.58 | 87.10% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1168.6977 | 2.048% | 3.595% |
| pool_util_pct | 85.3860 | 1.737% | 3.047% |
| mean_ms | 3.3523 | 2.069% | 3.644% |
| p99_ms | 5.8822 | 1.012% | 1.998% |
| stack_cpu | 5933.2171 | 0.346% | 0.622% |
