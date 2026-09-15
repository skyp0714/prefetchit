# JIT PrefetchIT experiments

This source-only repository contains the HotSpot C2 instruction-prefetch
patches, JVM workload drivers, JCodeStream sources, WideApi generator, compact
result CSVs, and the experiment record in `docs/PLAN.md`.

OpenJDK is intentionally not vendored. The umbrella migration bootstrap clones
the pinned `jdk17u-dev` commit into `jit_prefetch/openjdk` and applies the saved
combined patch. DaCapo, Renaissance, Trino distributions, build trees, classes,
JARs, perf traces, and logs are regenerated on the destination server.

Clone this repository as `jit_prefetch` under the umbrella PrefetchIT directory.
Scripts derive their paths from that layout. Override `JDK`, `DACAPO`, `REN`, or
`PREFETCHIT_ROOT` when using a different installation layout.

Typical source regeneration:

```bash
cd jcodestream
javac *.java

cd ../wideapi
python3 gen_wideapi.py 4000 src
mkdir -p classes
javac -d classes src/*.java
```

Entry points (`scripts/`):

- `ab_jcs.sh` — JCodeStream A/B (`CONFIGS="stock=;v4_128x32=..."`, `CORE=`, `ITERS=`).
- `ab_jvm_suite.sh` — DaCapo/Renaissance A/B (`SUITE=`, `BENCH=`, `CONFIGS=`, `CORES=`),
  replaces the per-workload `archive/scripts/ab_*.sh`.
- `screen_full_suites.sh`, `screen_renaissance.sh` — L2I/L1I MPKI screens.
- `../wideapi/ab_wideapi.sh` — WideApi fixed-capacity QPS A/B.

The HotSpot flags added by `patches/` (all default off): `PrefetchEntryAhead`,
`PrefetchEntryLines`, `PrefetchEntryMinBytecode`, `PrefetchEntryIT0` (V4),
`PrefetchRetTarget`/`PrefetchRetTargetLines`/`PrefetchRetTargetAhead` (V1/V3),
`PrefetchCallTarget` (V2). Deployable default: V4 with `MinBytecode=256`.

Scripts call `perf stat` directly; set `PERF="sudo perf"` (after `sudo -v`) when
`kernel.perf_event_paranoid` is not -1. No password is embedded anywhere.
Use the fixed-frequency, affinity, warmup, and interleaved A/B protocol in
`llvm_prefetchit/migration/REPRODUCIBILITY.md` for accepted measurements.
