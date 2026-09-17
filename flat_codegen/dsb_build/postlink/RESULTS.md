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
## Round 11 — wake-up warm-up (LD_PRELOAD, user-space stand-in for a kernel switch-in warm-up), rebuilt base image
Per request: 5.6 context switches, ~13.6k L2I misses (~2.4k per wake). Trace with sched_switch + sys_exit attributes 99% of misses to a
preceding wake-up (recv 12.5k, poll 9.8k, cond 8.5k wakes / 30 s). `warmup/warmup.c` wraps recv/recvfrom/read/readv/poll/epoll_wait: when
the call took >20k cycles (the thread slept), it prefetcht1's the first N lines of that hook's list (lines ordered by median time after the
wake, `wake_lines.py`). w64 = 64 lines/wake (top-256 list); w128s = 128 + 128 staged (top-1024 list). Twins issue NOPs instead. `P` = main@40 / pool@41-44.
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| g | 3 | 6019 | 0 | 3.8 | 12.2 | 53.97 | 1.0000x | 21.82 | 0.623 | 1.000 |
| w64 | 3 | 6019 | 0 | 4.0 | 13.3 | 52.95 | 1.0193x | 21.31 | 0.637 | 1.002 |
| w64_nop | 3 | 6019 | 0 | 3.8 | 12.1 | 53.91 | 1.0012x | 21.93 | 0.626 | 1.003 |
| w128s | 3 | 6019 | 0 | 3.9 | 11.8 | 53.66 | 1.0059x | 20.68 | 0.636 | 1.015 |
| w128s_nop | 3 | 6019 | 0 | 3.8 | 11.5 | 55.06 | 0.9802x | 21.92 | 0.616 | 1.008 |
| gP | 3 | 6019 | 0 | 3.8 | 11.8 | 36.17 | 1.4923x | 5.85 | 0.896 | 0.963 |
| w64P | 3 | 6019 | 0 | 3.7 | 11.0 | 36.69 | 1.4710x | 5.80 | 0.890 | 0.970 |
| w64P_nop | 3 | 6019 | 0 | 3.8 | 11.6 | 36.74 | 1.4690x | 5.87 | 0.889 | 0.971 |

Accounting (12 s smoke, w64): 43% of the warm-up prefetches were real L2 fills (vs 1% for in-code plans) — the hook is right, but 64–256 lines
per wake cover only a few % of the ~2,400 lines missed per wake; net +1–2%.
## Round 12 — paced wake-up warm-up (512 / 1024 lines per wake, 32-line batches separated by 8 pause iterations; `libwarmup_p.so`)
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| g | 3 | 6019 | 0 | 3.8 | 11.7 | 55.51 | 1.0000x | 22.58 | 0.609 | 1.000 |
| wp512 | 3 | 6019 | 0 | 3.9 | 12.3 | 55.57 | 0.9989x | 20.35 | 0.629 | 1.032 |
| wp512_nop | 3 | 6019 | 0 | 3.9 | 13.1 | 56.76 | 0.9779x | 21.42 | 0.615 | 1.032 |
| wp1024 | 3 | 6019 | 0 | 3.9 | 13.8 | 56.53 | 0.9818x | 19.02 | 0.634 | 1.060 |
| wp1024_nop | 3 | 6019 | 0 | 3.9 | 12.0 | 58.03 | 0.9565x | 20.92 | 0.619 | 1.061 |

The paced warm-up removes up to 16% of the misses (22.6 → 19.0 MPKI, the largest reduction of any prefetch arm on this service) but the
thread stalls while it paces (instructions +6%): net 0.98–1.00x. A kernel switch-in warm-up issued the same way would pay the same stall;
only an asynchronous prefetch engine (hardware "warm-up list" that streams the lines while the thread runs) could turn the miss reduction into time.

## Round 13 — isolation baseline (other 26 containers moved off cores 40-44; service main@40 / pool@41-44): warm-up on top of isolation
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs gI | MPKI | IPC | instr vs gI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gI | 3 | 6019 | 0 | 3.8 | 11.4 | 32.47 | 1.0000x | 1.89 | 0.991 | 1.000 |
| w64I | 3 | 6019 | 0 | 3.8 | 11.8 | 32.41 | 1.0018x | 2.11 | 0.990 | 0.997 |
| w64I_nop | 3 | 6019 | 0 | 3.8 | 11.9 | 32.44 | 1.0008x | 1.96 | 0.990 | 0.998 |
| wp512I | 3 | 6019 | 0 | 3.8 | 11.5 | 34.06 | 0.9533x | 1.88 | 0.975 | 1.032 |

