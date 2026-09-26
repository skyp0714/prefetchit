# Instruction Prefetch Experiment Summary (2026-09-24 Snapshot)

## Executive summary

The successful cases currently fall into four categories: **A-1 succeeds on large generated code where execution order closely follows code layout**, **A-2 succeeds when the next code type can be inferred statically from a call or schema graph**, **A-3 succeeds when a future function address is readable before dispatch**, and **B succeeds by replaying the dynamic first-touch stream of a request path after it wakes on a shared core**. A high MPKI or FE-bound percentage alone was not sufficient.

Unless noted otherwise, `speedup` means `baseline time / candidate time`. FE-bound is the Top-down user-slot percentage, not the exact fraction of total execution time spent stalled. `n/a` means that a value from the same operating configuration was not found in the retained results.

## 1. Why workloads below 5 MPKI usually did not benefit

The interpretation that “headroom is too small relative to prefetch overhead” is correct, but it is not the only cause.

1. **There are few absolute misses available to eliminate.** At 1–4 MPKI, recoverable time becomes small once only a subset of misses can be predicted and only some of those misses are on the critical path. Address calculation, guards, extra loads, prefetch issue, and code-layout changes still execute every time. In practice, roughly 0.5–2% of instruction and layout overhead was enough to consume the gain of general policies.
2. **Frontend misses may not be the primary bottleneck.** Silo had 9 MPKI but was only 9% FE-bound and 75% backend-bound. Conversely, an FE-bound value of 30–45% includes branch resteers, ITLB effects, L1I effects, and other components that `prefetcht1` cannot necessarily fix.
3. **A miss reduction is not necessarily a reduction in critical stalls.** One Django policy reduced MPKI by 3.24% while increasing CPU cost by 2.48%. FleetBench A-3 reduced code misses by 3.35%, added 0.69% instructions, and slowed performance by 0.46%. The eliminated misses may already overlap other work, occur on wrong paths, or be covered by hints that arrive too early or too late.
4. **General LBR-based placement lacked both coverage and lead.** LBR exposes only the most recent 32 branches, so it cannot directly observe long lead intervals, and traversal stops at cross-DSO or unresolved segments. Existing NOP insertion sites were also sparse: despite tens of thousands of miss samples, the Rails and MySQL plans selected only 12–19 patches. These cases suffered from both short lead and a lack of usable sites.
5. **Complex control flow and distributed miss paths break static graphs.** Direct-call graphs do not reconstruct the real execution sequence across virtual calls, `std::function`, interpreter dispatch, shared libraries, and callbacks. The static MovieId B plan saw only about one seventh of the 4,540 dynamic first-touch lines and achieved only 1.006x.
6. **MPKI also has a denominator effect.** Extra retired instructions can make MPKI appear lower. Absolute misses per fixed unit of work and CPU/request must therefore be reported alongside MPKI.

“Low MPKI causes failure” is consequently a prioritization rule, not a physical threshold. CXXRTL at 2.95 MPKI gained 2.5%, and FeedSim at 3.60 MPKI gained 8.54%. These exceptions show that **high accuracy, coverage, and lead with low dynamic cost** can matter more than the baseline MPKI: CXXRTL has an unusually regular execution order, while FeedSim exposes accurate future targets early.

## 2. A-1: Sequential large-code access

| Workload / selected policy | Speedup vs base | L2 code MPKI | FE-bound | Dynamic instruction change | NOP/code-inflation performance loss |
|---|---:|---:|---:|---:|---:|
| Pure sequential 16 MB, D=8 KB/S=64 B | **3.56x** | 70.9 → 1.09 (**↓98.5%**) | n/a | Comparable increase: n/a | NOP ≈ base, about 1.00x |
| Verilator, seq D=4 KB/K=20 + burst4 | **1.149x** | 56.9 → 13.7 (**↓75.9%**) | 61.2% | **+6.7%** | NOP twin: 0.929x, or **about −7.1%** |
| Arcilator, D=4 KB/K=10 | **1.543x** | 79 → 35 (**↓55.7%**) | 87.1% | n/a | Derived from the base/twin ratios: **about −8.3%** |
| CXXRTL, D=4 KB/K=80 | **1.025x** | 2.95 → 0.94 (**↓68.1%**) | n/a | n/a | n/a; denser K=20 policy achieved only 0.968x |

