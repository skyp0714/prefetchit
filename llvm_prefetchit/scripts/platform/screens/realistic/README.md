# Realistic-setting screening campaign (2026-09-18)

Rule (user): every server workload runs pinned to a few dedicated cores and is loaded until those cores are close to saturation
(70–90 % busy); batch/JVM workloads run pinned with the JVM's pools sized from the affinity mask. Counters are user-mode
(`cpu/event=0x24,umask=0x24/u` = L2 code read misses, `instructions:u`, `cycles:u`) over a 30 s steady window. A workload qualifies
for prefetch work when its L2I MPKI is >= 1 at the realistic operating point.

Scripts (copies of `llvm_prefetchit/results/realistic_screen_20260918/*`, where the CSV/log outputs live):
- `jvm_realistic_screen.sh` — DaCapo 23.11 + Renaissance 0.16.1, JDK 21, -Xms/-Xmx 8g, `CORES=8-11` (4) / `8-15` (8); `chain_jvm2.sh` reruns JDK-21-incompatible ones with `-Djava.security.manager=allow` and does the 8-core pass.
- `pg_realistic_screen.sh`, `mariadb_realistic_screen.sh` — server on 4 cores, client sweep (pgbench tpcb/select; sysbench rw/ro, durable/fast).
- `musuite_realistic_sweep.sh` — Router / SetAlgebra / HDSearch on 4 cores, open-loop qps sweep.
- `dsb_realistic_screen.sh` — any DeathStarBench stack (`PREFIX`, `URL`, `LUA`): sizes each container's cpuset from its CPU share at a base rate, then sweeps the rate and counts misses per container cgroup in one perf run; `hotel_mixed.lua` for hotelReservation.
- `cloudsuite_realistic.sh` — CloudSuite 4 data-caching / web-serving / media-streaming / web-search / data-serving with the server container on 4 cores.
- `dcperf_runs.sh` — DCPerf default jobs as shipped (whole machine), system-wide and per-process user-mode counters during the steady phase; `dcperf_install_chain.sh` + `shim/sudo` (non-interactive sudo, drops the `clang` meta-package).
- `utl_load_sweep.sh`/`utl_read.lua` live in `flat_codegen/dsb_build/postlink/` (user-timeline operating-point sweep).
