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
| **PostgreSQL 16 scale 100** (pgbench 16 clients, 16 backends) | 300445 | 16.97 | **6.0** | **0.1** | 5.8 | 0.87→1.22 | **1.88x** | 4.1% |
PostgreSQL loses even more to co-tenancy (1.88x, its isolated MPKI is 0.1). MariaDB is a second strong cold-start candidate (2.1k context switches per second per thread-equivalent; misses fall 3× when isolated);
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

## MariaDB durable under socialNetwork noise — wake-up warm-up (LD_PRELOAD, host glibc build incl. fsync/pwrite wrappers), 3 reps
Trace: 1.46 M poll wakes + 130 k cond + 110 k fsync/pwrite per 30 s; 7,805 distinct post-poll miss lines, the top-256 list covers only
27% of poll-wake misses (cond 75%). A/B (sysbench oltp_rw 8 threads, 50 s runs, server counters over 30 s):
| arm | tps (median) | MPKI | IPC | cycles per transaction (rel.) |
|---|---:|---:|---:|---:|
| base | 2460 | 12.6 | 1.08 | 1.00 |
| warm64 (64 lines per wake) | 2102 | 13.6 | 1.05 | 1.01 |
| warm64 NOP twin | 2348 | 12.6 | 1.09 | 1.03 |
tps swings ±8% between reps (fsync-bound + co-tenant noise); per-transaction cycles are equal within 3% and MPKI does not fall: the
64-line warm-up covers too little of MariaDB's broad post-wake footprint. No gain.

## Round 15 — "timeline" prefetch placed post-link at exact call sites (same plan; 57 sites snapped to the preceding direct call)
Service 13 sites / 890 prefetches, jaeger 5/103, mongoc 6/62, bson 5/110, thrift 3/113; cross-DSO targets through GOT anchors. Default scheduling, containers on 0-35.
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| g | 3 | 6019 | 0 | 4.1 | 50.6 | 56.97 | 1.0000x | 19.80 | 0.605 | 1.000 |
| tlpl | 3 | 6019 | 0 | 4.0 | 63.1 | 57.28 | 0.9947x | 19.99 | 0.601 | 0.998 |
| tlpl_nop | 3 | 6019 | 0 | 4.0 | 15.4 | 57.30 | 0.9942x | 19.90 | 0.599 | 0.995 |
| tlplw64 | 2 | 6013 | 0 | 4.0 | 14.4 | 57.24 | 0.9953x | 20.03 | 0.602 | 0.999 |
| tlplw64_nop | 2 | 6019 | 0 | 4.0 | 11.9 | 58.44 | 0.9749x | 20.40 | 0.593 | 1.005 |

Verdict: identical to the twin and to base (MPKI 19.8 → 20.0). Prefetching lines 10–20 µs ahead along the observed post-wake
timeline does not convert: the lines a request needs 10–20 µs later are not the ones on this request's path often enough, and
each site issues 60–70 prefetches at once (fill-queue bound). Together with rounds 11–14 this closes the software side for
user-timeline: wake burst +1.9%, inline plan +0.5%, post-link timeline 0.

## PostgreSQL under socialNetwork noise — wake-up warm-up (LD_PRELOAD inherited by the 16 backends; epoll_wait/cond/poll lists), 3 reps
| arm | tps (median) | MPKI | IPC | cycles per transaction (rel.) |
|---|---:|---:|---:|---:|
| base | 38212 | 5.85 | 0.870 | 1.000 |
| warm64 (64 lines per wake) | 38653 (1.012x) | 6.00 | 0.876 | 0.963 |
| warm64 NOP twin | 38349 (1.004x) | 6.15 | 0.862 | 0.999 |
tps varies ±2–5% between reps; MPKI does not fall. At most ~1% — same picture as user-timeline and MariaDB.

# Campaign conclusion (cold start, default Linux scheduling, prefetch-only remedies)
- Cold-start-dominated workloads are common and the loss is large: PostgreSQL 1.88x, compose-post 1.77x, user-timeline 1.64x,
  MariaDB 1.33x, home-timeline 1.28x when the service gets cores of its own (or, for home-timeline, when C6 is disabled: 1.23x).
- Every software prefetch remedy tried on them stays within ±2%: wake burst (user-timeline 1.019x; MariaDB and PostgreSQL ≈1.00x),
  paced 1,024-line warm-up (miss −16% but 0.982x), inline timeline plan (1.005x), post-link timeline plan at exact call sites (0.995x).
- Reason (measured): after a wake the misses are taken-branch targets spread over the whole ~65 µs run (2 µs: 1.4%, 10 µs: 13%,
  40 µs: 52%); the hardware next-line prefetcher already covers the sequential part; a software burst is bounded by 32–48 in-flight
  fills and pacing stalls the thread as long as the misses would have. A kernel switch-in warm-up shares these bounds (≤0.3% from the
  lead window alone). What captures the loss is placement (isolation, 1.3–1.9x) or an asynchronous hardware warm-up engine.

