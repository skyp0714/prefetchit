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
