# llvm_prefetchit/archive

One-off campaign drivers and negative-result sweeps, moved out of `scripts/`
and `tools/` on 2026-09-15 so the live flow is readable. Everything here still
runs from its new location only if its relative paths are fixed; treat it as
provenance for the numbers quoted in `../../docs/archive/`.

| directory | contents |
|---|---|
| `scripts/` | MicroSuite (Router/SetAlgebra/HDSearch/Recommend), TailBench, PostgreSQL, proto-arena, SPEC2026 sweeps; the June–August Verilator autotune/plateau/overnight watchdog drivers; `run_paper_goal_*_20260815.sh` campaign scripts; `configure_fixed_frequency{,_v2}.sh` (replaced by `scripts/platform/freeze_platform.sh`) |
| `tools/` | campaign report generators, MicroSuite helpers (`populate_router_memcached.py`, `grpc_core_cap.c`), DSB wave-7 planners (`make_burst_plan.py`, `make_dso_anchor_plan.py`), plot scripts for the retired sweeps |
| `work/pg_tpcc_variants/`, `workloads/postgresql/` | PostgreSQL TPC-C/TPC-B experiment inputs (negative case) |
| `experiments/` | MicroSuite static-gRPC early-init shims |
| `patches/` | MicroSuite HDSearch determinism patches |