## μSuite (wenischlab/MicroSuite, gRPC C++ microservices; leaf + mid-tier measured separately; open-loop load 3,000 qps; SN stack as co-tenant noise)
| service / tier | cs/s | instr/s (G) | MPKI shared | MPKI isolated | ΔMPKI | IPC sh→iso | cycles sh/iso | I-side headroom |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| Router leaf (memcached lookup, gRPC) | 12060 | 0.50 | **52.8** | **37.9** | 14.9 | 0.42→0.50 | 1.21x | 10.4% |
| Router mid-tier (gRPC fan-out) | 26287 | 0.96 | **48.0** | **35.0** | 13.0 | 0.39→0.49 | 1.28x | 9.1% |
| SetAlgebra | — | — | μSuite's open-loop load generator corrupts its heap (SIGSEGV in `UnionServiceClient::Union` → `std::map::operator[]`, `malloc_consolidate` abort): a data race between its sender and response threads; the closed-loop generator aborts at startup. Not measurable without patching the generator. | | | | | |
| HDSearch | — | — | with the corrected leaf arguments both tiers start, but the bucket (leaf) server dies on the first request with a protobuf `CHECK failed: index < current_size_` (2018 generated code vs protobuf 3.21) — needs a code fix; deferred | | | | | |
Router is different from everything screened before: even fully isolated it keeps 35–38 MPKI at IPC 0.5 — a large intrinsic
instruction-miss component (gRPC/protobuf/memcached-client code path), on top of a 13–15 MPKI cold-start share. That makes it the first
service-class workload where in-code static/PGO prefetch (our original tool) is worth testing.

## Cold-start loss decomposition — user-timeline, default scheduling (shared 0-35 with 26 containers) vs isolated (main@40, pool@41-44, others off)
| per 1,000 instructions | shared | isolated | Δ |
|---|---:|---:|---:|
| L2 code misses | 15.23 | 2.62 | +12.6 |
| L2 demand data misses | 5.16 | 2.50 | +2.7 |
| branch mispredicts | 7.55 | 2.67 | +4.9 |
| ITLB walks | 0.89 | 0.22 | +0.7 |
| DTLB load walks | 0.68 | 0.23 | +0.5 |
| IPC | 0.670 | 0.954 | CPI +0.44 |
The shared-core penalty is 0.44 cycles per instruction. With typical exposed costs (code/data L2 miss 20–50 cycles, mispredict ~20,
page walk ~30) the code misses are the largest single component (roughly half), branch mispredicts ~20–25%, data misses ~25–30%,
TLB walks <10%. So the earlier "instruction misses are only a quarter of the loss" inference (drawn from what prefetching *recovered*)
was wrong about the cause: the misses matter; software prefetch recovered little of them because its fills arrive late relative to the
branchy front-end demand (miss 1% removed ≈ 0.16% cycles), and it cannot touch the mispredict and data-miss shares at all.
(top-down slots group did not count under `-p`; not needed.)

## Round 16 — PREFETCHIT0/1 in the static modes (seq D=4 KB K=40 + callee burst 3, rebuilt service + libs; 3,763 prefetchit in the service, ~13k in the libs), default scheduling
| arm | reps | rps | non2xx | p50 ms | p99 ms | svc cycles (G) | cycles vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| seqit1 | 3 | 6019 | 0 | 3.7 | 11.7 | 55.08 | 0.9959x | 20.56 | 0.609 | 1.000 |
| seqit1_nop | 3 | 6019 | 0 | 3.7 | 11.4 | 54.96 | 0.9979x | 20.30 | 0.611 | 1.001 |
| seqit0 | 2 | 6013 | 0 | 3.7 | 11.4 | 55.00 | 0.9973x | 20.54 | 0.612 | 1.003 |
| seqit0_nop | 2 | 6019 | 0 | 3.7 | 12.8 | 55.13 | 0.9949x | 20.05 | 0.611 | 1.004 |
| g | 2 | 6019 | 0 | 3.8 | 13.1 | 54.85 | 1.0000x | 20.04 | 0.612 | 1.000 |

The prefetchit arms equal their NOP twins and the base (cycles within ±0.5%, MPKI 20.0–20.6): on this cold-start workload the
instruction prefetch hint changes nothing measurable, same as prefetcht1 did (round 4). (Encodings verified: prefetchit0 = 0F 18 3D,
prefetchit1 = 0F 18 35, RIP-relative; `/proc/cpuinfo` on this kernel does not list a `prefetchi` flag.)

