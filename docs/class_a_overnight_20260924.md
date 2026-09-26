# Class A: eight-hour follow-up, 2026-09-24

The run covers the user-authorized interval beginning 07:33 UTC (02:33 CDT),
with the report finalized by 15:33 UTC (10:33 CDT). The new independently
confirmed result is **FeedSim v2 staged entry12/body4: +8.541% CPU efficiency
[95% CI +8.143, +8.941] versus original**, and **+2.090% [+1.861, +2.319]
versus prior lead4**. The goal of a significant ≥1% improvement on every Class A
workload has **not** been achieved. Existing A-1 wins are reproduced references,
not discoveries from this follow-up.

## Results and scope

Efficiency means `baseline CPU/work ÷ candidate CPU/work − 1`.
+8.541% efficiency is approximately **7.87% lower leaf CPU/request**, not a
measured increase in maximum throughput or whole-system efficiency. Bracketed
intervals below use paired log ratios and t95% over **five fresh pairs**, with
screening samples excluded. Two-round screens are selection observations.

| Class / workload | Result from this follow-up | Decision / scope |
|---|---|---|
| A-1 Arcilator | Existing ASM ≈2.33× original in the first screen; new instruction-lead/spacing/tail alternatives fail to beat it. T2 versus T1: **−0.957% [−1.260, −0.654]** in fresh confirmation | Keep existing T1. 20,000-cycle simulator driver, no completed RISC-V payload claim |
| A-1 Verilator | Existing ASM +8.58% vs original in first screen. New lead/tail variants fail; cache T0 −0.018%, T2 +0.280% vs T1 (screens) | Keep existing ASM. Fixed 100,000-cycle qsort prefix, expected timeout; not full qsort completion |
| A-2 FleetBench protobuf | Existing schema G +3.31%; best new rare-budget pruning +2.41% vs original, −0.87% vs G (screen) | Keep prior schema policy |
| A-2 LLVM full reference mix | call512 −0.0018%, call2048 −0.0148%, small-wrapper bypass +0.0589% | No promoted candidate; both standard ref inputs, unchanged flags, all SHA-512 outputs valid |
| A-3 FeedSim v2 | **Staged +8.541% [8.143, 8.941]** vs original; **+2.090% [1.861, 2.319]** vs old lead4; **+8.332% [7.843, 8.823]** vs own NOP | New confirmed improvement, full application at normal 40 QPS |
| A-3 Scylla offline successors | Uniform8 −0.203% vs original / −0.331% vs NOP. Frequency-selected8 +0.529% / +0.408% (screens) | Neither passes all selection controls; no confirmed ≥1% gain |

Scylla is A-3 by method and a **B miss regime**: its high MPKI appears when
sharing four physical cores with a real MySQL workload. It is not presented as
an intrinsically high-MPKI single-tenant Class A workload.

## Additional completed comparisons

Arcilator NTA screen: vs base -61.068%, vs reference -83.166%, vs nop -57.976%. Same placement/layout; the NTA policy has a separate 20k-cycle full-state check.

### Scylla guarded live callback resolution

screen (separate samples):

| Comparison | CPU-efficiency effect |
|---|---:|
| callback1 vs base | +0.597% |
| callback1 vs queue1 | +0.997% |
| callback1 vs callback1.nop | +0.226% |
| callback3 vs base | -0.279% |
| callback3 vs queue1 | +0.117% |
| callback3 vs callback3.nop | +0.033% |

### FeedSim static-work lookahead4096

screen (separate samples):

| Comparison | CPU-efficiency effect |
|---|---:|
| staged vs base | +9.006% |
| staged vs future | +3.069% |
| work4096 vs base | +8.425% |
| work4096 vs future | +2.520% |
| work4096 vs staged | -0.532% |
| work4096 vs work4096_nop | +8.467% |

### MySQL static InnoDB hints

screen (separate samples):

| Comparison | CPU-efficiency effect |
|---|---:|
| body | -0.197% |
| entry | +0.223% |
| staged | -0.098% |

### FeedSim staged + static graph

screen (separate samples):

| Comparison | CPU-efficiency effect |
|---|---:|
| F (staged) vs original | +8.254% |
| G (graph) vs original | -0.349% |
| F+G vs original | +8.225% |
| F+G vs separate staged binary | -0.027% |
| F+G vs same-layout NOP | +8.253% |
| Added G, same layout | +0.031% |
| Added F, same layout | +8.105% |
| F only, same layout | +8.220% |
| G only, same layout | +0.137% |

