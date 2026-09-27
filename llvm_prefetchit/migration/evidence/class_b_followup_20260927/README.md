# Request metrics and schedule-relative MovieId misses

[Report and plot](../../../../docs/class_b_request_and_miss_timeline_20260927.md)
separate post-hoc request performance from separately instrumented diagnostics.

- `request_metrics.json`: seven paired blocks per family, external HTTP p99 and
  delivered RPS. Fixed 600 RPS does not establish maximum throughput. Neither
  family establishes a p99 reduction against baseline; all three controls are
  reported, including Social's higher p99 against the retained reference.
- `miss_timelines.json`: four 15-second PEBS captures, two sampling periods in
  each of one baseline and one new-policy MovieId process. Other services stay
  at baseline. Time zero is next-task selection at `sched_switch`; timestamps
  describe retirement of instructions that experienced an L2 miss, not the
  instant of fetch. No independent performance claim is made from these runs.
- `timeline_provenance.json`: settings, commands, raw record-type counts,
  captured source hashes, exact-duplicate decoder amendment, workload health,
  binary hashes and bulk-removal manifests.
- `tid_sensitivity.json`: effect of omitting samples with TID=-1. These are
  resolved only inside an exact target TGID/CPU scheduling interval; raw task
  lifetimes cover new and exiting threads. All four captures have 100% joins.
- `exclusions.json`, `excluded_decode_recovery.json`, cleanup summaries: failed
  setup, static-TID and interrupted-load attempts remain excluded. The complete
  baseline capture's duplicate-record parser failure was recovered offline
  under the same final decoder used for the new arm; real gaps still fail.
- `validation.json`: nine parser tests, four admitted captures / 48,696 samples,
  180 matching platform restoration checks, stopped task containers, module off
  and no remaining raw/decoded bulk. `source_audit.json` records the three
  `std::async` launch sites in the benchmark input; that input was not modified.
- `archive_reference.json`: fully SHA-256-verified local compact archive,
  including actual measurement/analysis source snapshots and negative results.
  No executables, original inputs or raw traces are published.

`source_manifest.json` records the final tool sources. `publication_manifest.json`
hashes the published evidence, report and figure. The detailed compact archive
stays under `/storage/prefetchit/class_b_followup_20260927/evidence_archive`.
