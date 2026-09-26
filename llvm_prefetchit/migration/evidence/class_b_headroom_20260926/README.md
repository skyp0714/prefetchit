# Class B 10% headroom investigation, 2026-09-26

No new service-performance measurements are present. `preflight.json` preserves
the initial unavailable sudo/PMU access. The user subsequently provided access;
`kernel_runtime_smoke.json` records successful basic runtime checks and unload. See
[`docs/class_b_headroom_20260926.md`](../../../../docs/class_b_headroom_20260926.md).

- `existing_operating_points.csv`: extracted historical operating-point results,
  preserving validity flags and absolute source paths.
- `cost_fractions.json`: historical baseline CPU fractions and the explicit
  fixed-kernel-cost arithmetic for a 10% target-CPU reduction.
- `trace_headroom*.json`: analysis of retained, rounded training first-touch
  marginals. Includes input hashes, missing-context accounting, selected global
  targets, and limitations. Context-oracle results are not deployable accuracy.
- `planner.patch`, `source_manifest.json`: new weighted merge implementation and
  source hashes. No new service binary has been built with these policies.
- `kernel_build.json`, `kernel_build.log`, `kernel_modinfo.txt`: successful module
  compile and opcode audit against the running kernel's headers, with warnings.
  Basic runtime checks are separately recorded in `kernel_runtime_smoke.json`.
  The current `.ko` stays local for service measurements.
- `validation.json`: 11 passing tool/ABI/ELF/planner tests; no privileged kernel
  performance test is claimed.
- `kernel_initial_build_cleanup.json`, `kernel_initial_source.c`: superseded
  first compile, binary hashes and reconstructed equivalent source record.
- `kernel_intermediate_cleanup.json`: removal of final unused intermediate
  objects, retaining current candidate and compact evidence.

No raw PT, decoded branches, datasets, old results, existing binaries, or NAS
contents were modified or removed by this investigation. No NAS transfers ran.
