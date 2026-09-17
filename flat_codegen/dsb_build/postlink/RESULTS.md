# DeathStarBench user-timeline-service: post-link prefetch campaign (2026-09-17 overnight)

Setup: stock DSB socialNetwork images (Ubuntu 16.04 userland), mixed wrk2 load R=6000 on cores 60-67, service unpinned unless noted,
3 interleaved reps, 3.8 GHz frozen, metric = service-process cycles/MPKI/IPC over a 30 s window (`perf stat -p`), p50/p99 from wrk2.
"cycles vs base" = base cycles / arm cycles at the same request rate (higher = less CPU per request). Twins = same layout, prefetch→NOP.
Tools: `llvm_prefetchit/tools/postlink/postlink_call_stubs.py` (call-site stubs / in-place PLT / plan mode), `postlink_hotset_burst.py`,
`postlink_trace_plan.py`; harness `dsb_postlink_ab*.sh`, results in `results/round*/runs.csv`.

## Round 1 — per-call-site stubs, callee-entry burst (3 lines); note: prefetcht0 encoding (ModRM bug fixed afterwards)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 3.8 | 11.5 | 51.69 | 1.0000x | 21.85 | 0.644 | 1.000 |
| svc_plt_b3 | 3 | 6019 | 0 | 3.8 | 11.8 | 51.21 | 1.0093x | 22.68 | 0.659 | 1.014 |
| svc_plt_b3_nop | 3 | 6019 | 0 | 3.8 | 11.6 | 51.79 | 0.9981x | 22.57 | 0.652 | 1.016 |
| svc_all_b3 | 3 | 6019 | 0 | 3.8 | 11.6 | 52.53 | 0.9840x | 23.23 | 0.641 | 1.013 |
| svc_all_b3_nop | 3 | 6019 | 0 | 3.8 | 11.3 | 52.26 | 0.9891x | 23.14 | 0.646 | 1.015 |
| all_b3 | 3 | 6019 | 0 | 3.9 | 12.2 | 52.82 | 0.9785x | 22.94 | 0.643 | 1.022 |
| all_b3_nop | 3 | 6019 | 0 | 3.8 | 11.4 | 53.55 | 0.9651x | 23.75 | 0.636 | 1.024 |

## Round 2 — in-place 16-byte PLT rewrite (1 line at +64 via GOT/r11), LD_BIND_NOW=1
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 3.9 | 13.1 | 52.28 | 1.0000x | 22.07 | 0.633 | 1.000 |
| pli_svc | 3 | 6019 | 0 | 3.9 | 13.1 | 52.84 | 0.9894x | 21.33 | 0.637 | 1.017 |
| pli_svc_nop | 3 | 6019 | 0 | 3.9 | 12.7 | 53.11 | 0.9844x | 21.82 | 0.634 | 1.018 |
| pli_all | 3 | 6019 | 0 | 3.8 | 11.4 | 53.76 | 0.9726x | 21.87 | 0.630 | 1.024 |
| pli_all_nop | 3 | 6019 | 0 | 3.9 | 12.1 | 53.02 | 0.9862x | 21.63 | 0.640 | 1.024 |

## Round 3 — caller-stream lookahead stubs at every call (site+2 KB)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 3.9 | 11.5 | 54.53 | 1.0000x | 22.26 | 0.615 | 1.000 |
| seq2k | 3 | 6019 | 0 | 3.9 | 12.3 | 56.20 | 0.9702x | 23.92 | 0.606 | 1.016 |
| seq2k_nop | 3 | 6007 | 0 | 3.9 | 12.7 | 55.94 | 0.9748x | 24.15 | 0.608 | 1.014 |

## Round 5 — per-request hot-set burst at mongoc_client_pool_pop/push (550 / 1050 hottest lines across all DSOs)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 4.0 | 13.6 | 54.58 | 1.0000x | 21.79 | 0.615 | 1.000 |
| hot550 | 3 | 6019 | 0 | 4.0 | 14.0 | 54.58 | 1.0000x | 21.93 | 0.615 | 1.001 |
| hot550_nop | 3 | 6019 | 0 | 4.0 | 12.3 | 55.53 | 0.9828x | 21.78 | 0.608 | 1.007 |
| hot1050 | 3 | 6019 | 0 | 4.0 | 12.2 | 54.75 | 0.9968x | 21.81 | 0.615 | 1.004 |
| hot1050_nop | 3 | 6019 | 0 | 4.0 | 12.6 | 54.73 | 0.9972x | 22.09 | 0.614 | 1.001 |

## Round 6 — pinned-core controls and read-path hot-set burst (Tracer::Global + pool sites)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 4.0 | 12.1 | 55.88 | 1.0000x | 22.46 | 0.604 | 1.000 |
| pin4 | 3 | 6019 | 0 | 4.0 | 13.8 | 37.11 | 1.5057x | 6.43 | 0.881 | 0.970 |
| pin8 | 3 | 6019 | 0 | 4.0 | 15.0 | 41.46 | 1.3478x | 9.72 | 0.788 | 0.969 |
| hotG550 | 3 | 6019 | 0 | 4.0 | 14.7 | 55.75 | 1.0023x | 21.29 | 0.610 | 1.008 |
| hotG550_nop | 3 | 6019 | 0 | 4.0 | 13.2 | 55.26 | 1.0113x | 21.98 | 0.615 | 1.007 |

## Trace (results/trace_utl, 212k L2I-miss samples, 6.6M LBR records)
- Miss IPs: libc 27%, service 24%, libstdc++ 16%, jaeger 12%, pthread 7%, mongoc 5%, bson 4%, thrift 2%.
- Only 2,956 distinct miss lines; 50% of misses in 227 lines (14 KB), 90% in 1,050 lines (66 KB).
- 84% of miss IPs lie within 64 B of the last taken-branch target (target-line misses; IND 26%, COND 26%, CALL 21%, RET 11%).
- 97% of misses have a direct-call site with ≥60 cycles of lead in the LBR stack (1,066 sites; 437/1,216/2,644 site→line pairs for 50/75/90%).
- 4,625 distinct threads in 40 s (thread-per-connection, connection-per-request): every request starts on a cold core.

## Verilator cost check of the stub mechanism (qsort 100k, 3 reps)
[2026-09-17 04:06:05] qsort pl_b4r2_nop rep3: 50.918s ok
| variant | n | median s | vs base | vs own NOP twin | L2I MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 49.09 | 1.0000x | - | 57.04 | 0.607 | +100.00% |
| pl_b4 | 3 | 50.23 | 0.9773x | 1.0098x | 56.39 | 0.596 | +100.63% |
| pl_b4r2 | 3 | 50.41 | 0.9739x | 1.0090x | 57.08 | 0.600 | +101.50% |
| pl_b4_nop | 3 | 50.72 | 0.9678x | - | 58.03 | 0.591 | +100.65% |
| pl_b4r2_nop | 3 | 50.86 | 0.9652x | - | 59.31 | 0.594 | +101.50% |
| pl_b4plt | 3 | 51.50 | 0.9532x | 1.0081x | 57.78 | 0.584 | +101.09% |
| pl_b4plt_nop | 3 | 51.92 | 0.9455x | - | 59.57 | 0.579 | +101.08% |

