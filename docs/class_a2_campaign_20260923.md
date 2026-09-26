# Class A-2: DCPerf v2, services and databases (2026-09-23)

The confirmed new result is **FeedSim v2: 5.19% less CPU/request at 40 QPS**,
with five fresh paired rounds and a same-layout NOP comparison. This is a
future-target-array dispatch optimization; it does not establish arbitrary
control-flow generalization. Rails, MySQL, Django, Silo and the three Media services have not demonstrated
3% with the tested methods. Their policy screens are complete; the requested
across-workload 3% target remains unmet.

User classification: **A-1** is sequential generated code
(Verilator/arcilator/CXXRTL); **A-2** is complex control flow
(FleetBench, DCPerf v2, services/databases). ARM remains a synthetic control.
Prior A-1 and FleetBench results are in
[class_a_generalization_20260922.md](class_a_generalization_20260922.md).
Raw data, per-run harness snapshots and reproducible commands are under
`llvm_prefetchit/results/class_a2_20260923/` (abbreviated `R` below).

## DCPerf v2 really retains the function-pointer array

Provenance is `origin/v2-beta` at
`b109b090c4d146204edf9c45f96f2d427445804b`; installed source is byte-identical to
that revision. Local `ed443ab9a7f4d07d25959678275d2e9531b88868` adds host installer
fixes without changing FeedSim. Exact hashes are in `R/dcperf_v2_provenance.json`.

- `FeatureExtractorSuite.h:86`: `std::vector<CopyFn> flat_copies_`.
- `generated/dispatch.h:35`: `using CopyFn = void(*)(CopyContext*)`.
- `FeatureExtractorSuite.cpp:96`: populate with `getAllCopyFunctions`, shuffle once.
- `FeatureExtractorSuite.cpp:191`: atomically reserve a consecutive range.
- `FeatureExtractorSuite.cpp:202`: call `flat_copies_[(start+i)%total](&ctx)`.

These files are in
`benchmarks/dcperf_v2/benchmarks/feedsim/src/workloads/ranking/feature_extractors/`.
The installed runtime has **104,850 generated copy-function pointers**.
Thread interleaving changes reserved start offsets; future targets inside each
reserved range remain readable. Thus the array supplies an unusually accurate
lookahead target even though the addresses are shuffled and calls are indirect.
The experiment preserves full FeedSim DLRM/RPC/TLS/ZSTD/feature/story work,
including the simulated outbound I/O. It is not an extracted dispatch loop.
The optimization is currently a source prototype, not an automatic compiler pass.

Obsolete DCPerf icachebuster results are excluded. Django's v2 history includes
`d20d38c` removing icachebuster calls; installed views only retain a commented
library load. Generated Python code variants are part of the v2 installer,
not additional cache pressure introduced for this experiment.

## Protocol and selected operating points

Select the maximum baseline MPKI among normal settings with utilization ≥15%,
application failures ≤0.1%, no socket errors and achieved fixed rate ≥98% of
offered rate. FeedSim additionally requires p95 ≤700 ms. No artificial cache
flushes, co-runners or workload inflation are added to create eligibility.
Selection precedes policy comparison. Closed-loop/capacity throughput is kept
separate from fixed-rate CPU cost. Five fresh interleaved paired rounds and a
same-layout NOP control are required for a confirmed prefetch gain.

The Xeon 6787P host uses fixed 2 GHz core/HWP settings, turbo off, fixed maximum
uncore and C6 off on participating cores during each wrapper. Each wrapper saves
and restores its exact prior state in `finally`; controller cores are 84–85.
Builds, tests, decoding, hashing large binaries and other benchmarks are serialized
outside timing windows. Original service data is untouched; MySQL uses a private
volume clone and Media a private Docker project.

