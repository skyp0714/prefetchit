# Split75 follow-up experiments

Four independent, completed 16-trial campaigns use fresh full Media compose-review C4 stacks, including MovieId, on eight workload CPUs. Clean endpoint timing precedes PMU collection. Campaigns are not pooled.

| Campaign | Change | Direct results |
|---|---|---|
| A / hybrid_screen | New split75 plus an early T1/IT0 burst, with matching gates and layout | [Report](hybrid_screen/report.md) |
| B / lead_screen | Residual-target displacement changes and earlier retired-LBR placement | [Report](lead_screen/report.md) |
| D / l1_screen | Fixed supplemental NOP/T1/IT0 slots selected from L1I profiles | [Report](l1_screen/report.md) |
| E / latency_screen | Retarget 21 existing supplemental T1 displacements using long frontend-stall profiles | [Report](latency_screen/report.md) |

Conditional original-baseline confirmations were not run when their frozen qualification criteria were not met. Original-only and top-down-quality aborted attempts remain in the evidence. The detailed [diagnosis](diagnosis/report.md) separates event populations, CPU scopes, modeled coverage, and causal limits.

[manifest.json](manifest.json) lists hashes for compressed bundles, sparse observations, and figures. Text bundles under `artifacts/` are gzip-compressed JSON dictionaries mapping original relative paths to byte-exact UTF-8 text. Sparse observation files are gzip-compressed JSON lists. The publisher verified text round trips and hashes. Source snapshots retain all 22 exact source revisions requested by the experiment and reporting records, including historical Git versions.

The `campaign.json.gz` bundle includes final policy decisions and cleanup records. Rejected executables and decoded traces were removed after preserving measurements, commands, settings, source, selection/patch records, hashes, and exclusion reasons. Original and split75 reference/control artifacts remain outside this archive. No executables, raw traces, benchmark input datasets, or container environments are published here.

[platform_restoration.json](platform_restoration.json) records 2,808 matching restoration checks across experiments and diagnostics. Individual paired-log t95 intervals have no multiplicity correction. This is a fixed C4 comparison near 85% CPU utilization, not a maximum-throughput sweep or all-API DSB validation.