## PREFETCHIT on Verilator (the frontend-starved reference: 57 MPKI, IPC 0.6) — same static arm (seq D=4 KB K=20 + burst 4, 209k sites), qsort 100k cycles, 3 reps
| variant | median s | vs base | vs own NOP twin | L2I MPKI | IPC |
|---|---:|---:|---:|---:|---:|
| base | 48.17 | 1.000x | — | 57.0 | 0.618 |
| prefetcht1 (round-4 arm) | 41.96 | **1.148x** | — | 13.7 | 0.757 |
| prefetchit1 | 54.27 | 0.888x | 0.948x | 59.1 | 0.586 |
| prefetchit1 NOP twin | 51.44 | 0.936x | — | 59.3 | 0.618 |
| prefetchit0 | 54.16 | 0.889x | 0.950x | 58.9 | 0.587 |
| prefetchit0 NOP twin | 51.44 | 0.936x | — | 59.3 | 0.618 |
With identical placement, prefetcht1 gains 15% and cuts MPKI 57→14, while prefetchit1/0 lose 11% (5% worse than their own NOP twins,
whose cost is the +7% instruction bloat of the seq code) and leave MPKI unchanged.
Counters (Verilator, 15k simulated cycles, core 34): prefetcht1 arm L2I 15.7 MPKI, IPC 0.68, 52 M software prefetches (6.8 M fills);
prefetchit1 arm L2I 65.3 MPKI = its NOP twin (65.4), IPC 0.520 vs twin 0.546, L2 code reads 77.0/kI vs 66.8/kI (+15%), and zero
SWPF events (PREFETCHIT is not a data prefetch). So PREFETCHIT does issue extra L2 code-read requests (it is not inert) but they do not
reduce demand code misses at all — they arrive too late or duplicate in-flight demand — and the extra traffic costs ~5% time.

## μSuite Router — static "seq" pass on the app binaries (leaf + mid-tier rebuilt with clang-19 + pass: seq D=4 KB K=40; prefetcht1 vs prefetchit0/1; NOP twins), 3 reps, 3,000 qps open loop, 22:00 2026-09-17

| tier / scheduling | base MPKI / IPC | seq prefetcht1 | seq prefetchit1 | seq prefetchit0 |
|---|---|---|---|---|
| leaf isolated (36-39) | 29.3 / 0.614 | 29.2 / 0.615, **0.988x** (twin 0.997x) | 29.2, 1.001x (twin 0.987x) | 28.6, 0.989x (twin 0.983x) |
| mid-tier isolated | 45.9 / 0.410 | 45.3 / 0.411, **0.984x** (twin 1.003x) | 45.0, 1.008x (twin 0.989x) | 45.4, 0.984x (twin 0.981x) |
| leaf shared (0-42 + SN noise) | 29.5 / 0.673 | 29.5, 0.991x (twin 1.017x) | 28.0, 1.017x (twin 1.012x) | 28.0, 1.011x (twin 0.994x) |
| mid-tier shared | 53.5 / 0.384 | 53.6, 1.001x (twin 1.000x) | 55.1, 0.987x (twin 0.993x) | 54.4, 1.002x (twin 0.999x) |

Speedup = base median cycles / arm median cycles over the 30 s window at fixed load (service CPU time per request). Every arm is within
±2% of its NOP twin and MPKI is unchanged (±1): the Router's 30–50 MPKI is not in the application TUs the pass can instrument (lookup/mid-tier
servers are thin; the misses are in libgrpc++/libprotobuf/libstdc++, prebuilt shared libraries). prefetchit0/1 arms are twins here as well.
Next for Router: DSO breakdown (`run/router_dso.sh`) and, if the misses are in gRPC/protobuf, the same fat-static + direct-reference cold-path
build used for the user-timeline round 18 (gRPC/protobuf rebuilt from source with the pass, linked statically).

## Round 17 — cold-path static mode of the IR pass (user request: a pass for short-dispatch services; no cost function; loop-free sites), shared-library build, 3 reps, 22:08 2026-09-17

Mode (`PREFETCHIT_COLD_OWN_LINES=16 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24`):
at the entry of every function with ≥24 IR instructions, `prefetcht1` of the function's own next lines (≤16, sized from the IR instruction count)
and of the first line of every callee reached outside loops, in block order (defined callee → pc-relative via an internal alias; declared callee →
`mov sym@GOTPCREL(%rip),%r11; prefetcht1 (%r11)`). Service 11,622 prefetches, jaeger 15,973, mongoc 5,026, redis++ 4,593, bson 1,426, thrift 891+.
Arms rebuilt in `dsb-deps-cold` (`chain_cold.sh`); default scheduling, containers on 0-35; `w32` = 32-line wake burst (LD_PRELOAD) alone.

| arm | svc cycles (G) | vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|
| g (clang-19 rebuild, shared libs) | 55.60 | 1.000x | 19.54 | 0.611 | 1.000 |
| cold | 55.20 | **1.007x** | **18.34** | 0.629 | 1.022 |
| cold_nop (twin) | 55.72 | 0.998x | 19.79 | 0.627 | 1.029 |
| coldw32 (+ wake burst 32) | 55.51 | 1.002x | 18.40 | 0.630 | 1.030 |
| coldw32_nop | 55.81 | 0.996x | 19.73 | 0.627 | 1.031 |
| w32 (wake burst alone) | 56.20 | 0.989x | 19.82 | 0.607 | 1.005 |