| Workload | Selected normal setting | Utilization | L2I MPKI | User-mode Top-down FE | Interpretation |
|---|---|---:|---:|---:|---|
| FeedSim v2 | 8 server cores, 40 QPS, full defaults | 87.25% | 3.622 | 39.26%* | Array-readable targets; confirmed below |
| Silo | 4 workers/warehouses, 5k QPS | 15.24% | 9.13 | 9.12% | BE 75.19%; high MPKI does not make this FE-bound |
| Rails | CRuby 3.2, Rails 8 production, Puma 4×8, 800 RPS | 36.85% user | 1.889 | 32.9% | 20k posts, YJIT off, original endpoint |
| MySQL 8 | 16 tables×200k rows, 16 clients, 400 TPS | 16.11% | 4.243 | 38.2% | 4 GiB buffer, durable commit/binlog settings retained |
| Django v2 | CPython 3.14.2, 4 server cores, 20 connections | 83.76% user | 1.784 | 44.1% | Full v2 application, Cassandra and async services |
| Media MovieId | 2 cores, 2,500 RPS | 34.62% | 1.405 | 41.96% | Info logs, fresh full stack per trial |
| Media ComposeReview | 2 cores, 2,500 RPS | 82.52% | 2.777 | 46.27% | Kernel CPU share 81.41% |
| Media Rating | 2 cores, 2,500 RPS | 31.71% | 0.711 | 38.43% | Kernel CPU share 73.33% |

FeedSim FE is the mean baseline share in the five fixed-40-QPS confirmation
rounds; BE is 15.06%. Other table FE values are qualification observations.

Rails/Django use user cycles divided by fixed 2 GHz for CPU cost and
utilization; kernel work is excluded. FeedSim/MySQL task-clock includes user and
kernel time. Production Media trials use per-container cgroup user+kernel CPU accounting
for eligibility and cost, with per-CPU user PMU counts retained separately. Absolute costs across these categories are not directly comparable. All reported
L2I/instruction/Top-down events in these comparisons are user-mode events.
In a syscall-heavy service, a high user-mode FE share does not by itself prove
that the whole service is predominantly frontend-bound.
CPU/request for FeedSim and HTTP services uses the approximately 25-second counter window
and aggregate achieved request rate, an approximation. MySQL aligns the window
with 25 one-second TPS reports. None of these cost reductions are called a
fixed-rate throughput gain.

Baseline sweeps retained in full:

- FeedSim 5/10/20/30/40 QPS: utilization 11.13/22.25/44.16/65.74/87.25%,
  MPKI 3.521 at 10, 3.499 at 20, 3.491 at 30, 3.622 at 40. Five QPS is below
  utilization threshold. Initial offered 50/100/200/300 all saturated near 46 QPS.
- Silo 1k/5k/10k/20k: utilization 2.98/15.24/31.04/55.70%,
  MPKI 9.56/9.13/9.00/8.36.
- Rails 400/800/1500 passed; 3000 achieved only 2135 RPS with socket errors
  and p99 21.74 seconds and is excluded.
- MySQL 200 TPS is below utilization threshold; 800/1200 valid but lower MPKI.
  Unbounded 1773.63 TPS is a capacity observation, not a fixed-rate candidate.
- Django 4/8/20 connections: utilization 73.34/82.05/83.76%,
  MPKI 1.564/1.705/1.784. The selected baseline has 1 failure in 10,463 requests.

## FeedSim: approximately 5% confirmed

The selected policy issues one T1 data-prefetch to the function entry **four
calls ahead**. Build manifests exist for lead 1/2/4/8 and a two-line alternative;
retained timing evidence verifies lead-four, so the other builds are not counted
as completed performance comparisons. Its cursor
uses increment/wrap instead of per-iteration division; the same-layout NOP twin
retains that code, so the NOP comparison separates the actual hint benefit.
`R/build_feedsim_dispatch.py` reproduces the variants.

| Fresh paired comparison | Versus original baseline | Versus same-layout NOP |
|---|---:|---:|
| 40 QPS: CPU/request reduction | **5.19%** | **4.95%** |
| 40 QPS: equivalent CPU-efficiency speedup | 5.48% (95%: 4.94–6.02%) | 5.20% (4.75–5.66%) |
| Offered 100 QPS: achieved-throughput increase | 4.99% (4.05–5.95%) | 5.28% (4.82–5.73%) |