The requested `69→12` does not correspond to one confirmed result row. The nearest real application result is Verilator at `56.9→13.7`; the pure stream microbenchmark measured `70.9→1.09` with D=8 KB/S=64 B.

The sequential policy succeeded because misses did not belong to a single branch target. They occurred continuously while execution traversed nearly every cache line in multi-megabyte function bodies. A `rip+D` hint can therefore pull in the next code line 4–8 KB ahead without target prediction or a profile.

Profile- and call-graph-based policies were weaker for the following reasons:

- The COND/CALL/RET label on a Verilator miss identifies only the last taken branch. The actual misses extend far into the following function body. Only 47% of CALL misses were on the callee's first line, and only 30% of RET misses were on the continuation line.
- RET and callee-entry policies cover only a few entry lines, not the stream through a very large function body. RET v3 reduced MPKI by only 1.7% even with accurate targets.
- Transferring generic depth-2 and depth-4 call-graph policies to Verilator produced 0.988x and 0.986x. Its largest function accounts for 32.7% of all defined-function bytes, making intra-function streaming much more important than entry prediction.

## 3. A-2: AsmDB-like static/call-graph analysis

| Workload | Policy | L2 code MPKI | FE-bound | Speedup vs base | Status |
|---|---|---:|---:|---:|---|
| ARM frontend large ipc3000 | Static direct-call graph, depth 4, one entry line | 59.55 → 45.44 (**↓23.7%**) | 89.8% | **1.09198x** | Success, synthetic ideal case |
| FleetBench Proto Arena seed 0 | Schema/type graph, grandchildren, at most 8 lines | 16.593 → 12.935 (**↓22.0%**) | 56.1% | **1.03484x** | Success |
| FleetBench Proto Arena seed 1 | Same policy, holdout seed | 16.572 → 12.914 (**↓22.1%**) | 56.1% | **1.03445x** | Success |
| FleetBench Proto NoArena | Same schema policy | n/a | n/a | **1.02181x** | Partial transfer |
| LLVM full reference mix | Sparse call512/call2048/wrapper bypass | 1.516 → n/a | 39.6% | 0.99998–1.00059x | Failure |
| Ceph RGW | Generic direct-callee g128/g512 | 5.91–8.94 → n/a | 49.3% | 1.00007x / 0.99869x | Failure; richer analysis in progress |
| Rails | Static + LBR-derived padding | 1.889 → n/a | 32.9% | n/a | Failure |
| MySQL | Static + LBR-derived padding | 4.243 → n/a | 38–39% | n/a | Failure |
| Django v2 | Static + corrected LBR placement | 1.784 → n/a | 44.1% | n/a | Failure |
| Silo | Static padding | 9.13 → n/a | 9.1% | n/a | Failure |
| Media services | Static graph/padding | 0.71–2.78 → n/a | 38.4–46.3% | n/a | Failure |

ARM succeeded because the large synthetic binary was almost entirely frontend-bound: 89.8% FE-bound versus 2.35% backend-bound. The next callee was statically known. Fetching one entry line at graph depth 4 created long lead while increasing text size by only 104 B. The default ipc1000 footprint showed no benefit versus its NOP control. ARM is therefore an ideal-case demonstration of the algorithm, not evidence of generalization to real services.

FleetBench benefited from information stronger than a general call graph: the **protobuf schema**. At a parent message's `Clear`, `Merge`, `ByteSize`, or `Serialize`, the policy can identify concrete field types and constructors exactly two levels below, exposing targets hidden behind generic runtime virtual calls. The selected policy added about 1.03% instructions, reduced speculative L2 code misses per fixed work by about 21.3%, and reduced I-cache stall cycles by 26.1%. It delivered 3.44–3.48% on both Arena seeds and retained 2.18% on NoArena, but it has not yet generalized beyond protobuf.

