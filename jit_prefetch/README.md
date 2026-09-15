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

Run `sudo -v` before scripts that profile with `perf`; no password is embedded.
Use the fixed-frequency, affinity, warmup, and interleaved A/B protocol in
`llvm_prefetchit/migration/REPRODUCIBILITY.md` for accepted measurements.
