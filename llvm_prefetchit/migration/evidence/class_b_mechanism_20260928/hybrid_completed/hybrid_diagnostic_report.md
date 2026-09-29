# Switch-age hybrid: endpoint performance and gate mechanism

Fresh full Media compose-review C4, eight workload CPUs, MovieId included. Individual paired-log t95 intervals; no multiplicity correction. Clean E2E precedes PMU.

| Policy | RPS | Speedup vs original [95% CI] | Mean ms | p99 ms | Whole CPU us/request |
|---|---:|---:|---:|---:|---:|
| original | 1168.70 | 1.00000x (reference) | 3.3523 | 5.8822 | 5933.22 |
| cost75_split | 1174.02 | 1.00469x [0.95282, 1.05939] | 3.3366 | 5.8746 | 5861.84 |
| hybrid_nop | 1128.81 | 0.96596x [0.89193, 1.04613] | 3.4732 | 5.9582 | 6122.22 |
| early_t1 | 1161.25 | 0.99373x [0.96809, 1.02005] | 3.3741 | 5.9105 | 5984.78 |
| hybrid_it0 | 1153.49 | 0.98712x [0.94754, 1.02835] | 3.3971 | 5.9072 | 5994.39 |
| hybrid_sparse_nop | 1147.89 | 0.98233x [0.93627, 1.03066] | 3.4134 | 5.8898 | 6005.44 |
| hybrid_sparse | 1171.38 | 1.00243x [0.95433, 1.05295] | 3.3442 | 5.7915 | 5885.67 |
| hybrid_sparse_mixed | 1176.33 | 1.00659x [0.93196, 1.08720] | 3.3303 | 5.8610 | 5887.59 |

| Diagnostic | Service | Checks/request | Bursts/request | Mean qualifying age us | Fraction under 5us | Late gates | Observed races |
|---|---|---:|---:|---:|---:|---:|---:|
| full | user-review-mongodb | 1252.46 | 2.654 | 3.156 | 87.67% | 1258 | 20 |
| full | movie-review-mongodb | 1257.44 | 2.660 | 3.198 | 86.38% | 1517 | 14 |
| full | review-storage-mongodb | 332.42 | 1.304 | 3.652 | 86.49% | 887 | 8 |
| sparse | user-review-mongodb | 159.53 | 2.568 | 3.505 | 84.14% | 2718 | 21 |
| sparse | movie-review-mongodb | 160.51 | 2.577 | 3.483 | 84.20% | 2633 | 14 |
| sparse | review-storage-mongodb | 50.32 | 1.282 | 3.848 | 84.14% | 1157 | 7 |

Different-seed, counter-instrumented 35-second diagnostic runs, including startup. Counters record architectural path entries, not accepted or speculative hint requests; they do not prove that hardware prefetch activity is confined to the qualifying age. Sparse selection used full diagnostic only; its independent verification is not a reselection input. Mean age includes qualifying 0..10us bursts only, not all scheduler switches.

Sparse selection: 57 groups, 57 call sites; 90.00% of first-diagnostic bursts. This retained fraction is not measured cache-miss coverage.

| Policy / Mongo-3 per request | LATE_SWPF | Retired L2 | Speculative code-read miss | I-cache stall cycles | Unknown-branch cycles |
|---|---:|---:|---:|---:|---:|
| original | 0.000 | 5,446.319 | 60,914.735 | 610,699.474 | 737,957.447 |
| cost75_split | 0.000 | 2,737.808 | 56,855.604 | 503,548.527 | 619,461.682 |
| hybrid_nop | 0.000 | 5,753.385 | 71,320.366 | 702,321.279 | 757,936.223 |
| early_t1 | 0.000 | 2,790.539 | 65,174.495 | 548,336.235 | 583,279.577 |
| hybrid_it0 | 15.477 | 2,814.425 | 65,134.689 | 549,495.610 | 592,168.300 |
| hybrid_sparse_nop | 0.000 | 5,675.123 | 63,138.274 | 647,823.244 | 791,378.031 |
| hybrid_sparse | 2.518 | 2,699.610 | 57,088.935 | 506,867.229 | 614,237.027 |
| hybrid_sparse_mixed | 1.737 | 2,698.212 | 57,540.941 | 501,208.179 | 614,427.847 |

Post-ROI, separate request-normalized windows. LATE_SWPF counts overlap of demand misses with instruction-prefetch-triggered fetch; no ratio to FE_L2 from a different window is an accuracy or lateness probability. Zero does not prove timely success, no execution, or an empty fetch queue.

The kernel publishes the time of incoming-task selection. User-space RIP-relative hints run at the first selected call that observes a new epoch before the deadline; this is not execution of IT0 inside the scheduler. Gate checks, instruction expansion and the module are included in whole-policy E2E comparisons. Exact-layout NOP and early-T1 controls retain their guard costs.