## 4. A-3: Future indirect-call/dispatch targets

Where available, “indirect-call share” means the association between L2-miss samples and recent LBR targets. It is neither a causal stall fraction nor a speedup upper bound. Indirect jumps are kept separate from indirect calls.

| Workload | L2 code MPKI | FE-bound | Indirect-call-target association within MPKI | What can be predicted? | Result |
|---|---:|---:|---:|---|---|
| FeedSim v2 | 3.598 → 2.988 (**↓17.0%**) | 39.4% | n/a | The upcoming feature-extractor functions in a request | **Staged 1.0854x** |
| FleetBench Proto | 16.9 → n/a | 56.1% | **13.3%** same-DSO vtable/function-pointer CALL; 15.9% including jumps | The method that will process the next protobuf message type | A-3: 0.9954x; A-2 schema: 1.0345x |
| Django | 2.4 → n/a, earlier screen | n/a | 5.4% indirect CALL; 13.2% computed-goto jump separately | The interpreter handler for the next bytecode | Not tested directly; general policy failed |
| MovieId alone | 4.9 → n/a, earlier screen | n/a | 8.2% same-DSO indirect CALL; 10.4% cross-DSO separately | The handler for the decoded RPC method | Current normal point is 1.04 MPKI; A-3 screen failed |
| ComposePost / UserTimeline alone | 1.0 / 1.1 → n/a | n/a | 8.8% / 3.4% same-DSO indirect CALL | The next RPC handler or callback | New A-3 performance: n/a |
| Scylla (co-located with MySQL) | 12.286 → 11.857 (**↓3.5%**) | 54–56% | n/a | The next task that the scheduler is likely to run | 1.0008x, not significant |
| MySQL durable | 4.28 → n/a | 39.1% | n/a | The storage-engine method selected for the request | 0.9984x screen |
| Ceph RGW | 7.62 → n/a, diagnostic point | 49.3% | **8.88% same-line**; 10.89% within target +256 B | The next authentication, storage, or completion step of the request | In progress; one `execute` target covers less than 0.2% |

FeedSim executes a **real full DCPerf v2 application path**. It retains DLRM, RPC, TLS, ZSTD, feature/story work, and simulated outbound I/O, and it passed the normal 40-QPS SLA and error gates. It is not an extracted toy dispatch loop. However, an immutable array of 104,850 generated function addresses with thread-local consecutive range reservation is much easier to prefetch than arbitrary RPC or server indirect calls. It is therefore a valid success on a realistic workload, but it should not be generalized as representative of all indirect-call structures.

FleetBench A-3 failed because repeated protobuf elements often share a concrete type, causing repeated hints to the same already-hot target. The future-vptr load and guard cost was too high relative to new cold-line coverage. The successful schema-based A-2 policy instead deduplicated concrete child types and chose deeper descendants with longer lead.

Scylla's 97.22% prediction accuracy appears strong, but dispatch coverage was only 31.84%, and live queue coverage was about 44%. MPKI fell 3.49%, yet misses per fixed operation fell only 2.45% while instructions rose 1.08%, leaving no performance gain. Accurate target prediction and useful cold-miss coverage are separate requirements.

The Scylla row reports **Scylla's per-process MPKI while MySQL shares the same four cores**; it is not a combined Scylla+MySQL MPKI. The A-2 MySQL value (4.243 MPKI) was measured for MySQL alone on exclusive cores, so the two numbers are not directly comparable.

## 5. B: Context-switch/interleaving misses

The interpretation that “B has no results yet” is not correct for the retained results. **The kernel switch-in prefetch method, B-3, has no result**, but the in-process trace-guided wake-stream has a confirmed MovieId result.

