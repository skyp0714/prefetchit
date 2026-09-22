# jit_prefetch/archive

- `scripts/ab_*.sh`: per-workload DaCapo/Renaissance A/B drivers, replaced by
  the parameterised `scripts/ab_jvm_suite.sh` (`SUITE=`, `BENCH=`,
  `CONFIGS=`, `CORES=`). Kept because `results/*.csv` were produced by them.
- `trino/`: Trino TPC-H staging config (screened at 0.75–1.71 L2I MPKI —
  below the technique's operating window; see `docs/PLAN.md`).