Each comparison has five new paired rounds; intervals are paired log-t intervals
and describe run variation, not generalization to different workloads.
All **15 fixed-40-QPS trials** satisfy rate/error/p95 criteria, and every pair
reduces CPU cost. MPKI falls 5.41% versus baseline. Fixed-rate throughput remains
capped by offered work. Evidence: `feedsim/fixed40_confirmation/summary.json`
and `feedsim/paired_analysis.json`.

The saturated experiment is **not all-round SLA-qualified capacity**: baseline
p95 exceeds 700 ms in rounds 2/3 (705.58/708.81) and NOP in round 4 (707.68).
These rounds are retained, not silently dropped. Mean achieved QPS is
46.288/48.600/46.164 for baseline/prefetch/NOP; all prefetch p95 values are
551.57–638.94 ms and no driver errors occurred. CPU/request falls 5.79% versus
baseline. Evidence: `feedsim/confirmation/summary.json`.

Mechanism evidence is consistent with useful lead time, not just extra retired
instructions: at saturation instructions/request rise 0.37%, L2I/request falls
5.65%, absolute FE slots/request fall 20.82% and fetch-latency slots/request
fall 29.35%. BE slots/request rise 10.52%; Top-down attribution does not directly
measure overlap or prove the exact causal latency saved. The isolated
FRONTEND_RETIRED.LATENCY_GE_64 run at 40 QPS falls about 13.8% per request.
That single diagnostic counts qualifying retired instructions, not stall cycles,
and is not an additional timing confirmation.

## Generalization experiments beyond the dispatch array

Two separate methods were evaluated:

1. **Static placement in existing executable padding.** Replace canonical
   in-function NOPs with same-length RIP-relative T1 hints; look ahead to a
   direct callee at 256/512/1024-byte windows or own code at +256/+512 bytes.
   Removing hints exactly restores the baseline, controlling code layout.
2. **Profile-guided placement probe.** Retired-L2 miss samples plus LBR select
   target code lines and predecessor NOP sites. Short/long lead windows and
   strict/relaxed vote shares test placement sensitivity. LBR edge cycles are
   a retirement-time proxy, not actual fetch lead. Conditional target vote share
   is not execution probability. The index was expanded from symbol-bounded
   7/8-byte NOPs to executable-section padding, including validated long forms.
   Only sites observed in continuous LBR segments can be selected.

These padding probes are constrained by available insertion sites and are
**not an achievable-performance upper bound**. The LBR version is explicitly
profile-guided, not purely static compiler analysis. Cross-DSO/unknown cycle
segments stop traversal. PIE mapping uses each sampled process's load map.

| Workload | Completed policy evidence | Best observation / status |
|---|---|---|
| Silo | Five static padding policies | About +0.8% in one screen; backend dominated, no confirmed 3% |
| Rails | Five static policies; symbol-bounded and expanded LBR policies | Static all regress; expanded best −0.06% CPU efficiency, no 3% |
| MySQL | Five static policies; symbol-bounded and expanded LBR policies | Expanded long-lead +0.47% in one screen, no 3% |
| Django | Five static policies; four corrected mapped LBR policies | Best mapped relaxed +0.65% in one screen; short-lead −0.59%/−2.42%, no 3% |
| Media | Five static policies on each of MovieId/ComposeReview/Rating, production logs and fresh stacks | Best single-screen observations +0.13% / +0.56% / +1.18%; no confirmed 3% |

Rails LBR has 27,714 samples / 17,065 in libruby. The original 645-site index
selected only one patch; 32/128 budgets produced identical binaries and are not
independent policies. The expanded index has 4,811 sites; the relaxed plan selects
12 sites, with 706 samples having a candidate. MySQL has 19,797 samples / 17,333
in mysqld; expansion from 10,416 to 67,230 NOP sites produces at most 19 patches
in the relaxed plan, with 884 sample candidates. Sparse coverage limits both
conclusions. These raw sample counts must not be read as exact useful-miss coverage.

