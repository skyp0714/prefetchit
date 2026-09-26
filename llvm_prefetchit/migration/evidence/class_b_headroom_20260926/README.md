# Class B 10% headroom investigation, 2026-09-26

This directory retains the implementations' compact evidence and the real-service
campaign results. `preflight.json` describes the initial unavailable sudo/PMU
access, which the user subsequently supplied. It is historical, not the final
execution status. See
[`docs/class_b_headroom_20260926.md`](../../../../docs/class_b_headroom_20260926.md).

- `existing_operating_points.csv`: extracted historical operating-point results,
  preserving validity flags and absolute source paths.
- `cost_fractions.json`: historical baseline CPU fractions and the explicit
  fixed-kernel-cost arithmetic for a 10% target-CPU reduction.
- `trace_headroom*.json`: analysis of retained, rounded training first-touch
  marginals. Includes input hashes, missing-context accounting, selected global
  targets, and limitations. Context-oracle results are not deployable accuracy.
- `planner.patch`, `source_manifest.json`: initial weighted merge implementation
  and source hashes. Later build plans, commands, hashes and failures are retained
  in the completed campaign archive.
- `kernel_build.json`, `kernel_build.log`, `kernel_modinfo.txt`: successful module
  compile and opcode audit against the running kernel's headers, with warnings.
  Basic runtime checks are separately recorded in `kernel_runtime_smoke.json`.
  Rejected module binaries were removed after recording hashes and results.
- `validation.json`: the initial 11 tool/ABI/ELF/planner checks. Context training
  and NOP-space ELF checks brought the campaign's relevant tests to 16 passing.
  Kernel lifecycle and application measurements are separate from these tests.
- `kernel_initial_build_cleanup.json`, `kernel_initial_source.c`: superseded
  first compile, binary hashes and reconstructed equivalent source record.
- `kernel_intermediate_cleanup.json`: removal of unused intermediate objects
  during initial development.
- `fresh_qualification.json`, `selection.json` and trace training reports: operating
  point selection before PF measurements, held-out path accuracy and coverage,
  the rejected clock join, and verified syscall-return context matching.
- `kernel_screen/`, `kernel_screen_rejection.json`: single-block
  exploration with pool-level CPU accounting. Three T1 policies lacked pool net
  savings; these are negative screen results, not universal impossibility claims.
- `reference_harness.tar.gz` and its manifest: source needed to reconstruct the
  existing workload/platform harness, without inputs or executables.

Completed confirmation and the synthetic cache diagnostic are collected by
`scripts/class_b/collect_evidence.py`. Its `campaign_results.tar.gz` retains
per-arm settings, workload validity, CPU/PMU summaries, controller counters,
trace summaries, build records, negative results, cleanup manifests and platform
restoration records. `campaign_archive_manifest.json` gives every member's source
path, size and SHA-256. Top-level confirmation JSON files expose the predeclared
selection, all rows, final paired intervals and promotion decision without
unpacking the archive. Screen and confirmation data are never pooled.

Original source/input datasets and reference executables are preserved. Newly
generated raw/decoded traces, mapped ELF copies, build objects, duplicate and
rejected executables were removed after retaining compact results and hashes.
Existing reference binaries needed for timing were staged locally using serial,
rate-limited rsync and checked against the retained manifest; timing never used
NAS symlinks. The archive excludes bulk artifacts and credentials.
