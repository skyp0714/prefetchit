# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1175.74 | 3.3311 | 5.7912 | 5854.86 | 84.89% |
| 1 | 1177.37 | 3.3263 | 5.8219 | 5838.62 | 84.83% |
| 2 | 1182.29 | 3.3125 | 5.7728 | 5831.89 | 85.09% |
| 3 | 1179.59 | 3.3199 | 5.8038 | 5845.83 | 85.08% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1178.7458 | 0.241% | 0.556% |
| pool_util_pct | 84.9729 | 0.155% | 0.304% |
| mean_ms | 3.3225 | 0.242% | 0.559% |
| p99_ms | 5.7974 | 0.357% | 0.847% |
| stack_cpu | 5842.8011 | 0.169% | 0.393% |
