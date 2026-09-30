# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1183.32 | 3.3094 | 5.8632 | 5917.82 | 86.35% |
| 1 | 1179.19 | 3.3214 | 5.9068 | 5912.04 | 85.92% |
| 2 | 1160.72 | 3.3758 | 5.8625 | 5934.09 | 84.92% |
| 3 | 1162.69 | 3.3696 | 5.8224 | 5922.50 | 84.84% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1171.4794 | 0.977% | 1.929% |
| pool_util_pct | 85.5047 | 0.873% | 1.766% |
| mean_ms | 3.3440 | 1.003% | 1.986% |
| p99_ms | 5.8637 | 0.588% | 1.439% |
| stack_cpu | 5921.6102 | 0.158% | 0.372% |