Scylla's separate diagnostic resolved actual callbacks on
**10.050% of dispatches**, or
**22.358% of queue hints**.
The pinned wrapper sequence calls the pointer at `task − 16`. A collision-free
static table holds 24 observed, byte-verified wrapper addresses; full 64-bit
relative-address equality guards the object-prefix load. Unknown wrappers retain
the ordinary queue target. Actual callback addresses may cross DSO boundaries;
this run does not establish DSO-specific gains. Normal binaries contain no model
updates or diagnostic counters. This is a profile-bounded static recognition
prototype with live pointer resolution, not an automatic arbitrary-C++ pass.
One/three cache-line variants retain identical computation in their NOP twins.
The three-line variant expands both resolved callbacks and fallback queue entries;
it is not an isolated callback-body expansion. Unlike FeedSim's size-checked
functions, arbitrary Scylla callback lengths are unknown here, so +64/+128 may
refer to adjacent code rather than the target's own body.
Coverage is not a measurement of cold misses, next-task precision, or fetch lead.
The complete screen gives callback1 +0.597% vs original but only +0.226% vs
its NOP; callback3 is −0.279% vs original / +0.033% vs NOP. Neither qualifies.
For callback3, misses/operation fall 1242.68→1192.74 versus original, but the
same-layout NOP is already 1201.79. Its hint-specific miss reduction is only
about 0.75% versus that control, with no useful CPU gain. For callback1, misses
are slightly higher than its NOP. These two-round counters do not establish
causal stall attribution or a statistically confirmed improvement.
The separate diagnostic exposes only 15.76 queued-target hint issues and 3.52
resolved-callback issues per operation, versus about 1,243 demand code misses
per operation in the normal baseline. Projecting three lines per queue decision
is about 47 issued lines/operation, before accounting for repeated/hot targets.
This is an issuance-budget comparison, **not a rigorous miss-reduction upper
bound** or a measurement from callback3; it helps distinguish narrow entry
coverage from simply insufficient prediction accuracy (`callback_hint_budget.json`).

The static-work policy uses original generated function sizes to select one
immutable future pointer per unchanged shuffled-array index, with 2–16-call
bounds and three hinted lines. This mapping can skip/repeat targets; it is not
only a change of lead time. The 4096-byte budget is measured if shown above;
16384-byte source/sanitizer support is **not** claimed as a timing result.
`work_mapping_analysis.json` records exact seed122 startup geometry where built,
not runtime cold-line coverage. For budget4096, 104,850 positions map to 95,457 unique targets (91.04%); most look two calls ahead, and mean intervening static code size is 9,068 bytes. This is not measured cycle lead. Suites are per-thread instances in this workload.

The graph composition uses the existing static depth2 graph from **seven
extractor translation units**, not a complete program-wide C++ graph. Exact
same-layout controls remove graph hints, future hints, or both. The table exposes
total and incremental effects; a combined improvement over original alone does
not establish benefit from adding G to F.

## Baseline MPKI and top-down breakdown

| Baseline / class | L2 code MPKI | Retiring | Bad spec | FE-bound | BE-bound | Setting |
|---|---:|---:|---:|---:|---:|---|
| A-1 Arcilator | 79.289 | 11.76% | 0.39% | 87.06% | 0.78% | 20k-cycle driver; no loaded RISC-V payload |
| A-1 Verilator | 57.237 | not collected | not collected | not collected | not collected | 100k-cycle qsort prefix |
| A-2 protobuf | 16.525 | not collected | not collected | not collected | not collected | ProtoArena,100iterations,seed0 |
| A-2 LLVM | 1.516 | not collected | not collected | not collected | not collected | Full two-input reference mix; count-weighted aggregate |
| A-3 FeedSim | 3.598 | 36.72% | 9.95% | 39.44% | 14.25% | Full v2,40QPS |
| A-3 Scylla / B regime | 12.527 | 15.74% | 5.96% | 54.02% | 25.64% | YCSB20kops/s + MySQL400TPS shared4cores |
| A-2 MySQL | 4.287 | 33.74% | 6.60% | 39.36% | 21.35% | Standalone durable OLTP400TPS |

Ratios use summed raw counters within each named phase. Missing top-down is not zero. Full phase identifiers are in `baseline_table.json`; no counter values are borrowed from a different operating setting.

## FeedSim attribution and PMU evidence

Five fresh confirmation rounds, arithmetic means:

| Policy | Leaf CPU ms/request | L2 code MPKI | L2 misses/request | FE-bound | BE-bound |
|---|---:|---:|---:|---:|---:|
| Original | 171.898 | 3.598 | 2.587 M | 39.44% | 14.25% |
| Prior lead4 | 161.682 | 3.405 | 2.453 M | 33.48% | 16.79% |
| Staged entry12/body4 | 158.372 | 2.988 | 2.154 M | 29.00% | 19.25% |