The pass removes 6% of the code misses (IPC +3%) but adds 2.2% instructions, net +0.7%. The wake burst adds nothing on top.

## Round 18 — GOT bypass by fat-static linking + direct references (user: "컴파일러 flag로 GOT 우회해서 명령어 오버헤드 줄여"), 3 reps, 22:37

Build: `FATSTATIC=1 build_utl_variant.sh` links libthrift.a, libjaegertracing.a, libopentracing.a, libyaml-cpp.a, libmongoc-static, libbson-static,
hiredis/redis++ and `-static-libstdc++ -static-libgcc` into the PIE service (NEEDED shrinks to libc/libm/libssl/libcrypto/libsasl2/libicuuc/libz/libresolv).
Pass: `PREFETCHIT_COLD_DIRECT_SYMS=plans/cold_direct_syms.txt` (13,456 global symbols of those archives + the service) → listed declared callees get one
`prefetcht1 sym(%rip)`; executable modules reference every symbol by name (no alias). Service TUs: own 3,007, direct 594, listed-direct 1,204, GOT 217
(libc). The archives were still the round-17 objects (GOT form inside jaeger/thrift/…: 9,231 `(%r11)` sites of 31,088). `cold2s` = libc callees skipped.

| arm | svc cycles (G) | vs g | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|---:|
| g (shared libs) | 55.56 | 1.000x | 0.963x | 19.85 | 0.611 | 0.994 |
| gs (fat-static, no pass) | 53.49 | **1.039x** | 1.000x | 18.07 | 0.639 | 1.000 |
| cold2 (fat-static + cold pass, direct) | 53.18 | **1.045x** | 1.006x | **16.74** | 0.654 | 1.018 |
| cold2_nop (twin) | 54.12 | 1.027x | 0.988x | 18.12 | 0.645 | 1.022 |
| cold2s (libc callees skipped) | 53.45 | 1.040x | 1.001x | 16.92 | 0.650 | 1.017 |

Static linking alone (no PLT/GOT hops, one link unit) is worth 3.9% and −9% misses. On top of it the direct-reference cold pass removes a further
7% of the misses (18.1 → 16.7) and is worth 1.8% against its twin, but the twin costs 1.2% (+1.8% instructions), so the net is +0.6% over gs
(+4.5% over the original shared-library build). Skipping the libc GOT prefetches changes nothing (0.5% of sites).

## Round 19 — dependency archives rebuilt static-only with direct references (`dsb-deps-cold3`, `rebuild_deps_static.sh`; jaeger 19,293 rip / 275 r11, thrift 6,073 / 240, yaml 8,173 / 204; mongoc/bson keep the GOT form because their shared-library build cannot be disabled), 3 reps, 23:01

| arm | svc cycles (G, median) | vs gs | vs g | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|---:|
| g (shared libs) | 57.15 | 0.945x | 1.000x | 19.68 | 0.599 | 1.001 |
| gs (fat-static, no pass) | 54.00 | 1.000x | 1.058x | 18.23 | 0.633 | 1.000 |
| cold3 (own 16, callee 1, all direct) | 53.83 | **1.003x** (mean 1.010x) | 1.062x | **16.21** | 0.649 | 1.022 |
| cold3_nop (twin) | 54.42 | 0.992x | 1.050x | 18.06 | 0.642 | 1.022 |
| cold3o8 (own 8) | 54.39 | 0.993x | 1.051x | 16.83 | 0.644 | 1.024 |

Like-for-like (static vs static): the pass removes 11% of the code misses and is worth 1.1% against its twin, but +2.2% instructions cost 0.8%,
net +0.3% (median) / +1.0% (mean; per-rep cold3 53.2/53.8/54.0 vs gs 54.6/54.0/54.0). Own-lines 8 keeps the miss reduction but not the gain.
Shared vs shared (round 17): the same pass in GOT form is +0.7% net. Either way the cold-path pass is ≈ +1% on user-timeline; the 5–6% between
g and gs is the static link itself (45k PLT call sites removed, one packed 2.8 MB .text instead of six DSOs), not prefetching.

## Round 20 — cold-path restricted to functions that miss (trace of the cold3 twin: 240 functions = 90% of exe misses → `PREFETCHIT_SEQ_FUNCTIONS_FILE`; service sites 44 instead of 495; library bursts unchanged), 2 reps, 23:33

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 55.23 | 1.000x | 18.29 | 0.624 | 1.000 |
| cold4 | 54.22 | **1.019x** | **16.77** | 0.646 | 1.017 |
| cold4_nop (twin) | 55.18 | 1.001x | 18.12 | 0.633 | 1.014 |

Same miss reduction as cold3 (−8%) with the twin now free (1.001x): the service-side bursts were mostly overhead; the +1.7% instructions
that remain come from the library archives (19.7k sites), which the function list does not touch.

