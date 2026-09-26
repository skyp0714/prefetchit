# A-3 expansion: future dispatch addresses and gated prediction

**Completed: no new statistically confirmed application gain.** RPC and MySQL
live-target screens did not qualify; Scylla's frozen aggressive predictor confirmed
at **+0.08% vs original (95% CI −0.84 to +1.01%)**, and **+0.19% vs exact NOP
(−1.51 to +1.92%)** across five fresh paired rounds. The ≥1% goal, particularly
3–5%, is not achieved in this expansion. Earlier FeedSim and schema-graph wins
remain separate evidence.

This campaign labels the **method** A-3: an early load of a runtime callee, or an
explicitly measured predictor when reachable future depth/lead is inadequate.
Miss regime remains a separate field. In particular, Scylla's high-MPKI result
is an interleaving result, not newly discovered standalone code-capacity pressure.

## Candidate catalog

| Candidate | Regime and prior qualification | A-3 dispatch opportunity | Test status |
|---|---|---|---|
| DSB Media ComposeReview / MovieId | Production info logging, 2,500 requests/s; prior user L2 code MPKI approximately 2.8 / 1.4 | Live Thrift iface virtual handler before argument decoding | Early / immediate-before-call / exact NOP source builds; full stack, normal requests |
| MySQL 8 | Durable OLTP, 16 tables × 200k records, 16 clients, 400 TPS; prior MPKI 4.24 | Live storage-engine vtable target at handler wrapper entry | Package-specific hooks; account for compiler devirtualization |
| Scylla 6.2.3 / Seastar | Alone approximately 0.4; previously 6.05 with MySQL on the same four cores | Task queue contains live future objects; `run_and_dispose` vtable slot | Read queue targets; independently measure queue availability/order/lead before prediction |
| VPP / CSIT candidate | New AF_PACKET IPv4 forwarding: 0.007 MPKI at 100Mb/s, no packet loss; 0.058 at 1Gb/s with 0.53% loss | Pending node/frame dispatch | Below threshold in these settings; this is not a CSIT/DPDK result |
| Envoy | Legacy reverse proxy at 55kRPS: approximately 0.24 MPKI, **all-mode counters** | Event/callback dispatch candidate | No newly qualified high user-MPKI point; no new optimization trial |
| DSB social RPC | RPC-family candidate, no new qualified point in this campaign | Same generated Thrift dispatch pattern | Media is the measured RPC implementation; no social gain claimed |
| FeedSim full v2 | Earlier independently confirmed A-3 | Immutable function-pointer array lookahead | Prior reference: +6.13% CPU efficiency; not a new result here |
| FleetBench protobuf | Earlier A-3 attempt negative | Live future MessageLite method targets | Prior reference: −0.46%; static schema graph remains +3.45% |

Candidate classification does not assert that every candidate has high MPKI, a
working optimization, or a measured speedup. Neither source prototypes nor pinned
binary hooks establish a general compiler pass for arbitrary C++ call graphs.

## Prospective protocol

Raw working root: `llvm_prefetchit/results/class_a3_dispatch_20260924/`.
`PROTOCOL.md` was written before screening. Prefer utilization ≥15% and user L2
code MPKI ≥1 at normal load. Do not inflate code/data footprints or remove work.
Fixed 2 GHz cores, fixed uncore, turbo/C6 off, restoration recorded. Benchmarks,
builds and heavy analysis are serialized. Instrumented probes are diagnostics,
not speedup observations. A screen >0.5% against original and exact NOP qualifies
for fresh randomized five-pair confirmation; retain negative arms and uncertainty.

At fixed arrival rate the primary gain is **CPU efficiency for completed work**,
not measured throughput capacity. For RPC use cgroup user+kernel CPU/request;
user cycles alone cannot establish whole-service improvement.

## RPC lead diagnosis

Separate sampled diagnostic at the normal 2,500 requests/s setting: each generated
processor hints the live handler before decoding arguments; every 64th call records
entry-to-handler TSC ticks. Startup/warmup are removed by counter differencing.
Each active method has approximately 1,220 samples. Most samples lie between
1,024 and 4,096 invariant-TSC ticks; none are below 512. Movie UploadMovieId mean
is approximately 1,854 ticks. Probe overhead remains in these diagnostics, and TSC
ticks are not asserted to equal core cycles.

This does **not** justify an aggressive predictor on a short-lead argument.
Additional depth must be justified separately. A FE64/LBR profile was collected
only in the diagnostic trial; it is not a performance trial or a causal stall
attribution. Branch stacks are bounded histories, not complete call stacks.

## Implementation constraints

RPC resolves virtual member pointers from an existing live shared iface using the
x86-64 Itanium C++ ABI. The future method is never executed to obtain its address.
The diagnostic build passes the same output/order checks with ASan and UBSan.

