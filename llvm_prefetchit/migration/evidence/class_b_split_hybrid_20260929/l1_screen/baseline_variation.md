# Baseline variation

Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.

| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |
|---|---:|---:|---:|---:|---:|
| 0 | 1176.02 | 3.3302 | 5.7814 | 5843.47 | 84.80% |
| 1 | 1191.02 | 3.2868 | 5.8484 | 5841.05 | 85.72% |
| 2 | 1186.17 | 3.3012 | 5.8351 | 5832.86 | 85.30% |
| 3 | 1214.50 | 3.2227 | 5.8293 | 5819.09 | 87.16% |

| Metric | Mean | Sample CV | Full range / mean |
|---|---:|---:|---:|
| rps | 1191.9269 | 1.367% | 3.228% |
| pool_util_pct | 85.7477 | 1.182% | 2.747% |
| mean_ms | 3.2852 | 1.382% | 3.271% |
| p99_ms | 5.8236 | 0.502% | 1.150% |
| stack_cpu | 5834.1152 | 0.189% | 0.418% |