Staged reduces misses/request about 12.2% vs lead4 with instructions within 0.1%.
Frontend slots/request decline from 610 M to 516 M, while backend slots/request
rise from 306 M to 343 M. These fractions cannot quantify overlapped stalls.

The separate seven-arm component screen gives entry-only +6.328% and body-only
+6.217% vs original, both about 2.2–2.3% behind staged. Redirecting only staged's
far-entry hint to the near target, while retaining its address work and all three
hint instructions, gives **+0.201% vs staged**, below the promotion threshold.
Thus wider entry/body coverage has stronger evidence than a claim that 12-call
entry lead is uniquely optimal. The prologue-hoisting candidate fails incremental
attribution: +6.181% original, +0.089% prior lead4, −0.121% against the control
removing only its new prologue hints. It is not promoted.

Separate two-round stall diagnostic (millions of event counts/request):

| Event | Original | Lead4 | Staged | Staged change vs lead4 |
|---|---:|---:|---:|---:|
| ICACHE_DATA_STALL | 37.759 | 36.089 | 28.573 | -20.83% |
| STALL_L1D_MISS | 40.530 | 33.828 | 30.088 | -11.05% |
| ITLB_WALK_ACTIVE | 18.921 | 5.433 | 5.439 | +0.12% |
| BACLEAR | 0.708 | 0.724 | 0.713 | -1.55% |

These counters have different event definitions and can overlap. The final column is an event-count change, not CPU speedup.

Additional stall/latency diagnostics, when present in `diagnostic_mechanisms.json`,
are separate two-round observations. I-cache/data/ITLB stall categories overlap;
they are not added or subtracted as disjoint costs. FE_LATENCY_GE_64 counts
qualifying retired events, not cycles; BACLEAR is unknown-branch resteering,
not all BTB misses. TSC observation gaps are not actual fetch lead or core cycles.

Translation-specific diagnostic: **2 separate pair(s)**, staged versus its byte-verified same-layout NOP. This is an attribution observation, not a fresh performance confirmation.

| Event / request | Same-layout NOP | Staged | Change |
|---|---:|---:|---:|
| ITLB_WALK_ACTIVE | 19,048,276 | 5,314,455 | -72.10% |
| ITLB_WALK_COMPLETED | 218,437 | 115,498 | -47.13% |
| ITLB_STLB_HIT | 488,275 | 642,820 | +31.63% |
| DTLB_LOAD_WALK_COMPLETED | 192,046 | 288,865 | +50.41% |