## Static targets vs traced misses (cold3 layout: twin trace = baseline misses, prefetch-binary trace = residual; `cold_target_analysis.py`, `results/target_analysis_cold3.txt`)

- Miss samples: exe 55.7%, libc 42.9% (static pass reaches only the exe half; libc only via GOT entry lines).
- Of the exe misses, 56.9% fall on lines the pass targets. Uncovered: 17.7% in functions with no site at all (prebuilt libstdc++ / thrift
  template code, functions < 24 IR insns), 15.4% beyond the own-lines cap (IR-size estimate too small or > 16 lines deep), 5.6% callee
  interior lines, 4.3% entries reached only by virtual/indirect calls.
- Waste: 16,486 of 17,874 target lines (84% of the 24,706 sites) never miss in the twin trace.
- Residual: with the prefetches in place 53% of the remaining exe misses are on targeted lines (issued too late at the entry, or dropped
  from a 32-prefetch burst).
→ Round 21 (`chain_cold6.sh`): trace-guided cold plan (`cold_plan.py`: LBR trace of gs, each missed line attributed to the oldest
  instrumentable function entry with 60–4,000 cycles of lead; exe lines pc-relative, libc lines via GOT anchor + displacement; bursts
  padded to 16 B so offsets stay exact) built into both the service and the static-only archives (`dsb-deps-plan`), arms gs / cold5 / cold5_nop.

## Why does the static link gain? Counter decomposition g / gs / cold3 (per 1k instructions, 2 reps, service pid, 30 s window, `cold_counters.sh`, 23:43)

| arm | IPC | L2 code miss | L2 data miss | ITLB walk | DTLB load walk | branch mispred | indirect mispred | ret mispred |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| g (shared libs) | 0.602 | 19.62 | 5.81 | 0.78 | 0.82 | 7.22 | 1.75 | 0.15 |
| gs (fat-static) | 0.635 | 17.88 (−9%) | 5.42 (−7%) | 0.66 (−15%) | 0.78 | 7.13 | 1.65 (−6%) | 0.16 |
| cold3 (gs + cold pass, all direct) | 0.645 | 16.32 (−9% vs gs) | 5.39 | 0.55 (−17% vs gs) | 0.95 (+22%) | 6.93 | 1.57 | 0.16 |

The static link removes work on every front the PLT/GOT touched: fewer code misses (PLT stubs and scattered DSO pages gone), fewer data
misses (GOT loads gone), fewer ITLB walks (one packed text instead of six DSOs), fewer indirect mispredicts (the PLT's `jmp *GOT`). The
cold pass then cuts code misses and ITLB walks further (software code prefetch also warms the page walk) but raises DTLB load walks by 22%:
`prefetcht1` goes through the data path, so every prefetch of a cold code page costs a DTLB lookup/walk — a cost the twin does not pay.

## Round 21 — trace-guided cold plan v1 (LBR attribution to the oldest instrumentable entry with 60–4,000 cycles lead; 191 sites, 1,639 targets incl. 288 libc lines via GOT anchors), 23:58 — INVALID (root disk fell to 2.8 GB during rep 2: gs rep 2 returned 946 non-2xx, p99 10 s) but the rep-1 numbers already decide it

| arm | svc cycles (G, rep 1) | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|
| gs | 55.25 | 18.07 | 0.627 | 1.000 |
| cold5 (plan v1) | 57.18 | 12.88 | 0.733 | **1.21** |
| cold5_nop | 57.30 | 15.18 | 0.732 | 1.21 |

The plan removes far more misses than any static heuristic (misses per instruction −29%, IPC +17%) but costs 21% more instructions:
the attributed sites are *hot* functions (TVirtualTransport::read, std::function handlers, SpanContext::fromStream) that execute dozens of
times per request, and each execution re-issues its ~10-line burst. Net −3.5%. Lesson: a plan site must be a *cold* function (executed
about once per wake) — or the burst must be gated to fire once per epoch. → plan v4 (round 24): sites chosen by lowest entry rate
(cycles+LBR rate trace), pairs costing > 20 prefetch executions per saved miss dropped. Disk lesson recorded in memory; `janitor.sh` added.

## Round 24 — cost-aware trace-guided plan v4 (site = lowest-entry-rate instrumentable function in the miss's LBR window with 60–4,000 cycles lead, fallback = oldest running function; pairs costing > 20 prefetch executions per saved miss dropped; 336 sites, 2,356 targets incl. 518 libc lines via GOT anchors; hiredis/mongoc/bson/redis++ sites in GOT form), 3 reps, 00:17

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs | p99 ms |
|---|---:|---:|---:|---:|---:|---:|
| gs | 55.98 | 1.000x | 18.29 | 0.623 | 1.000 | 12.6 |
| cold8 (plan v4) | 54.38 | **1.029x** | **15.58** | 0.667 | 1.040 | 139.8 |
| cold8_nop (twin) | 56.31 | 0.994x | 17.80 | 0.643 | 1.038 | 12.4 |

Best static-vs-static result so far: 3.5% against the twin, +2.9% net (the +4.0% instructions cost 0.6%). Per-rep spread < 1%.
Target check in the twin's layout: 757 of 881 planned exe lines are exact miss lines, 120 land one line short (register-allocation drift
after the burst), 124 never miss. Residual misses on targeted lines fell to 37% (from 53%); the top residual lines are the post-wake
socket-read path (TSocket::read, TFramedTransport::readFrame, ConnectionPool::fetch) whose only possible site is the previous request's
tail — a wake burst's job, not a static site's. Open question: p99 is 133–143 ms in all three cold8 reps versus 12–17 ms for gs and the twin.

