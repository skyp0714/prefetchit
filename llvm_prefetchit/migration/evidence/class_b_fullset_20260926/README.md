# Five-service Class B and kernel emission evidence

The [report](../../../../docs/class_b_fullset_20260926.md) separates whole CPU,
user CPU time, historical user-cycle results, exploratory screens and fresh
confirmations. Positive values mean cost reduction per completed external request.

| Implementation | Source | Evidence |
|---|---|---|
| Five-service trace coverage policy, exact-layout NOPs | [drivers](../../../scripts/class_b/README.md) | `results.json`, `confirmation_rows.json`, `protocols.json`, `builds.json` |
| Selected-next-task budgets, spacing, groups, split phases and T0/T1 | [kernel module](../../../kernel/wake_prefetch/README.md) | `kernel_screen.json`, `selection_amendment.json`, kernel section in `results.json` |
| Temporal trace admission and coverage | [training and capture drivers](../../../scripts/class_b/README.md) | `trace_validation.json`, `operating_points.json`, `exclusions.json` |
| Separate cache warmth and switch-completion delay diagnostics | [kernel module](../../../kernel/wake_prefetch/README.md) | `diagnostics.json` |
| Post-hoc user/kernel CPU decomposition | [report collector](../../../scripts/class_b/fullset_report.py) | `user_cpu_breakdown.json` |

Media changes three services together; Social changes two. Seven fresh seeded
blocks compare baseline, retained artifact reference, new NOP and new prefetch
bundles. The independent kernel confirmation uses seven fresh processes with
rotated off/NOP/prefetch phases. Intervals are individual 95% paired-log t
intervals without multiplicity correction. Each family also has one-arm-at-a-time
screens and separate PMU diagnostics, retained in the local archive.

MovieId passed the target retention rule. ComposeReview, Rating, ComposePost,
UserTimeline and the tested kernel finalist did not establish incremental net
savings under their promotion rules. Rejected generated executables were removed;
original inputs, source, existing references and the MovieId candidate/NOP remain.
This retention decision does not establish a separately tested mixed deployment.

MovieId's historical approximately 5.1% saving is user cycles against its old
baseline. This campaign's user CPU-time saving against its new baseline is 4.88%,
while whole CPU saving is 1.26%. Comparing against the old p11a artifact also
includes build differences. These gains must not be added or substituted for
whole-stack savings. The 10% whole-CPU target was not achieved.

`validation.json` records 9 ABI tests, 3 trace admission tests, 17 original-module
runtime checks and 17 NOP-module runtime checks, along with the initial missing
pytest environment failure. `platform_restoration.json` retains all 3,636
before/restored comparisons. The final experiment containers and module were
removed. `source_manifest.json` gives source hashes and the Git revision before
this result commit; actual measurement protocols retain their execution hashes.

Only these compact JSON summaries and this README are published. The detailed
archive is local at `/storage/prefetchit/class_b_fullset_20260926/evidence_archive/`.
`archive_reference.json` gives its archive/manifest hashes and member count.
It includes compact per-run CPU/PMU measurements, commands, build records,
negative results, trace summaries and cleanup manifests. It excludes executable
binaries, objects, raw/decoded PT, mapped ELF copies and original datasets.
Generated plans, service logs and the compressed archive are not committed.
