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

## Round 7 — trace-guided post-link plans (direct-call sites with ≥60 cycles lead → up to 4 missed lines; pgo50 = 321 sites/581 targets, pgo75 = 928 sites/2,861 targets; cross-DSO via GOT anchors; exe + 7 libs incl. libc/libpthread patched)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 4.1 | 13.6 | 56.01 | 1.0000x | 22.28 | 0.607 | 1.000 |
| pgo75 | 3 | 6019 | 0 | 4.0 | 15.1 | 55.47 | 1.0098x | 19.82 | 0.648 | 1.057 |
| pgo75_nop | 3 | 6019 | 0 | 4.0 | 13.1 | 57.48 | 0.9744x | 22.05 | 0.624 | 1.056 |
| pgo50 | 3 | 6019 | 0 | 4.0 | 11.8 | 56.28 | 0.9953x | 20.74 | 0.629 | 1.042 |
| pgo50_nop | 3 | 6019 | 0 | 4.1 | 12.8 | 56.80 | 0.9861x | 21.77 | 0.622 | 1.040 |

## Round 8 — pinned to 4 cores: baseline vs trace-guided plan (intrinsic remainder)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs pin4 | MPKI | IPC | instr vs pin4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pin4 | 3 | 6019 | 0 | 4.0 | 12.3 | 38.57 | 1.0000x | 6.96 | 0.849 | 1.000 |
| pin4_pgo75 | 3 | 6019 | 0 | 4.1 | 14.9 | 38.46 | 1.0028x | 6.33 | 0.904 | 1.062 |
| pin4_pgo75_nop | 3 | 6019 | 0 | 4.1 | 17.3 | 38.93 | 0.9907x | 6.92 | 0.892 | 1.060 |

## Round 9 — site-frequency-capped plans (exclude call sites above the 90th / 75th percentile of LBR CALL records; coverage 37% / 16.5%)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs base | MPKI | IPC | instr vs base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 3 | 6019 | 0 | 4.1 | 16.9 | 57.40 | 1.0000x | 22.59 | 0.590 | 1.000 |
| pgo75c90 | 3 | 6019 | 0 | 4.0 | 12.5 | 57.61 | 0.9964x | 22.51 | 0.596 | 1.015 |
| pgo75c90_nop | 3 | 6019 | 0 | 4.1 | 13.5 | 58.31 | 0.9844x | 23.25 | 0.589 | 1.015 |
| pgo75c75 | 3 | 6019 | 0 | 4.2 | 19.0 | 57.48 | 0.9985x | 22.44 | 0.594 | 1.009 |
| pgo75c75_nop | 3 | 6019 | 0 | 4.1 | 16.0 | 57.90 | 0.9914x | 23.03 | 0.590 | 1.009 |

## Round 4 — full clang-19 rebuild of the userland (service + thrift/mongoc/bson/jaeger/opentracing) with the IR pass, plan-free modes
Images `dsb-deps-g` (base), `dsb-deps-b3` (callee-entry burst 3 lines: service 345 + libs ~3.6k prefetches), `dsb-deps-seq` (seq D=4 KB K=40 + burst: service 2,138 + libs ~9k). libc/libstdc++ remain distro binaries. Reference arm = g.
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| g | 3 | 6019 | 0 | 4.1 | 13.0 | 58.98 | 1.0000x | 22.59 | 0.590 | 1.000 |
| b3 | 3 | 6019 | 0 | 4.2 | 14.7 | 58.93 | 1.0009x | 22.16 | 0.592 | 1.004 |
| b3_nop | 3 | 6019 | 0 | 4.1 | 18.9 | 59.35 | 0.9937x | 22.54 | 0.590 | 1.006 |
| seq | 3 | 6019 | 0 | 4.1 | 13.0 | 59.44 | 0.9923x | 22.09 | 0.589 | 1.007 |
| seq_nop | 3 | 6019 | 0 | 4.1 | 17.0 | 59.52 | 0.9909x | 22.22 | 0.590 | 1.009 |