On the isolated baseline the service's intrinsic miss rate is ~1.9 MPKI and the wake-up warm-up is exactly neutral (1.002x, twin 1.001x);
the paced 512-line variant only pays its stall (0.953x). There is no prefetch headroom left once the pollution is removed.
## When do the post-wake misses happen? (results/trace_wake, 16,159 wake windows)
| within N µs after the wake | 1 | 2 | 5 | 10 | 20 | 40 | 100 |
|---|---:|---:|---:|---:|---:|---:|---:|
| share of misses | 0.2% | 1.4% | 5.8% | 13% | 27% | 52% | 92% |
Run window (wake → next sleep) median 65 µs. The misses are spread over the whole run, not front-loaded: a warm-up that uses the kernel's
switch-in lead (0.5–1.5 µs before user code resumes) can address ~1–2% of them; 84% of misses sit within 64 B of a taken-branch target
(next-line hardware prefetch already covers fall-through), so what remains is branch targets scattered through the 65 µs run.
Upper bounds for a kernel warm-up module (I-side slope measured 0.7% cycles per MPKI): isolated 4-core baseline 1.9 MPKI → ≤1.3% (measured 1.002x);
4 cores shared with other containers 5.7 MPKI → ≤4% (measured 0%); kernel-lead-only coverage → ≤0.3%.

## Conclusion
No prefetch arm moves user-timeline's CPU time by more than ~1%; the only large effect is core pinning (1.51x). The L2I misses of this
service are L2 pollution by co-scheduled containers during the ~30 ms idle gaps between a thread's requests, not a
prefetchable code stream. Trace-guided post-link placement does reduce misses by 11% (pgo75) but its stub overhead (+5.7% instructions)
cancels the gain. Injecting the same kind of plan inline via a full rebuild (round 10, no stub overhead) gives +1.2% unpinned and +0.3% with
the service pinned (main thread on its own core, workers on a 4-core pool): the prefetchable remainder is small once the pollution is removed by pinning.
Wake-up warm-up (rounds 11–12): the right hook — 43% of its prefetches are real fills and it removes up to 16% of misses — but a
software burst is bounded by the fill queue (64–128 lines per wake, +1–2%) and pacing to 1,024 lines stalls the thread as long as the
misses would have (0.98x). Best DSB result overall: w64 1.019x (unpinned). On the isolated baseline (the realistic deployment, 1.9 MPKI) every prefetch arm is
neutral. Isolation remains the only large lever (1.64x); a kernel switch-in warm-up could at best hide 1–3 µs of the wake burst per switch
when the core was polluted, i.e. a few % only on shared cores, and nothing on isolated cores.
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

# Cold-start screening (2026-09-17 afternoon, default Linux scheduling, cores 0-42 only)
Protocol: every container of the stack confined to cores 0-35 (they float among themselves = a busy multi-tenant node under default
scheduling); `shared` = measured in that state; `isolated` = the one container moved to cores 36-39 that nobody else uses. Sequential
`perf stat -p` 30 s per container under the mixed wrk2 load (R=6000, clients on 40-42). ΔMPKI × 0.7 %/MPKI = I-side headroom estimate.

