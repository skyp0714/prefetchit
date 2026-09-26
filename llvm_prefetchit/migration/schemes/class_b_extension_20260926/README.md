# Class B: per-service wake-stream prefetch

Exact source snapshot of the completed Media/SocialNetwork campaign. Baseline Intel
PT selects run-start frames, function-entry and post-call targets; plans are inserted
statically with lead 8/16 and an identical-layout NOP control. Training and performance
confirmation use separate runs. This is trace-guided placement, not trace-free static
analysis. See the [results and operating protocol](../../../../docs/class_b_coldmiss_summary_20260926.md).

- `run_paths.py`, `trace_media.py`, `trace_social.py`: baseline path reconstruction and target selection.
- `build.py`, `pipeline.py`: pass-based insertion, NOP controls, independent confirmation.
- `media.py`, `social.py`, `load.py`: complete service stacks, open-loop load, cgroup CPU accounting.
- `audit_qualification.py`, `report.py`, `consolidate.py`: operating-point gates and paired summaries.
- The small policy JSONs retain the final warmup/tracing/confirmation amendments.

These are host-specific research drivers, not a turnkey benchmark installer. For a
new run, stage the snapshot at the original ignored driver directory
`llvm_prefetchit/results/class_b_extension_20260926/` and adjust the host paths.
`common.py` names the original repository and allows `CLASS_B_STORAGE_ROOT` and
`CLASS_B_TRACE_ROOT` overrides. The old orchestration waits for `PIPELINE_READY` and
`SOCIAL_READY`; create those markers only after the complete drivers and dependencies
are staged. Run with the campaign lock and root privileges on an idle measurement host.

Required external inputs remain outside Git: upstream DeathStarBench source/data,
`dsb-deps-jammy` container dependencies, the local LLVM 19 pass build, Media support
binaries under `results/class_a2_20260923/media_rpc_production/support`, the movie
initializer under `results/class_a2_20260923/media_production_qualification/base_2500`,
and upstream request-title data referenced by `load.py`. Paths below `results/` are
relative to `llvm_prefetchit/`. The tracked `flat_codegen/dsb_build` helpers are also
used. Stage archived binaries locally before timing; follow the repository retention
and single-stream, rate-limited rsync policy.

`sources.json` records byte-identical source provenance. Retry controllers, credentials,
readiness markers, generated plans, traces, databases, executables and logs are omitted.
