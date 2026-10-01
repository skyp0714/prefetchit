# Preserved canonical evidence

These small CSV files were copied byte-for-byte from result directories that
are intentionally excluded from Git. They are retained so a source migration
does not lose the measurements behind the canonical result table.

| directory | contents |
|---|---|
| `verilator/` | Latest compact 100k-cycle summary plus fixed-3.8-GHz raw qsort, top-variant, and cross-payload runs |
| `django/` | Three paired baseline/`d4_next` service runs, including affinity and migration audit fields |
| `feedsim/` | Three interleaved baseline/target variants, including MPKI, IPC, and affinity audit fields |

`verilator/summary_20260901.csv` is the only retained compact source for the
latest 100k-cycle 1.080x static and 1.076x PGO numbers. The per-repetition file
for that exact short run was not retained. The other Verilator CSVs provide raw
fixed-frequency corroboration but use longer or cross-payload runs, so they must
not be presented as the raw repetitions behind the 100k-cycle summary.

The arcilator raw summaries and JVM result CSVs are tracked in the source-only
`flat_codegen` and `jit_prefetch` repositories respectively. Paths are listed in
`../core_results.tsv` and `../REPRODUCIBILITY.md`.

## Curated September 22–26 publication

Only the compact summaries, protocols, source hashes, exclusion reasons and final
figure listed in [curated_20260926.tsv](curated_20260926.tsv) are published from the
new campaigns. Each inventory row gives the relative path, bytes and SHA-256 of the
committed file. It does **not** inventory a complete reproduction bundle.

The September 27 request/timeline follow-up has a separate
[publication manifest](class_b_followup_20260927/publication_manifest.json),
covering its compact evidence, report and figure.

Raw perf/PT, individual service logs, generated plans/indices, build outputs and
compressed measurement/reproduction archives remain outside Git. Historical reports
may describe these local records; an archive filename or absolute path inside a
summary is provenance, not a claim that Git contains that file. Older canonical
tracked evidence described above is retained. No local archive was deleted to make
this publication smaller.

| Campaign | Main published evidence | Interpretation |
|---|---|---|
| FleetBench static/schema and ARM generalization | [general](class_a_general_20260922/summary.csv), [lead confirmation](fleetbench_proto_lead_20260922/confirmed_summary.csv), [further search](fleetbench_proto_search_20260922/confirmed_summary.csv) | Keep screening and fresh confirmations separate |
| A-2 services and kernel diagnostics | [services](class_a2_20260923/service_analysis.json), [kernel](class_a_kernel_20260923/analysis.json) | Kernel scenarios are conditional estimates, not measured speedups or strict upper bounds |
| A-3 F/G/FG and dispatch | [FleetBench factorial](class_a3_20260923/proto/factorial_analysis.json), [FeedSim confirmation](class_a3_20260923/feedsim/confirmation_analysis.json), [dispatch](class_a3_dispatch_20260924/analysis.json) | Source-specific prototypes; Scylla confirmation did not establish a gain |
| Overnight follow-up | [analysis](class_a_overnight_20260924/analysis.json) | Staged FeedSim gain; other unpromoted/negative policies retained |
| New native candidates | [qualification](class_a3_qualification_20260924/qualification.tsv), [further search](class_a_search_20260924b/qualification.tsv) | Candidate qualification is not an insertion speedup |
| JVM candidates and G/F/GF | [recheck](class_a_jvm_recheck_20260924/summary.json), [G2 comparison](class_a_jvm_fg_20260925/primary_comparison.json), [latest snapshot](jvm_status_20260926/results.json) | Planned 100-block confirmation was only 2/100 per candidate at this snapshot |
| L3/sTLB/PT and HP/CloudSuite expansion | [status](class_a_expansion_20260925/STATUS.md), [FleetBench filters](class_a_expansion_20260925/fleet_filter_summary.json) | Individual settings and exclusions are retained; not all planned experiments completed |
| AsmDB-style PT placement | [comparison](asmdb_trace_20260926/comparison.json) | Full-trace variants underperform baseline and the static schema reference |
| Class B extension | [consolidated](class_b_extension_20260926/consolidated.json), [main](class_b_extension_20260926/results.json), [Media 10%](class_b_extension_20260926_sampling10/results.json) | Fixed-rate user+kernel CPU/request; two applications, four services; no maximum-throughput claim |
| Class B five-service follow-up | [results](class_b_fullset_20260926/results.json), [CPU decomposition](class_b_fullset_20260926/user_cpu_breakdown.json), [diagnostics](class_b_fullset_20260926/diagnostics.json) | MovieId included; seven-block CPU comparisons, 13 kernel emission screens per service and independent kernel confirmation; detailed archive stays local |
| Class B request and miss age | [request metrics](class_b_followup_20260927/request_metrics.json), [miss timelines](class_b_followup_20260927/miss_timelines.json) | Post-hoc p99/RPS; MovieId schedule-relative PEBS at two sample periods, including dynamic thread lifetimes; diagnostic only |