The restricted ELF hooker appends RX code and optional RW state without moving
original allocated sections. It checks input/site fingerprints and whole stolen
instructions, refuses PC-relative/control-flow relocation, preserves CET landing
pads, and produces an exact NOP twin only for inserted hints. Each site's scratch
registers and object lifetime require an explicit ABI review. The original GNU
build ID remains; SHA256 and loaded maps, not build ID alone, identify variants.

Seastar queue lookahead reads the queue owned by the current reactor. The next
queued object is live, but an urgent task inserted by current work can change
which task runs next. Availability, next-target agreement and lead must therefore
be measured; a live queued address is not an unconditional execution prediction.

MySQL's compiler already devirtualizes some engine operations. For index_read_map,
the early resolver follows the default-wrapper test and reads inner index_read
only on that path. Prefetching an inlined-away wrapper would not warm the actual
callee. These hooks are for the inspected package and durable InnoDB workload.

## Relation to prior work

[Call-chain Software Instruction Prefetching in J2EE Server Applications](https://sites.cs.ucsb.edu/~ckrintz/papers/nagpurkar_pact07.pdf)
explains why hoisting beyond the immediate caller can improve lead while losing
accuracy when hoisted too far. This motivates measuring lead before extending
prediction depth. [The Entangling Instruction Prefetcher](https://webs.um.es/aros/papers/pdfs/aros-ipc20.pdf)
separately emphasizes timeliness, coverage and accuracy; its hardware mechanism
and reported gains are not evidence that this software prototype will improve.
[CGPoPE](https://os.itec.kit.edu/97_3406.php) uses recorded call relationships and
binary-inserted hints. Our live queued target and any online transition predictor
must be reported separately from a profile-derived static call graph.

## RPC and MySQL selection results

One independent-build screen per arm, **not confirmed speedups**. Each RPC arm
uses fresh stack/data and one service change. No policy passes the prospective
+0.5% threshold against both original and exact NOP.

| Workload / policy | CPU efficiency vs original | vs exact NOP |
|---|---:|---:|
| ComposeReview early handler | −0.29% | +0.24% |
| ComposeReview immediately before handler | −1.02% | −0.64% |
| MovieId early handler | +0.25% | −0.34% |
| MovieId immediately before handler | +0.87% | −0.11% |
| MySQL live engine targets | −0.16% | +0.88% |

MySQL's address lookup / hook control itself costs approximately 1% relative to
original in this screen. A hint-only benefit against that control does not imply
a net application gain. RPC baseline user L2 code MPKI is 2.33 (ComposeReview)
and 1.04 (MovieId); MySQL is 4.28. Retain the single-trial uncertainty rather than
interpreting these screens as proof of exactly zero possible improvement.

The RPC FE64 diagnostic contains 97,368 samples. Residual handler-entry-line
samples are a small part of this **already-prefetched, instrumented** stream;
most samples are elsewhere, including serialization, tracing and shared libraries.
This is not a baseline coverage ceiling or evidence that every residual miss can
be predicted earlier. The recorded profile reports nine out-of-order events.

## Scylla prediction gate and diagnostic

At YCSB 20k ops/s plus durable MySQL 400 TPS on four shared cores, the unmodified
Scylla recheck has **12.48 user L2 code MPKI**, 44.2% aggregate CPU utilization,
and approximately 56.9% user FE-bound slots. This remains an **interleaved**
operating point. Standalone Scylla's historical approximately 0.4 MPKI result does
not change classification merely because an A-3 method is tested.

The separate queue diagnostic observes 17,562,964 dispatches: next-queued address
available 45.22%, depth 2 available 22.65%, depth 4 available 5.31%; no owner-slot
collisions. The hinted queue target equals the immediately next dispatched target
58.09% of the time (urgent insertions/scheduling can intervene). Matched lead
averages 2,440 TSC ticks. This opens the **insufficient readable future depth** gate,
not the short-lead gate. Live queued targets may still run later when not next.

The conditional aggressive mode uses a per-reactor tagged 256-entry last-successor
table. It trains from actual dispatched code addresses, requires two matching
transitions, skips self-target predictions, and predicts only when no next task is
queued. No predicted object is dereferenced and no future function is executed.
An owner hash collision falls back to queue lookahead; it cannot change work.

An independent diagnostic sees 17,688,878 dispatches and 6,029,094 emitted/resolved
predictions: **93.06% next-target accuracy**, **34.08% of all dispatches receive an
extra prediction**, mean matched lead 4,095 TSC ticks, zero owner collisions. This
establishes predictability in this scheduler; it is **not a performance result**.
Timing uses separate builds without diagnostic counters/TSC reads. One- and
four-cache-line variants distinguish entry-only coverage from a larger code span;
four lines do not mean four predicted functions.

The first queue diagnostic's harness initially rejected a 454 TPS single second
from the valid randomized 400 TPS co-tenant. Its workload completed with no errors;
the erroneous per-second validator is retained in the failure log. Before timing,
validation was corrected to the matched 25-second average, positive progress in
all intervals, and zero errors. Subsequent trials record the co-tenant's matched
report boundaries. This diagnostic is never used as a speedup observation.

## Baseline counters in the first timing screens

User counters; utilization includes user+kernel CPU divided by allocated cores.
Top-down columns are percentages of user slots; fetch latency is a subset of FE.
Keep counter-derived values (small hardware/aggregation discrepancies are not
renormalized). These are baseline characterization, not speedup observations.

| Service / normal operating point | L2 code MPKI | Utilization | Retiring | Bad speculation | FE bound | BE bound | Fetch latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| ComposeReview, full Media2500RPS,2cores | 2.33 | 81.50% | 22.94% | 5.88% | 46.67% | 24.51% | 33.33% |
| MovieId, same stack/rate,2cores | 1.04 | 34.40% | 18.43% | 4.31% | 41.18% | 36.08% | 30.39% |
| MySQL durable400TPS,4cores | 4.28 | 15.82% | 33.98% | 6.82% | 39.05% | 21.35% | 30.49% |
| Scylla20kops/s + MySQL400TPS,4sharedcores | 12.09 | 44.97% | 13.81% | 6.07% | 56.36% | 24.05% | 48.40% |

For Scylla, the initial exploratory sequence reused its private dataset. Repeated
updates changed its LSM state and instructions/operation, so those baseline costs
must not be pooled. A subsequent screen and all confirmation arms instead clone
the unchanged original 1M-record dataset read-only before every run. The workload
remains 50/50 read/update with the same 30-second warmup; no dataset reduction or
application work removal is used to obtain an improvement.

RPC validity distinguishes startup from timing: each 12-second warmup had 11–22
non2xx responses. The logs record upstream concurrent first-review-document
creation races (`E11000` duplicate keys in user-review/movie-review MongoDB
collections). All ten subsequent 50-second timed loads have zero non2xx responses
and no socket-error report. Warmup errors are retained and disclosed; “zero
errors” applies to the timed comparison, not every request since stack startup.


## Aggressive variants and independent confirmation

The online transition predictor did not pass screening. To reduce update cost,
the frozen variant trains the first 1,000,000 dispatches per reactor and then stops
updating the transition table. Both versions first use an available live queue
target and predict only when that queue is empty. One- and four-line variants were
tested; four lines cover 256 bytes from one callee entry, not four future callees.

In a separate diagnostic with the same fresh-data setup and four-line frozen
policy used for confirmation, 17,714,619 dispatches yielded 5,639,961 predictions:
**97.22% next-target accuracy, 31.84% dispatch coverage**, with mean matched lead
**2,220 invariant-TSC ticks**. Live queue coverage was 44.36%. All four reactors
had completed training before the measurement window; owner collisions were zero.
These are instrumented diagnostics. Target accuracy is neither cold-miss accuracy
nor the fraction of costly instruction misses covered.

The initial frozen four-line screen selected +0.80% vs original and +1.69% vs NOP.
Its mutable LSM state prompted the per-arm reset check. The fresh-data screen
instead found +0.06% vs original and −0.09% vs NOP. The originally selected policy
was still taken through all five fresh paired rounds, with no screening trials
pooled into confirmation. This explicitly tests whether the apparent initial win
reproduces.

## Scylla performance results

CPU efficiency, positive means less CPU per completed operation. Initial and
frozen screens reused a private mutable dataset; each screen has its own baseline.
Fresh screen and confirmation reset from the same read-only source before every
arm. Single-trial screens are selection observations, not confirmed effects.

| Stage | Policy | vs original | vs exact NOP |
|---|---|---:|---:|
| Initial screen | `late` | -0.62% | +0.51% |
| Initial screen | `queue1` | +0.67% | -0.89% |
| Initial screen | `queue1_lines4` | +0.77% | -0.31% |
| Initial screen | `aggressive` | -1.26% | -2.22% |
| Initial screen | `aggressive_lines4` | -1.49% | -1.40% |
| Frozen screen | `aggressive_frozen` | +0.59% | -0.22% |
| Frozen screen | `aggressive_frozen_lines4` | +0.80% | +1.69% |
| Fresh-data screen | `queue1_lines4` | -0.36% | -1.29% |
| Fresh-data screen | `aggressive_frozen_lines4` | +0.06% | -0.09% |
| **Fresh five-pair confirmation** | **`aggressive_frozen_lines4`** | **+0.08% [−0.84, +1.01]** | **+0.19% [−1.51, +1.92]** |

Confirmation uses paired log-ratios and unadjusted t95% intervals (df=4), without
pooling screening observations. The early +0.80% selection did not reproduce as a
statistically supported gain. All 15 confirmation arms completed successfully.

| Confirmation mean | Original | Aggressive frozen, four lines | Exact NOP |
|---|---:|---:|---:|
| CPU microseconds / operation | 88.782 | 88.712 | 88.880 |
| User L2 code MPKI | 12.286 | 11.857 | 12.203 |
| L2 code misses / operation | 1223.35 | 1193.37 | 1226.21 |
| User instructions / operation | 99572 | 100651 | 100488 |
| FE-bound slots | 54.57% | 54.08% | 53.31% |
| BE-bound slots | 25.03% | 25.10% | 25.76% |

MPKI fell 3.49%, but absolute misses/operation fell only **2.45%**, while user
instructions/operation increased **1.08%** (ratios of arithmetic means). The MPKI
denominator therefore contributes to its apparent reduction. Neither top-down
aggregate movements nor target prediction accuracy establish a causal stall saving.
No new policy earned the conditional static-graph composition follow-up; that
comparison has not been performed for these services.

## Applicability and next decision

All listed runtime-dispatch candidates are catalogued as **A-3 methods**. Scylla
retains its **B/interleaved miss regime**: sharing cores with a real durable MySQL
service is the qualified setting. VPP was qualified only with AF_PACKET IPv4
forwarding; this says nothing about an untested CSIT/DPDK workload. Envoy's legacy
low-MPKI observation used all-mode counters. Social RPC and Django have no new
qualification or optimization result in this campaign.

RPC's measured lead did not justify prediction on a short-lead argument. MySQL
received live-target hooks but no lead probe or aggressive predictor; no conclusion
about its deeper prediction opportunity follows. Scylla's measured lack of queued
future targets is the explicit aggressive-mode gate. Static insertion sites and
runtime target loads are separated from its online-trained predictor. None is a
generic transformation for arbitrary C++ call graphs.

A useful next experiment would measure which **predicted code lines actually miss**
and cause exposed frontend stalls, rather than increasing successor accuracy alone.
The present diagnostics cannot causally apportion a neutral result among already
hot targets, uncovered code, hook overhead, overlap with backend stalls, or lead
variation. ITLB/BTB misses are not repaired by these data-prefetch hints.


## Validation, evidence and reproduction

[Published analysis](../llvm_prefetchit/migration/evidence/class_a3_dispatch_20260924/analysis.json)
retains the screen/confirmation outcomes and diagnostics. Raw counter/client
observations, per-binary manifests/assembly and the full reproduction archive
remain local. The [publication inventory](../llvm_prefetchit/migration/evidence/README.md)
identifies the compact subset in Git; it is not the full local archive.

- Eleven unique execution tests passed: ELF PIE/ET_EXEC preservation and exact NOP,
  four queue/diagnostic cases, four online/frozen predictor cases, and RPC target
  resolution/order under ASan+UBSan. Future functions are never invoked early.
- All 15 confirmation arms have successful READ/UPDATE counts and per-arm dataset
  clone proofs. All timed RPC loads are error-free; the disclosed warmup races are
  excluded from timing. MySQL rate/progress/error checks are enforced by the harness.
- All 79 perf counter files have numeric results and 100% scheduling. Twelve
  platform sessions (193 per-CPU records) restored their prior platform/HWP state.
  Temporary containers and VPP namespaces are absent; original DB containers remain
  stopped. The task-owned Scylla data clone was removed after measurement; the
  original dataset and pre-existing private MySQL volume are preserved.
- Rebuildable non-selected/diagnostic Scylla binaries were removed (2.31 GB of
  cumulative removals, including a pair rebuilt for the fresh screen). The pinned
  original and final PF/NOP pair remain. The new Git evidence is approximately
  2.7 MB / 36.5k lines, with no binaries, dependencies, full trace or server log dump.

Builders: `llvm_prefetchit/scripts/static/build_rpc_future_targets.py`,
`build_mysql_future_targets.py`, `build_scylla_future_targets.py`; restricted
rewriter: `llvm_prefetchit/tools/append_dispatch_hooks.py`. Package hashes and ABI
fingerprints fail closed on uninspected inputs. Example selected build:

```sh
python3 llvm_prefetchit/scripts/static/build_scylla_future_targets.py \
  <pinned-original-scylla> <output> --mode aggressive_frozen --lines 4 \
  --gate llvm_prefetchit/migration/evidence/class_a3_dispatch_20260924/scylla/prediction_gate.json
```

The builder also emits the exact `.nop` twin. Archived platform `command.json`
files and `measure_*.py` record CPU assignments, rates and image/data prerequisites;
they are host-specific harnesses, not portable benchmark installers. Recomputing
archived summaries requires only Python's standard library and `analyze.py`.