## socialNetwork (25 containers)
| container | cs/s | instr/s (G) | MPKI shared | MPKI isolated | ΔMPKI | IPC sh→iso | cycles sh/iso | I-side headroom ≈0.7%×ΔMPKI |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| socialnetwork-compose-post-service-1 | 7639 | 0.62 | 22.9 | 4.4 | 18.5 | 0.51→0.83 | 1.77x | 12.9% |
| socialnetwork-post-storage-memcached-1 | 27750 | 1.45 | 7.3 | 0.3 | 7.1 | 0.77→0.97 | 1.30x | 5.0% |
| socialnetwork-user-timeline-mongodb-1 | 861 | 1.19 | 10.2 | 7.0 | 3.1 | 1.46→1.86 | 0.56x | 2.2% |
| socialnetwork-post-storage-service-1 | 32896 | 21.54 | 2.6 | 0.6 | 2.0 | 1.90→2.24 | 1.19x | 1.4% |
| socialnetwork-home-timeline-service-1 | 14427 | 2.10 | 6.4 | 5.3 | 1.1 | 1.07→1.34 | 1.28x | 0.7% |
| socialnetwork-url-shorten-mongodb-1 | 791 | 0.19 | 36.6 | 36.5 | 0.1 | 0.53→0.61 | 0.62x | 0.1% |
| socialnetwork-text-service-1 | 2780 | 0.95 | 6.6 | 8.8 | -2.2 | 1.36→1.54 | 1.15x | -1.5% |
| socialnetwork-social-graph-mongodb-1 | 35 | 0.01 | 8.5 | 11.5 | -3.0 | 0.98→0.95 | 0.89x | -2.1% |
| socialnetwork-user-mongodb-1 | 35 | 0.01 | 8.8 | 12.7 | -3.9 | 0.95→0.88 | 0.88x | -2.7% |
| socialnetwork-user-mention-service-1 | 1328 | 0.20 | 19.9 | 46.2 | -26.2 | 0.66→0.54 | 0.85x | -18.4% |
| socialnetwork-home-timeline-redis-1 | 2998 | 0.39 | 6.4 | 37.9 | -31.5 | 0.66→0.45 | 0.71x | -22.1% |
| socialnetwork-post-storage-mongodb-1 | 2928 | 0.78 | 42.0 | 75.1 | -33.1 | 0.48→0.37 | 0.80x | -23.2% |
| socialnetwork-url-shorten-service-1 | 2113 | 0.18 | 27.3 | 66.6 | -39.3 | 0.49→0.41 | 0.91x | -27.5% |
| socialnetwork-user-memcached-1 | 2819 | 0.09 | 26.5 | 77.7 | -51.2 | 0.51→0.37 | 0.83x | -35.8% |
| socialnetwork-social-graph-service-1 | 1332 | 0.11 | 14.8 | 86.8 | -72.1 | 0.67→0.37 | 0.31x | -50.4% |
| socialnetwork-social-graph-redis-1 | 587 | 0.04 | 22.1 | 114.9 | -92.8 | 0.64→0.32 | 0.53x | -65.0% |
| socialnetwork-unique-id-service-1 | 725 | 0.05 | 23.8 | 127.4 | -103.7 | 0.47→0.27 | 0.60x | -72.6% |
| socialnetwork-media-service-1 | 719 | 0.05 | 20.9 | 125.1 | -104.3 | 0.49→0.27 | 0.58x | -73.0% |
| socialnetwork-user-timeline-redis-1 | 2086 | 0.11 | 19.4 | 126.6 | -107.2 | 0.52→0.25 | 0.56x | -75.0% |
| socialnetwork-user-service-1 | 722 | 0.05 | 23.5 | 135.2 | -111.6 | 0.48→0.26 | 0.58x | -78.1% |

Two classes. Busy services lose to pollution and recover when isolated (compose-post 22.9→4.4 MPKI, 1.77x; post-storage memcached
7.3→0.3, 1.30x; home-timeline 6.4→5.3, 1.28x). Low-activity services (≤0.2 G instr/s: unique-id, user, media, social-graph, url-shorten,
user-mention and their redis/memcached) get *worse* when isolated (24→127, 20→125, 22→115 …): their exclusive cores idle into core C6
(170 µs exit latency, 650 µs target residency, enabled by default; 2.3 M C6 entries per core during the run), which flushes L2, so every
wake is fully cold. On shared cores the neighbours keep the core awake and part of the code survives. See the C-state separation below.

## hotelReservation (Go services; socialNetwork load running as co-tenant noise; wrk2 mixed R=3000 on the frontend)
| container | cs/s | instr/s (G) | MPKI shared | MPKI isolated | ΔMPKI | IPC sh→iso | cycles sh/iso | I-side headroom ≈0.7%×ΔMPKI |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| hotelreservation-frontend-1 | 11727 | 0.64 | 17.7 | 9.0 | 8.6 | 0.70→0.87 | 1.30x | 6.0% |
| hotelreservation-mongodb-profile-1 | 35 | 0.01 | 7.2 | 6.1 | 1.1 | 0.96→1.10 | 1.03x | 0.8% |
| hotelreservation-mongodb-geo-1 | 36 | 0.01 | 7.2 | 6.7 | 0.5 | 0.95→1.02 | 1.08x | 0.4% |
| hotelreservation-mongodb-attractions-1 | 35 | 0.01 | 6.4 | 6.1 | 0.3 | 0.99→1.07 | 1.09x | 0.2% |
| hotelreservation-mongodb-rate-1 | 35 | 0.02 | 3.9 | 6.1 | -2.2 | 1.18→1.05 | 1.53x | -1.5% |
| hotelreservation-mongodb-recommendation-1 | 27 | 0.02 | 3.6 | 6.4 | -2.7 | 1.17→1.04 | 1.36x | -1.9% |
| hotelreservation-mongodb-user-1 | 1 | 0.01 | 0.6 | 5.9 | -5.2 | 1.46→1.10 | 0.60x | -3.7% |