Intel defines WALK_ACTIVE as active instruction-walk cycles, WALK_COMPLETED as walks completed after misses in all TLB levels, and ITLB_STLB_HIT as first-level instruction-TLB misses hitting the shared TLB. The DTLB row counts demand data-load walks, not software-prefetch walks. These counters do not directly measure every L1 instruction-TLB miss or establish the internal mechanism. A change against the NOP control is evidence beyond code placement, but cannot establish general elimination of iTLB or BTB misses. [Intel Granite Rapids event definitions](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

The four restricted programmable events were collected together without multiplexing; core cycles/instructions use fixed counters. The short diagnostic remains separate from the five-pair CPU confirmation. The observed reduction in instruction-translation walk cost qualifies the earlier blanket assumption that data prefetch cannot help any iTLB-related stall; direct L1 instruction-TLB filling, shared-TLB warming as the specific cause, and BTB training remain unproven.

Scylla uniform8 held-out accuracy is 99.9766% but emission coverage only 4.1109%.
Frequency-selected8 increases emission coverage to 6.3941% while accuracy falls
to 83.3434%. Queue emission is ≈45% and next-wrapper agreement ≈58%.
Uniform8 reduces absolute misses/operation only 1.35% while adding 1.08%
instructions; weighted8 reduces misses 2.71% while adding 0.61% instructions.
High prediction accuracy and lower MPKI do not alone imply useful miss coverage.

Verilator reproduces the same caution: prior IR reduces absolute misses 76.44%
but adds 6.79% instructions; prior ASM reduces misses 63.36% and adds 2.98%.
CPU times are 73.21s and 72.43s versus 78.64s original in the first screen.

## Operating conditions, controls and validation

- FeedSim full v2: unchanged DLRM/RPC/TLS/ZSTD work, 40 QPS, eight leaf cores.
  All accepted runs require ≥39.2 QPS, p95 ≤700 ms, zero driver errors and
  ≥15% utilization. CPU denominator is 25s × achieved QPS, as in the prior harness.
- Scylla 6.2.3: YCSB workloada read/update50/50, 1 M records, eight clients,
  20k ops/s; durable MySQL 16 × 200k rows, 16 clients, 400 TPS on shared cores.
  Each arm starts from a fresh private Scylla data clone. Matched operation/TPS
  windows and successful READ/UPDATE counts are checked.
- MySQL standalone comparison retains the same normal durable 400 TPS setting.
  Static hints replace existing NOPs; their reversal is byte-identical to original.
  Loaded executable hashes are checked. No kernel modifications were made.
- CPU affinity, fixed 2 GHz/HWP controls, turbo/C6 and uncore settings follow the
  saved protocol. Every platform context is restored. Builds/heavy analysis are
  serialized outside measurements; controllers use separate cores84–85.
- New candidates need >0.5% over required controls before fresh five-pair
  confirmation. Time-limited screens remain screens. Exact NOP twins retain
  address computation/control flow; they isolate hints, not all insertion costs.
- Arcilator state bytes match at 200/2000 cycles across earlier variants;
  final base/ASM/T0/T2 comparisons check all 1,199,438 bytes at 20,000 cycles.
  Execution tests cover PIE relocation, wrapping/empty queues, diagnostic ownership,
  unknown-address hash collisions with an inaccessible object prefix, unchanged
  call order, and sanitizer-checked FeedSim work mappings.

Two incomplete performance attempts are explicitly excluded: a FeedSim listener
shutdown/startup collision and a Scylla co-tenant interruption during filesystem
space exhaustion. No partial rows from either enter accepted effects. The latter
original MySQL stderr was unavailable, so a specific server ENOSPC error is not
claimed. SQL binlog rotation/purge on the private benchmark MySQL volume freed
6.01 GB; table counts/durable settings were checked unchanged. Original service
containers stayed stopped and original volumes were preserved.

LLVM's empty process-exit perf footer is handled by a strict terminal-only parser:
all actual intervals must be numeric and fully scheduled. The resumed round keeps
its original random order; no rows were dropped or resampled. Missing Python wall
timers are marked null; perf elapsed time and CPU costs remain available. All
252 unique selected wrapper entries (555 sites) passed bounded reinspection.

## What to carry forward

Keep FeedSim's confirmed staged policy and the prior A-1/schema policies.
For future compiler work, separate (1) safe early target availability,
(2) dynamic cold-code coverage, (3) body footprint, (4) lead and hint overhead.
The array and owner-thread queue examples provide concrete transformation sites,
but neither proves general safe pointer hoisting across arbitrary C++ effects.
High-MPKI service work should next target measured cold bodies with bounded
static recognition and held-out footprint evidence, not accuracy alone.
Two concrete untested follow-ups remain: remove the redundant far-pointer load
from the near3 source policy, and expand only guarded, size-validated Scylla
callback bodies while preserving one-line fallback hints. Neither was timed.

Reusable implementation changes include [FeedSim policies](../llvm_prefetchit/scripts/static/feedsim_future_policy.py),
[static-work target preparation](../llvm_prefetchit/scripts/static/feedsim_work_policy.py),
[Scylla callback recognition](../llvm_prefetchit/scripts/static/build_scylla_callback_targets.py),
[offline successor rules](../llvm_prefetchit/scripts/static/build_scylla_offline_rules.py),
[MySQL static engine targets](../llvm_prefetchit/scripts/static/build_mysql_static_engine.py),
and [cache-hint retuning](../llvm_prefetchit/tools/retune_prefetch_hint.py).
Their campaign commands, exact controls and execution-test logs accompany the evidence.

[Hierarchical Prefetching, ASPLOS 2025](https://ease-lab.github.io/ease_website/pubs/HP_ASPLOS25.pdf)
motivates footprints beyond entries; its hardware results are not native T1 gains.
[Call-chain software instruction prefetching](https://research.ibm.com/publications/call-chain-software-instruction-prefetching-in-j2ee-server-applications)
motivates entry/timing separation.
[Indirect-memory software prefetching, CGO 2017](https://www.research.ed.ac.uk/en/publications/software-prefetching-for-indirect-memory-accesses/)
informs target-address preparation.
[DEER](https://arxiv.org/abs/2504.20387) uses profile-guided lookahead with hardware
support, and [IP-CaT](https://arxiv.org/abs/2605.12433) considers translation/cache
management; neither is evidence that changing a data-prefetch mnemonic fixes
BTB/iTLB misses. Further qualifications are in `literature_notes.md`.

## Reproducible evidence and cleanup

The [published analysis](../llvm_prefetchit/migration/evidence/class_a_overnight_20260924/analysis.json)
and mechanism/PMU summaries retain the results and negative takeaways. Full trial
records, build/control hashes, commands and restoration audits remain in the local
archive. The [publication inventory](../llvm_prefetchit/migration/evidence/README.md)
identifies the smaller Git subset. Machine-specific prerequisites and original
benchmark inputs are required for rebuilding. Cleanup is confined to this campaign's own files.
