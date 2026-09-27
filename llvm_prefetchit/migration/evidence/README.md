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