Only the Go frontend is busy enough to read (17.7→9.0 MPKI, 1.30x; 6% I-side headroom — but Go code is not addressable by our AOT
pass or post-link tools in a stable way). The Go backends executed <5 M instructions per 30 s under this load (rows omitted), so the
suite adds no candidate. Mongo sidecars: 4–7 MPKI, isolation-neutral.

## C-state separation on isolated cores (36-39 exclusive; core C6/C6P enabled vs disabled via cpuidle)
| container | instr/s (G) | MPKI iso C6 on | MPKI iso C6 off | IPC on→off | cycles on/off |
|---|---:|---:|---:|---|---:|
| unique-id-service | 0.05 | 17.5 | 17.5 | 0.55→0.55 | 1.00x |
| social-graph-service | 0.11 | 10.9 | 10.8 | 0.76→0.76 | 1.00x |
| user-mention-service | 0.19 | 12.3 | 12.5 | 0.79→0.78 | 0.99x |
| post-storage-service | 20.7 | 1.3 | 1.3 | 2.11→2.11 | 1.00x |
| compose-post-service | 0.57 | 4.9 | 4.8 | 0.78→0.78 | 1.01x |
| **home-timeline-service** | 2.06 | 5.3 | **0.1** | 1.34→1.64 | **1.23x** |
Only home-timeline is C6-bound (its cores idle into C6 between its bursts; with C6 disabled MPKI 5.3→0.1 and 23% fewer cycles).
The low-activity services (≤0.2 G instr/s) are insensitive to C6 and their MPKI swings between runs (10–130) because a handful of sparse
wake bursts (e.g. jaeger reconnect attempts) dominate their tiny instruction counts — not stable candidates and negligible in cycles.
The earlier "isolated is worse" rows for them are that run-to-run swing, not a C-state effect.

## Native candidates under socialNetwork co-tenant noise (process floats on 0-42 vs pinned to 36-39 exclusive)
| workload | cs/s | instr/s (G) | MPKI shared | MPKI isolated | ΔMPKI | IPC sh→iso | cycles sh/iso | I-side headroom |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| **MariaDB 10.11 durable** (fsync+binlog, sysbench oltp_rw 8 threads) | 61964 | 8.67 | **12.0** | **3.8** | 8.2 | 1.10→1.41 | **1.33x** | 5.8% |
| TailBench masstree (integrated, 4 threads, 2000 qps) | 2195 | 0.44 | 9.5 | 9.5 | 0.0 | 0.32→0.32 | 1.00x | 0 |
| PostgreSQL scale 100 (pgbench 16 clients) | — | — | (multi-process; re-screen queued) | | | | | |
MariaDB is a second strong cold-start candidate (2.1k context switches per second per thread-equivalent; misses fall 3× when isolated);
masstree's 9.5 MPKI is intrinsic (unchanged by isolation). TailBench xapian/img-dnn/sphinx need the missing 10 GB input set.

## Round 14 — "timeline" prefetch, inline via the IR pass (default scheduling, every container confined to cores 0-35)
Plan: per 5 µs slot after a wake, the 3 most-sampled IPs become sites; targets = lines whose first use is 10–20 µs later (63 sites,
1,646 targets incl. libc/libstdc++ lines via exported-symbol GOT anchors). The pass matched only 85 of 410 main-binary sites by debug
location (266 sites have no matching file:line after -O3 inlining) → service 86 prefetcht1, libs bson 40 / thrift 38 / jaeger 19 / mongoc 13.
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| g | 3 | 6019 | 0 | 3.9 | 12.3 | 56.66 | 1.0000x | 19.84 | 0.604 | 1.000 |
| tl | 3 | 6019 | 0 | 3.9 | 14.4 | 56.36 | 1.0053x | 20.00 | 0.609 | 1.004 |
| tl_nop | 3 | 6019 | 0 | 3.9 | 17.3 | 56.73 | 0.9988x | 20.12 | 0.607 | 1.007 |
| tlw64 | 2 | 6019 | 0 | 3.9 | 12.3 | 56.32 | 1.0061x | 19.91 | 0.611 | 1.006 |
| tlw64_nop | 2 | 6019 | 0 | 3.9 | 12.2 | 56.43 | 1.0041x | 20.27 | 0.609 | 1.005 |

Verdict: +0.5% (twin −0.1%), MPKI unchanged — the inline route places too few of the planned sites. Round 15 places the same plan
post-link at the exact call sites (57 sites, ~1.3k prefetches).
