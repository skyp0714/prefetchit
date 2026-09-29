# Type B mechanism experiments

Original measurements are retained at `/storage/prefetchit/class_b_mechanism_20260928`.
The report is [class_b_mechanism_20260929.md](../../../../docs/class_b_mechanism_20260929.md).

Clean E2E trials and perturbing PMU/wake profiles are separate. The long same-stack
write crossover is excluded from causal E2E claims because the repeated NOP
control drifted as review arrays grew. Completed and partial observations, the
exclusion reason, and restoration records are retained.

`completed_native_manifest.json` covers the completed 20-run native validation
and earlier screens. `completed_records/manifest.json` adds 28 verified compact
bundles/files (7,988 measurement, settings, quality, patch, exclusion and cleanup
records, plus compressed selector inputs), including all 12 completed native
wake captures. The native-only archive excludes active backend/call-path work;
those phases are not claimed complete here. No executable, original input
package, decoded trace, or NAS artifact is stored in this evidence directory.