Django's first trace recorded only master-process maps and could not map worker
samples after workers renamed their process comm. Those failed plan builds are
**setup failures, not evidence of absent opportunity**. Recollection saves maps
for all descendants containing libpython: 44,899 samples, 16,464 target samples,
all mapped. Its 6,739-site index yields distinct short/long/relaxed policies.
The mapped screen completed baseline, long and relaxed arms, then hit a transient
7199 shutdown listener. Bounded preflight waiting and exact per-run-marker cleanup
were added. A fresh baseline plus the two remaining arms completed with no
request errors: 32 sites reduced CPU efficiency by 0.59%, 46 sites by 2.42%.
The 46-site plan reduced MPKI by 3.24% despite increasing CPU cost by 2.48%.
This is another example of a miss reduction without a performance benefit.
Django static seq512 had 15 failures / 10,412 requests (0.144%) and is excluded
from performance credit even though its reported latency/cost looked better.

Sampled-DSO attribution (`R/lbr_dso_analysis.json`) further limits the
interpreter-only conclusions: libruby contains 61.58% of Rails samples, mysqld
87.55% of MySQL samples, and libpython3.14 only 36.67% of Django samples.
Django also includes proxygen_binding (9.87%), python3.12 (7.98%) and Cassandra
extension DSOs. These are retired-L2 sample shares, not fractions of execution
time or proven speedup potential. An eventual broader placement method must
cover those components explicitly.

Detailed estimates, including invalid rows, are in `R/service_analysis.json`.
No fresh five-round confirmation is triggered by these small exploratory
observations (Media promotion threshold was 1.5%, set before screening). The requested across-workload 3% target remains unmet.

## Media setup and measurement corrections

The private stack keeps the upstream compose-review Lua mix, seed 122,
1,000 movies, 18,194 cast entries and 1,000 users. MovieId, ComposeReview and
Rating each have two dedicated server cores. Backends, ingress and clients are
on other cores. A clean source archive produces one-pass compiler builds;
the earlier accidental double-plugin build was never measured and is excluded.
Four policies prefetch handler entries or static descendants. MovieId has
8/16/32/32 hints, ComposeReview 20/40/80/80 and Rating 4/8/16/16; all have NOP twins.

Failed initializations exposed compatibility defects and are retained as failures:
missing aiohttp in the root environment, ingress readiness, Lua request-body
spilling, null optional TMDB fields, duplicate movie titles and a Jaeger version
without the legacy UDP agent. Private harness fixes use the normal user's Python,
wait for real backend/ingress readiness, preserve startup restart behavior and:

- Pin Jaeger 1.57, verify UDP 6831 and retain at most 10,000 traces.
- Increase body buffering to 1 MiB only on initialization endpoints.
- Translate absent poster/overview to empty optional values.
- Register the first input occurrence of each title, matching the unique-title
  lookup API; still upload all movie-info and plot records. Validate exactly
  995 registered titles for the 1,000 input movies.

`media_screen6` was the first functionally successful run but is **excluded from
all performance credit**. Per-PID perf raced with short-lived std::async threads:
missing Top-down counters and inconsistent slots/cycles occurred despite perf
reporting 100% scheduling and stable service PIDs. The replacement `media_screen7`
uses per-CPU user counters on dedicated core pairs and checks every required
numeric event, scheduling and slots/cycles consistency. Its user-only utilization
is too restrictive for RPC services with substantial kernel work; therefore
`media_screen8` repeated baseline selection using complete cgroup CPU accounting.
Those debug-log runs are retained only as setup diagnostics, as explained below.
Per-CPU task-clock measures elapsed CPU availability, so it is not used as busy
utilization. User cycles / fixed frequency remain a separate diagnostic. Final cost and
utilization use deltas of cgroup v2 `cpu.stat` (`usage_usec`, `user_usec`,
`system_usec`) over the observed measurement interval; this includes all transient
threads without perf attaching to individual TIDs. Semantics follow the
[Linux cgroup v2 documentation](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/admin-guide/cgroup-v2.rst).
Container PID/restart checks before/after each trial additionally reject restarts.
At 3,000 RPS the stack only achieved 2,722.64 RPS with 325 HTTP errors; that
point is excluded. At 2,500 RPS, the later screen has 184 HTTP errors; a 2,000-RPS policy-screen
baseline also has 182 failures in 100,082 requests. Neither is eligible for a
performance claim.

### Production operating setting correction