## Round 25 — plan v4 without libc/GOT targets (cold8n: 1,632 direct + 69 GOT sites), 3 reps, 00:50

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 55.85 | 1.000x | 18.29 | 0.620 | 1.000 |
| cold8n | 55.48 | 1.007x | 16.00 | 0.652 | 1.045 |

Dropping the 518 libc lines loses most of the gain (1.029x → 1.007x): the libc half of the misses is worth prefetching and the GOT form
is not the problem. The ~200 ms p99 spikes appeared here in one gs rep and one cold8n rep, so the round-24 tail was environmental
(the disk janitor's image removals and scans coincided with cold8's slots), not the prefetches; the janitor now idles during measurements.
seqA (sequential mode on the 240 missing functions) did not build: docker rejects the upper-case image name — rebuilt as `seqa` in round 28.

## Round 26 — epoch-gated plan v5 (burst fires once per request per thread: hidden global epoch incremented at ReadUserTimeline, per-site TLS "last epoch"; 339 sites, 2,459 targets, 319 gated), 3 reps, 00:47

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 56.32 | 1.000x | 18.13 | 0.621 | 1.000 |
| cold9 (plan v5, gated) | 55.57 | 1.014x | 15.52 | 0.656 | 1.042 |
| cold9_nop (twin) | 57.76 | 0.975x | 17.96 | 0.635 | 1.049 |

Gating removes nothing that matters: the cost-aware v4 sites were already cold, so the miss reduction is the same as round 24 (15.5 MPKI)
while the guard itself (epoch load, TLS compare, jump, 31 B per site) costs 2.5% — the twin is 0.975x. Net 1.4% < v4's 2.9%. Dropped.

## Round 27 — self-hosted refinement v6 (LBR trace of cold8's twin → plan with frozen burst sizes and unshifted offsets; 366 sites, 2,756 targets), 3 reps, 01:07

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 57.08 | 1.000x | 18.23 | 0.616 | 1.000 |
| cold8 (plan v4, same binary as round 24) | 56.03 | 1.019x | 15.60 | 0.654 | 1.042 |
| cold10 (plan v6) | 56.43 | 1.011x | **14.39** | 0.690 | **1.106** |
| cold10_nop (twin) | 58.31 | 0.979x | 16.89 | 0.668 | 1.107 |

Lowest miss rate so far (−21%) and IPC +12%, but the refined plan executes 10.6% more instructions: the added sites fire many times
per request (the LBR-entry rate proxy under-estimates some functions), so the twin loses 2.1% and the net is +1.1%. Round-to-round
noise note: the same cold8 binary measured 1.029x in round 24 and 1.019x here (gs itself moved 55.98 → 57.08 G).
→ Round 32: measure executed prefetches per site directly (instruction sampling of cold8, `cold_site_profile.sh`) and drop sites whose
executions exceed 10× the misses they save (`--site-exec`).

## Round 28 — regular sequential-lookahead mode (seq D=1 KB, K=40) restricted to the 240 functions that miss (seqa, 644 sites), 3 reps, 01:29

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 58.04 | 1.000x | 18.19 | 0.610 | 1.000 |
| seqa | 57.45 | 1.010x | 17.78 | 0.616 | 0.999 |
| seqa_nop | 57.03 | 1.018x | 17.96 | 0.617 | 0.994 |

Noise (arm = twin, MPKI −2%): the misses in this service are not sequential streams inside functions, so the seq mode has nothing to mix in.
Drift note: gs has slowed from 55.6 G (round 19) to 58.0 G (round 28) over the night — the mixed load keeps appending posts, so timelines and
per-request work grow; only in-round comparisons (interleaved reps) are valid.

## Round 30 — wider plan v7 (64 lines per site, weight ≥ 2, up to 3 sites per line, lead window 20k cycles; 349 sites, 2,822 targets, 699 libc), 3 reps, 01:47

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 58.20 | 1.000x | 18.18 | 0.608 | 1.000 |
| cold8 (v4) | 57.21 | 1.017x | 15.62 | 0.646 | 1.043 |
| cold11 (v7) | 56.97 | 1.022x | 15.07 | 0.651 | 1.048 |
| cold11_nop | 58.97 | 0.987x | 17.38 | 0.630 | 1.050 |