## Round 10 — inline trace-guided plan in a full clang-19 rebuild, under both baselines (2026-09-17 12:21–12:49)
Trace taken on the rebuilt base (`dsb-deps-g`, -g everywhere, pass-built hiredis/redis++) with the service pinned main@40 / worker pool@41-44.
Plans per binary (`prefetchit_trace_to_plan.py`, cov 75%, budget 2, depth 2–8): service 90 sites (+97 hiredis/redis++ sites routed to the libs plan),
libs 360 injections (GOT operands); built inline by the IR pass (no stubs): service 100 prefetcht1, mongoc 97, bson 52, jaeger 37, redis++ 29, thrift 23.
`P` = main thread on core 40, worker threads on 41-44 (`pin_threads.sh`); reference arm = g (unpinned rebuilt base).
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| g | 3 | 6019 | 0 | 3.9 | 12.0 | 53.72 | 1.0000x | 21.91 | 0.627 | 1.000 |
| gP | 3 | 6019 | 0 | 3.8 | 11.4 | 36.23 | 1.4828x | 5.74 | 0.898 | 0.965 |
| pgo | 3 | 6019 | 0 | 3.9 | 16.4 | 53.11 | 1.0115x | 21.22 | 0.641 | 1.011 |
| pgo_nop | 3 | 6019 | 0 | 3.8 | 11.1 | 53.85 | 0.9976x | 21.86 | 0.634 | 1.013 |
| pgoP | 3 | 6019 | 0 | 3.9 | 12.3 | 36.11 | 1.4878x | 5.48 | 0.911 | 0.976 |
| pgoP_nop | 3 | 6019 | 0 | 3.9 | 12.8 | 36.16 | 1.4856x | 5.61 | 0.911 | 0.977 |

Read as: unpinned plan 1.0115x vs base (twin 0.998x; MPKI 21.9→21.2); pinned plan vs pinned base 36.11 vs 36.23 G = 1.003x (MPKI 5.74→5.48).
## Conclusion
No prefetch arm moves user-timeline's CPU time by more than ~1%; the only large effect is core pinning (1.51x). The L2I misses of this
service are L2 pollution by co-scheduled containers during the ~30 ms idle gaps between a thread's requests, not a
prefetchable code stream. Trace-guided post-link placement does reduce misses by 11% (pgo75) but its stub overhead (+5.7% instructions)
cancels the gain. Injecting the same kind of plan inline via a full rebuild (round 10, no stub overhead) gives +1.2% unpinned and +0.3% with
the service pinned (main thread on its own core, workers on a 4-core pool): the prefetchable remainder is small once the pollution is removed by pinning.
## Software-prefetch accounting of the inline-plan arm (30 s windows, R=6000; L2_RQSTS.SWPF_HIT/MISS = prefetcht1 that reached L2 and hit/missed)
| arm | instr (G) | L2I MPKI | L2I misses (M) | sw prefetches at L2 (M) | of which missed = real fills (M) | useful share |
|---|---:|---:|---:|---:|---:|---:|
| g | 41.8 | 18.00 | 753 | 0 | 0.20 | 62.25% |
| pgo | 34.2 | 21.00 | 717 | 256 | 2.65 | 1.04% |
| gP | 42.7 | 3.89 | 166 | 0 | 0.28 | 67.06% |
| pgoP | 60.9 | 3.00 | 183 | 430 | 1.04 | 0.24% |

Reading: the plan's prefetches execute in bulk (250–430 M per 30 s) but 99% of them find their target already in L2. Only 1–2.7 M lines
were actually fetched against 180–750 M demand code misses. The misses are the cold-start burst at the beginning of each request
(transport/parse code in libthrift/libstdc++/libc, before any site in our code runs); by the time the plan's sites fire, the request's
working set is already re-warmed. `P` = pinned main@40 / pool@41-44 (other containers still float over those cores).

## Isolation control (other 26 containers moved off cores 40-44, service main@40 / pool@41-44, rebuilt base)
instr 32.3 G, cycles 32.7 G (**1.64x vs unpinned g**, 1.11x vs gP), IPC 0.99, **L2I MPKI 1.99** (results/swpf/gP_isolated.csv).
With the pollution removed the service's intrinsic instruction-miss rate is ~2 MPKI; there is nothing left for software prefetch to recover.

## Trace (results/trace_utl, 212k L2I-miss samples, 6.6M LBR records)
- Miss IPs: libc 27%, service 24%, libstdc++ 16%, jaeger 12%, pthread 7%, mongoc 5%, bson 4%, thrift 2%.
- Only 2,956 distinct miss lines; 50% of misses in 227 lines (14 KB), 90% in 1,050 lines (66 KB).
- 84% of miss IPs lie within 64 B of the last taken-branch target (target-line misses; IND 26%, COND 26%, CALL 21%, RET 11%).
- 97% of misses have a direct-call site with ≥60 cycles of lead in the LBR stack (1,066 sites; 437/1,216/2,644 site→line pairs for 50/75/90%).
- Thread census under load: 71–75 alive threads (one per nginx keepalive connection), median 1 running (max 4), ~1 new thread/s — threads are long-lived; each idles ~30 ms between requests, during which other containers evict the core's L2. (An earlier reading of 4,625 distinct TIDs from the perf dump is not reproduced by the direct census.)

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