Live logs revealed that upstream `src/logger.h` unconditionally enables debug
severity, emitting multiple lines per request. Consequently all debug-log Media
screens (`media_screen7`, `media_screen_high7`, `media_screen8`,
`media_movie_rpc_screen8`) are excluded from production performance claims in
`R/EXCLUDE_media_debug.json`, even where their PMU data is valid. At 2,000 RPS,
those runs spend roughly 74–79% of accounted CPU in the kernel; user-mode FE
shares alone would give a misleading view of the whole service.

The replacement builds **all 13 C++ services with the same info-level logger
filter**, from the same private clean source revision. Every baseline, prefetch
and NOP arm uses that configuration. This operating-setting change is not
credited as a prefetch gain. The private rebuild also records the required
PicoSHA2 header hash; the first auxiliary-service build failed because that
header was absent from the source archive and was retried with it included.

`build_media_production.py` creates the baseline/policies, and
`run_media_production.py` performs a new baseline-only load sweep. Each rate and
each policy trial has a newly initialized private stack and identical initial
dataset. This avoids comparing different accumulated review volumes or stale
connections after replacing a service. A fresh baseline must pass again at the
selected rate before testing policies. Promising results require five additional
interleaved rounds with NOP controls; all invalid rounds are retained.

### Production Media results

Six fresh baseline points were measured: 500/1,000/1,500/2,000/2,500/3,000 RPS.
The first five pass the rate/error criteria. At 3,000 the stack achieves only
2,922.04 RPS (97.40%) and p99 is 3.02 seconds, so it is excluded even though
there are no HTTP errors. At 2,500 it achieves 2,502.17 RPS with zero errors and
p99 12.19 ms. This is the eligible maximum-MPKI point for all three services.
Each service's baseline passes again before its policy screen.

All 18 production policy-screen trials (baseline plus five policies on each
service) meet rate/error criteria. These are **single-round screens**, not
confirmed gains. The five policies are handler entry 4/8 lines, direct handler
children, grandchildren, and static padding/callee lookahead at 512 bytes.

| Policy | MovieId CPU-efficiency change | ComposeReview | Rating |
|---|---:|---:|---:|
| Handler 4 lines | +0.13% | −0.05% | +0.36% |
| Handler 8 lines | +0.06% | +0.36% | +0.26% |
| Handler children | +0.09% | +0.24% | +1.18% |
| Handler grandchildren | −1.12% | +0.56% | +1.03% |
| Padding/direct callee | −0.42% | +0.11% | +0.23% |

The metric is the selected service's user+kernel CPU per external request,
not full-stack throughput or total deployment CPU. No candidate reached the
predeclared 1.5% promotion threshold, so none received a five-round/NOP
confirmation and none is credited as a demonstrated prefetch gain. MovieId's
8-line policy reduced MPKI about 5.28% in its screen but changed total CPU cost
by only −0.06% and user CPU cost by +0.43%; the miss reduction alone is not a
performance result. Full rows and invalid historical debug trials remain in
`R/media_analysis.json`; provenance and selections are in
`R/media_production_selections.json` and `R/media_production_jobs.json`.

### Separate all-mode diagnostic

A final baseline at 2,500 RPS collected user+kernel PMU counters on the dedicated
service cores. It achieved 2,502.11 RPS, zero HTTP errors and p99 12.62 ms.

| Service | All-mode frontend bound | All-mode backend bound |
|---|---:|---:|
| MovieId | 23.53% | 50.20% |
| ComposeReview | 26.47% | 46.86% |
| Rating | 23.14% | 50.39% |

This configuration is more backend-bound than the user-only profile suggests.
It is not an ideal frontend-dominated workload for a user-code prefetch policy.
This is one separate diagnostic, not proof of which particular cache misses
were overlapped or an additional timing confirmation. Per-CPU all-mode counters
can include activity outside the service cgroup; they are not interchangeable
with the cgroup CPU-cost metric. Evidence: `R/media_production_allmode`.

## PMU, validation and literature

