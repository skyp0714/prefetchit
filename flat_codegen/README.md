# Flat-codegen PrefetchIT experiments

This source-only repository contains the arcilator and DeathStarBench tooling
used by PrefetchIT. Generated LLVM/MLIR, binaries, dependency libraries,
containers, traces, and raw logs are deliberately excluded.

Clone it as `flat_codegen` under the umbrella PrefetchIT directory. Scripts
derive `PREFETCHIT_ROOT` from that layout; it can also be exported explicitly.
The pinned CIRCT tools, Chipyard/DeathStarBench source, LLVM pass, and benchmark
patches are restored by `llvm_prefetchit/migration/bootstrap.sh`.

Key evidence is in `docs/PLAN.md` and the small CSV files under `results/`.
Arcilator inputs under `work/` are generated from pinned Chipyard FIRRTL; the
small C drivers and state descriptions needed by that process remain tracked.

Before privileged profiling or Docker commands, run `sudo -v`. No script stores
a password. Result-producing runs should follow the affinity, fixed-frequency,
and same-binary NOP protocol in
`llvm_prefetchit/migration/REPRODUCIBILITY.md`.