| Workload / regime | Cores | CPU utilization | Context-switch observation | MPKI: alone → interleaved → PF | Speedup | Status |
|---|---:|---:|---|---|---:|---|
| Media MovieId, R=600 | Shared pool of 8 | n/a | **12.7 runs/request** in the PT trace; about **17k context switches/s**, mostly blocking wakes; three `std::async` workers created per request | about 3.25 → **86.6 → 76.9** | **1.054x** | B in-process success, five repetitions |
| Scylla 20k + MySQL 400 TPS | 4 shared cores | **44–45%** for Scylla | Task-queue dispatch; high MPKI appears only under sharing | 0.40 → **12.29 → 11.86** | 1.0008x | B regime, A-3 failure |
| MySQL with Scylla | 4 shared cores | about 21% in earlier characterization | Another service evicts code between requests | 2.35 → 9.25 → n/a | n/a | Profile only |
| Rails with Scylla | 4 shared cores | about 39% in earlier characterization | Same mechanism | 1.91 → 3.48 → n/a | n/a | Profile only |
| ComposeReview / ComposePost | Pool of 8 or 16 | n/a | Neighbor services evict code between requests | 3.8→38 / 1.0→42–44 | n/a | Profile only |

MovieId's B misses are not primarily kernel-code misses caused directly by the context-switch instruction. They occur because another service runs on the same core while the thread is switched out, evicting the thread's user-code working set and branch state from L2/BTB. The thread then resumes cold. Similar MPKI at pool sizes 8 and 16 shows that sharing a core with different code matters more than the pool size itself.

MovieId incurred about 10.4k L2I misses per request, but only about 4.54k lines were first-touched by the executed code in each run. At least 5.9k remaining misses are attributed to wrong-path and fall-through fetches caused by a cold BTB/BPU. Wake-stream covered about 42% of executed first-touch lines, reducing MPKI from 86.6 to 76.9 and improving performance by 5.4%. BTB resteers, 27% backend-bound slots, and about 10% ITLB-walk cost remained. This explains why in-process `prefetcht1` policies saturated near 1.05x.

The following results are still unavailable:

- B-3 kernel module that prefetches a task's working set before switch-in: **n/a**
- Generalization of the MovieId wake-stream to ComposeReview or ComposePost: **n/a**
- Final speedup from an affinity/scheduling sweep over different amounts of core sharing: **n/a**

## 6. Is the proposed classification correct?

It is mostly correct, with the following refinements:

- **A-1 = sequential large-code access:** Correct. More precisely, it is an intra-function stream in generated or flattened code where layout order closely matches execution order.
- **A-2 = AsmDB-like call-graph-based analysis:** Mostly correct. The successful FleetBench policy used a protobuf **schema/type graph**, not a general call graph; ARM was a direct-call-graph ideal case. Profile/LBR-based AsmDB-like placement is a separate variant and has not succeeded generally.
- **A-3 = indirect call:** Directionally correct but too broad. The precise category is an **indirect dispatch whose future target address can be obtained with sufficient lead**. A high indirect-call count alone is insufficient.
- **B = context-switch misses:** Correct. More precisely, interleaving on the same core evicts user instruction working sets and branch state while a task is switched out, producing misses after switch-in. C6 wake misses were removed through the operating configuration and are not included in B.

The main interpretation is: **success depends on the product of (1) the solvable share of misses, (2) target accuracy, (3) sufficient lead, (4) dynamic-instruction and code-inflation cost, and (5) whether the miss is actually on the critical path—not on MPKI alone.**

## Source documents

- A-1: `README.md` §2-1 and `icache_microbenchmark/microbench/seq_stream/README.md`
- A-2: `docs/class_a_generalization_20260922.md`, `docs/class_a_proto_lead_20260922.md`, and `docs/class_a2_campaign_20260923.md`
- A-3: `docs/class_a3_campaign_20260923.md`, `docs/class_a3_dispatch_20260924.md`, and `docs/class_a_search_20260924b.md`
- B: `docs/prefetch_plan_classB_wakestream.md` and `docs/prefetch_plan_by_miss_class.md`
- Latest consolidated check: `docs/class_a_overnight_20260924.md`