Slightly more coverage (MPKI 15.1) for slightly more instructions; within noise of v4 (both 3.5% against their twins). The plan is
saturating on what LBR attribution can reach: libc misses whose 32-branch windows never leave libc get no site (10% of samples).
→ Round 34: "orphan burst" — those top lines prefetched once per request at TDispatchProcessor::process entry (N = 64 / 128).

## Round 31 — plan v4 with a longer minimum lead (200 cycles; cold12) and a single site per line (cold13), 3 reps, 02:05

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 58.37 | 1.000x | 18.31 | 0.609 | 1.000 |
| cold8 (v4) | 57.73 | 1.011x | 15.78 | 0.644 | 1.046 |
| cold12 (min lead 200) | 58.66 | 0.995x | 15.26 | 0.636 | 1.049 |
| cold13 (1 site per line) | 57.87 | 1.009x | 15.89 | 0.638 | 1.038 |

Neither variant beats v4: pushing sites further from the miss lowers MPKI a little but not cycles (the further sites are hotter), and
de-duplicating sites saves 0.8% instructions but loses the same in misses. Noisy round (gs rep 3 and cold8 rep 3 both ~59 G with 300 ms
p99 spikes). v4's in-round net over the night: 1.029 / 1.019 / 1.017 / 1.011x (mean +1.9%); against its twin consistently +3.5%.

## Round 32 — measured-overhead pruning v10 (instruction sampling of cold8: 2.97% of all instructions were prefetches, 40% of them in six thrift TVirtualProtocol/TVirtualTransport template instantiations; sites whose executions exceed 10× the misses they save dropped → 24 sites / 151 targets removed, 62% of the executed prefetch volume), 3 reps, 02:29

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 60.46 | 1.000x | 18.25 | 0.595 | 1.000 |
| cold8 (v4) | 59.08 | 1.023x | 15.90 | 0.638 | 1.049 |
| cold14 (v10) | 58.95 | **1.026x** | 15.88 | 0.624 | **1.022** |
| cold14_nop | 60.70 | 0.996x | 18.00 | 0.611 | 1.031 |

Same miss reduction and speed as v4 with half the instruction overhead (the twin is now free). The gain is limited by coverage, not cost:
the remaining misses are lines no site can claim (libc-internal windows) and lines prefetched too late. v10 is the base for the final
combination (round 35: + orphan burst if round 34 shows it helps).

## Round 33 (02:50) — INVALID: disk-full incident #2. The socialNetwork redis containers snapshot their datasets to disk every minute (default
`save 60 10000`); home-timeline-redis had grown to 33 GB (compose-post fan-out) and had written 951 GB since the stack came up. The snapshots
filled the root disk (twice: 1.6 GB, then 0 GB), broke the load generator (rps=0 / non-2xx rows) and are the likely source of the random
200–400 ms p99 spikes seen all night (a 33 GB fork + write every 60 s on the shared cores). Fix applied at 02:53: `CONFIG SET save ""` and
`appendonly no` on all socialnetwork redis containers, dump files removed (24 GB freed). The 5-rep confirmation is re-queued as round 36.
Also removed during the emergency: two *stopped* containers of another workflow (rbr-plot, rbr-design-sweep; 123 kB / 1.4 MB writable layers).

## Round 29b — wake burst (LD_PRELOAD, list regenerated for the fat-static layout: 1,030 lines over recv/poll/cond hooks) on top of plan v4 and on gs, 3 reps, 02:55 (first round after the redis snapshots were disabled: no p99 spikes anywhere)

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs | p99 ms |
|---|---:|---:|---:|---:|---:|---:|
| gs | 60.09 | 1.000x | 18.28 | 0.599 | 1.000 | 16.5 |
| cold8 (v4) | 58.08 | **1.035x** | 15.52 | 0.643 | 1.039 | 17.1 |
| cold8 + wake 32 lines | 59.35 | 1.013x | 15.73 | 0.631 | 1.041 | 19.1 |
| cold8 + wake 64 lines | 58.64 | 1.025x | 15.67 | 0.637 | 1.038 | 15.5 |
| gs + wake 32 lines | 60.30 | 0.996x | 18.28 | 0.599 | 1.003 | 19.0 |

The wake burst adds nothing on either base and costs 1–2% on top of the plan (the post-wake lines it fetches are already covered by the
plan's early sites, and the wrapper's rdtsc + burst on every long syscall return is pure overhead here). Dropped. With the redis
snapshot storm gone, cold8's in-round gain is 3.5% — the cleanest measurement of v4 so far.