[Source map](../schemes/README.md) links the implementations. Dated source snapshots
have independent `sources.json` hashes. This publication preserves experiment
outcomes without copying whole result trees into the repository.

## October 1 temporal prefetch campaign

[Report](../../../docs/class_b_temporal_20261001.md),
[independent confirmation](class_b_temporal_20261001/confirmation.json),
[final PMU and temporal summary](class_b_temporal_20261001/final_summary.json),
[verified publication manifest](class_b_temporal_20261001/manifest.json).

This campaign publishes small compressed **record archives** containing measurements,
settings, decisions, commands, source/patch records and binary hashes. They are not
executable or full reproduction bundles. Each member is SHA-256 verified and listed
in `records_manifest.json`. Generated plans, full location/callgraph indices, reusable
branch observations, raw/decoded traces, datasets and executable build outputs are
excluded; retained local derived records have a separate hash manifest. Rejected
generated binaries and raw traces were removed after their results were extracted.

The 25 independent confirmation trials are separate from 40 exploratory trials.
The final policy improves whole compose-review throughput by 2.42% versus original
(individual paired-log 95% CI 1.23–3.63%); its incremental throughput over the older
Mongo-only policy is not established by that comparison's interval. The operating
point has roughly 85% CPU utilization and is not a new maximum-throughput sweep.

## October 1 DSO ablation and RPC future-path campaign

[Report](../../../docs/class_b_rpc_future_20261001.md),
[independent confirmation](class_b_rpc_future_20261001/confirmation.json),
[PMU contrasts](class_b_rpc_future_20261001/pmu_contrasts.json),
[RPC target footprint](class_b_rpc_future_20261001/rpc_target_footprint.json),
[verified publication manifest](class_b_rpc_future_20261001/manifest.json).

This campaign tests strict removal of DSO hints, live virtual-call target hints,
RPC-type handler hints, and prior-trace downstream targets. A refined append pass
preserves existing decoder hints and code layout; an exact NOP disables only the
new RPC hints. The 25 independent confirmation runs are separate from 18 exploratory
runs and 8 diagnostic runs. The existing full policy remains best: throughput
+2.53% versus original (individual paired-log 95% CI +1.20–+3.87%). The no-DSO
and added-RPC throughput intervals versus original include zero. The operating
point is compose-review with MovieId, balanced C4 and about 85–87% CPU utilization.

The compact archives retain measurements, settings, commands, versioned source,
emitted assembly/patch maps, binary hashes, and cleanup decisions. Each member is
verified by SHA-256. Generated ELFs, datasets, full request lists and raw/decoded
trace copies are excluded. Rejected RPC binaries were removed after diagnosis;
the no-DSO ablation and previous winning/reference artifacts remain local.

## October 1 RPC phase and worker continuation campaign

[Report](../../../docs/class_b_rpc_route_20261001.md),
[measurements](class_b_rpc_route_20261001/report.json),
[restart record](class_b_rpc_route_20261001/resumption.json),
[stub address audit](class_b_rpc_route_20261001/training_stub_audit.json),
[verified publication manifest](class_b_rpc_route_20261001/manifest.json).

RPC decoder, handler and typed asynchronous-worker policies were tested with T1,
worker IT0, and the existing full DSO policy. The campaign contains 37 clean
endpoint trials, two separate PMU trials and six functional smokes. Eight completed
confirmation trials from before a host reboot are retained separately and excluded
from the fresh confirmation; the unfinished ninth trial is also recorded.

The full policy plus worker hints measured throughput +4.17% versus original
(individual paired-log 95% CI +1.72–+6.67%), but its incremental gain over the
incumbent was not established. A separate exact-layout NOP comparison measured
only +0.08%, with a wide interval. Removing three new hints to the issuing cache
line measured +0.76% versus the incumbent, also with an interval spanning zero.
The incumbent remains selected; the 10% throughput goal was not reached.

Only 20.50% of the retained training samples could be assigned to the modeled RPC
contexts, and the selected worker targets overlapped 2.08% of those samples' total
request-normalized population. An address-range audit located 12.71% of the total
training samples inside the incumbent's generated prefetch stubs; this is not a
slowdown estimate or attribution of target-prefetch misses. The selector now
excludes the issuing cache line, with the original measured source preserved.

All 7,076 archived records were SHA-256 verified. Failed and unpromoted generated
ELFs were removed after extracting their results; source, patch, hash and cleanup
records remain. Original datasets, shared dependencies and retained incumbent,
original and no-DSO reference binaries were preserved. Completed platform contexts
were audited separately from the reboot-interrupted context.