Intel's [GNR event table](https://raw.githubusercontent.com/intel/perfmon/main/GNR/events/graniterapids_core.json)
marks FRONTEND_RETIRED.LATENCY_GE_64
[TakenAlone](https://github.com/intel/perfmon#takenalone). The new FeedSim diagnostic
requests that programmable event alone. Earlier Silo FE64 combined with other
programmable events is excluded from mechanism claims; its separate timing,
cache and Top-down measurements remain usable. One hundred percent reported
scheduling alone does not override event restrictions or missing thread coverage.

The current tools passed **42 tests** in 1.92 seconds, outside benchmark windows
(`R/repair_tests.log`). Tests cover executable boundaries/canonical padding,
actual decoder validity of long NOP replacements, reverse restoration, PIE maps,
LBR cycle direction and stopping at unknown or cross-DSO segments. Final audit (`R/audit.json`) verifies **44 platform runs / 928 per-CPU
snapshots restored**, including HWP. All 237 nonexcluded counter files have
numeric values and full scheduling; 12 known incomplete Media per-PID files
remain explicitly excluded. This counter audit does not override application,
SLA, debug-log or TakenAlone exclusions. `git diff --check` passes. No benchmark
processes or task-owned Media containers remain running. Original MySQL/Scylla
containers remain stopped; the private MySQL clone is retained and original
volumes were not changed.

Selected metadata, counters, client logs and reproduction harnesses are preserved
under `llvm_prefetchit/migration/evidence/class_a2_20260923/`, with hashes in
`SHA256SUMS`. Generated plans, per-CPU platform snapshots, superseded Media debug
runs, warmup/build logs and duplicate source/report copies were removed from this
review archive on 2026-09-23. Negative-result summaries and explicit exclusions
remain; the audit describes the original full campaign in `R`.
Full raw evidence, ELF/build/perf.data/decoded-trace artifacts remain in `R`;
this is not a standalone redistribution of the workloads. `implementation_provenance.json`
records the prebuilt plugin hash, source/tool hashes, kernel/perf version and
build image ID. No additional timing jobs remain queued.

[AsmDB (ISCA 2019)](https://liberty.princeton.edu/Publications/isca19_frontend.pdf)
emphasizes profile/control-flow-informed timely placement. Its proposed
instruction fills L1-I and uses I-TLB; ordinary T1 data-prefetch does not inherit
those capabilities or its reported coverage.
[Software CGP (TOCS 2003)](https://pages.cs.wisc.edu/~jignesh/publ/CGP-TOCS.pdf)
uses profiled call sequences and motivates selective future targets rather than
prefetching every reachable callee.
[Hierarchical Prefetching (ASPLOS 2025)](https://www.research.ed.ac.uk/en/publications/hierarchical-prefetching-a-software-hardware-instruction-prefetch/)
combines software grouping with additional hardware record/replay. It motivates
RPC subgraph tests, but its gains cannot be assigned to our software-only hints.
Media compatibility fixes follow
[nginx body buffering](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_body_buffer_size)
and [Jaeger 1.57's agent implementation](https://raw.githubusercontent.com/jaegertracing/jaeger/v1.57.0/cmd/all-in-one/main.go).

The next methodological step after these neutral padding probes is profile-guided
IR/Machine placement with independent layout controls and DSO-complete coverage.
Separately inspect long frontend latency, branch/ITLB stalls and per-request
backend work before increasing hint count. A high MPKI or lower miss count alone
is insufficient evidence that the saved misses were on the performance-critical
path; backend stalls need not be literally zero for a useful frontend improvement.

## Compiler direction supported by these observations

The two application successes so far have an identifiable future target source:
FleetBench's schema/type graph and FeedSim's immutable function-pointer array.
A useful common compiler abstraction is a provable future target plus an earlier
safe issue site, with a small per-iteration hint budget. Array lookahead requires
bounds/wrap handling and proof that intervening calls cannot mutate the dispatch
array; a profile or explicit annotation must not be silently treated as an alias
proof. The current FeedSim source prototype does not provide that compiler proof.

For arbitrary control flow, first expand measured module coverage and permit
IR/Machine insertion outside pre-existing NOP sites. Preserve a same-layout NOP
variant, separate profiling from confirmation, and tune lead/target precision
against complete CPU cost. The existing padding failures do not establish that
this more flexible placement cannot work. A static policy should be extracted
only after an independently confirmed placement experiment shows a recoverable
frontend benefit in another application.