## Round 34 — "orphan burst": the top 64 / 128 miss lines that no site could claim, prefetched once per request at TDispatchProcessor::process entry (cold15 / cold16), 3 reps, 03:05

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 61.21 | 1.000x | 18.10 | 0.592 | 1.000 |
| cold8 (v4) | 60.35 | 1.014x | 15.51 | 0.627 | 1.045 |
| cold15 (v4 + orphan 64) | 60.44 | 1.013x | 15.45 | 0.626 | 1.045 |
| cold16 (v4 + orphan 128) | 60.54 | 1.011x | 15.48 | 0.625 | 1.045 |
| cold15_nop | 61.33 | 0.998x | 17.72 | 0.615 | 1.041 |

No effect: the unattributable lines are needed before the dispatcher runs (socket read/parse) or by other threads, so one burst at
dispatch entry neither reduces misses (15.5 → 15.45) nor pays. Round 35 (combination) was skipped by rule: only the measured pruning
qualified, and it was already measured alone (round 32). Round 36 = 5-rep confirmation of v4 (cold8) vs gs and twin.

## Round 36 — 5-rep confirmation of plan v4 (cold8) vs the fat-static base and its twin, 03:45 (redis snapshots off; clean p99 except one gs outlier)

| arm | svc cycles (G, median of 5) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 61.46 | 1.000x | 18.13 | 0.592 | 1.000 |
| cold8 (plan v4) | 60.81 | **1.011x** (mean 1.012x; paired reps 1.001–1.029) | **15.68** | 0.623 | 1.041 |
| cold8_nop (twin) | 61.78 | 0.995x | 17.68 | 0.613 | 1.041 |

Definitive number for the trace-guided cold plan on user-timeline: **+1.1% net, +1.9% against the twin, −13.5% code misses.** The base
keeps slowing (gs 55.6 G at 23:00 → 61.5 G now: the write load grows the timelines and the per-request work, instructions +7%), which
dilutes the relative gain of a fixed miss reduction; the earlier in-round measurements (1.029x at 00:17, 1.035x at 02:55) were taken on
a lighter dataset. The 5% target was not reached with prefetching alone; the static link itself (gs vs the shared-library build) remains
the largest single win of the night (4–6%).

## Round 37 — re-attribution with the 21 hot sites (≥ 100 prefetch-instruction samples in cold8's profile) removed from the candidate set (v14, cold18; their lines move to colder sites instead of being dropped), 3 reps, 04:09

| arm | svc cycles (G) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 63.52 | 1.000x | 18.04 | 0.577 | 1.000 |
| cold14 (v10, pruned) | 61.47 | **1.033x** | 15.86 | 0.612 | 1.026 |
| cold18 (v14) | 62.00 | 1.025x | 15.45 | 0.620 | 1.050 |
| cold18_nop | 63.27 | 1.004x | 17.81 | 0.606 | 1.047 |

Re-attributing the hot sites' lines recovers a little coverage (15.45 MPKI) but the receiving sites are not free either (+5% instructions),
so v10 (drop the lines, keep the overhead at +2.6%) stays the best engineering point. v10 in-round: 1.026x (round 32), 1.033x here.

## Round 38 — 5-rep confirmation of the pruned plan v10 (cold14) vs the fat-static base and its twin, 04:30

| arm | svc cycles (G, median of 5) | vs gs | MPKI | IPC | instr vs gs |
|---|---:|---:|---:|---:|---:|
| gs | 63.50 | 1.000x | 18.13 | 0.578 | 1.000 |
| cold14 (plan v10) | 62.16 | **1.022x** (mean 1.032x; paired reps 1.014–1.047) | **15.84** | 0.606 | 1.026 |
| cold14_nop (twin) | 63.61 | 0.998x | 17.84 | 0.596 | 1.033 |

**Best confirmed configuration of the night: plan v10 = +2.2% (median) / +3.2% (mean) net over the fat-static base, +3.2% against its
twin, −12.6% code misses, +2.6% instructions.** Against the original shared-library build (g) the same binary is ~+6–8% (round 39 closes
that loop). The 5% goal against gs was not reached: the remaining misses have no static site ahead of them (libc-only branch windows,
post-wake socket path) and every attempt to reach them (wake burst, orphan burst, epoch gating, re-attribution) cost more than it saved.

## Round 39 — closing the loop: original clang-19 shared-library build (g) vs fat-static (gs) vs the best plan (cold14), 3 reps, 04:52

| arm | svc cycles (G) | vs g | MPKI | IPC | instr vs g |
|---|---:|---:|---:|---:|---:|
| g (shared libs) | 67.37 | 1.000x | 19.73 | 0.548 | 1.000 |
| gs (fat-static) | 64.65 | 1.042x | 18.27 | 0.574 | 1.005 |
| cold14 (fat-static + plan v10) | 62.99 | **1.070x** | **15.87** | 0.607 | 1.036 |

Against the build the service shipped with, the night's best binary is 7.0% faster (4.2% from the static link, 2.7% from the trace-guided
cold plan) with 20% fewer code misses. Platform restored at 05:05 (`MODE=restore`: powersave, 0.8–3.8 GHz, uncore defaults), containers
un-confined, disk cleaner stopped; both DeathStarBench stacks left running (redis snapshots disabled).
