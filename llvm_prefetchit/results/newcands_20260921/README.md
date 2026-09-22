# 2026-09-21 candidates: screened and classified (A = capacity, B = interleaving)

Setting (the valid one of `docs/prefetch_plan_by_miss_class.md` §0): cores pinned, deep C-states disabled on the measured cores,
clock frozen at 2 GHz (`freeze_platform.sh MODE=2ghz`, `performance`, no turbo), user-mode counters only
(`cpu/event=0x24,umask=0x24/u` = L2 code-read miss, `instructions:u`, `cycles:u`), load generators on cores 60-67.
Operating point per workload = the highest-MPKI load with utilization >= 15% (the rule in `feedback-reporting-format`), other loads kept
in `services.csv` / `batch.csv`. Utilization: per-process from `task-clock` (batch), per-container from `docker stats` (services), and
from user cycles / (cores x window x 2 GHz) where perf ran system-wide (a system-wide `task-clock` counts idle CPUs too).

## A: capacity (pinned, alone, C6 off)

| workload | config | L2I MPKI | util | IPC | class |
|---|---|---:|---:|---:|---|
| **ARM core-benchmarks `frontend` dfs_chase, depth 16** (65k functions, 9.0 MB text, gcc -O0) | 1 core | **72.1** | 100% | 0.47 | **A, top tier** |
| **ARM core-benchmarks `frontend` inst_pointer_chase, 3000 chains x depth 20** (60k functions, 6.7 MB text) | 1 core | **48.9** | 100% | 0.41 | **A, top tier** |
| ARM `frontend` inst_pointer_chase at the upstream defaults (1000 chains, 20k functions, 2.25 MB text) | 1 core | 2.31 | 100% | 0.63 | A (borderline: the default footprint is the size of L2) |
| **MySQL 8.0 (docker), sysbench oltp_read_write** 16 tables x 200k, 16 threads, durable | 4 cores | **2.35** | 75% | 1.45 | **A** (2-3x MariaDB 10.11's 0.8-1.1 on the same harness) |
| **Rails 8 API + puma** 4 workers x 8 threads, CRuby 3.2 (no YJIT), production, MySQL backend | 4 cores | **1.91** | 38% | 1.34 | **A** (second sample of the AOT-interpreter class next to Django/CPython 2.4) |
| ScyllaDB 6.2 (Seastar, shard-per-core), YCSB workloada, 1M records | 4 cores | 0.40 | 33% | 1.46 | out of A (see B) |
| Renaissance finagle-http (JDK 21) | 4 cores | 0.26 | 92% | 2.36 | out (JIT) |
| OpenMM 8.6 CPU platform, 12k-particle LJ fluid, 4 threads | 4 cores | 0.01 | 84% | 1.78 | out |

Rates measured (MPKI): Scylla 5k/20k/60k/200k ops/s = 0.50 / 0.40 / 0.37 / 0.36; MySQL 200/1k/4k/unlimited = 3.56 / 2.35 / 2.33 / 2.33;
Rails 200/800/3000 rps = 1.88 / 1.91 / 1.59 (2209 rps achieved at the last point).

## B: interleaving (the same service, sharing one 4-core cpuset with another tenant, C6 off)

| service | alone | interleaved | factor | co-tenant |
|---|---:|---:|---:|---|
| **ScyllaDB** | 0.40 | **6.05** / **10.97** | 15x / 27x | MySQL 8 (sysbench 400/s) / Rails (800 rps) |
| **MySQL 8** | 2.35 | **9.25** | 3.9x | ScyllaDB (YCSB 20k) |
| **Rails + puma** | 1.91 | **3.48** | 1.8x | ScyllaDB (YCSB 20k) |

Each service kept the same per-service utilization as in its alone run (Scylla 33%, MySQL 21%, Rails 39%), so the jump is eviction by
the neighbour between requests, not a load change. This reproduces the DeathStarBench pattern on stock server software: a service whose
own code fits L2 when it owns the core (Scylla 0.40) becomes the *worst* of the three once it shares one (10.97).

## Not measured, and why

| candidate | status |
|---|---|
| GHDL LLVM backend (flattened simulator, A candidate) | `apt install ghdl-llvm` is blocked on this host: `libgnat-13` wants `gcc-13-base 13.3.0-6ubuntu2~24.04.1` but a PPA has `13.4.0-6ubuntu1~22~ppa2` installed. Needs a source build of GHDL (hours) or the PPA removed (shared host) |
| BenchBase (Java OLTP suite, the BTB-Ferret paper's BTB-heaviest set) | needs JDK 23 (`<java.version>23</java.version>`); host has 21 and 17, and JDK 21 fails the build. JIT reference value only |
| HHVM drupal/wordpress/mediawiki (Twig / BTB-Ferret set) | HHVM is a JIT: out of the AOT pass's reach by construction; the php-fpm 8.3 + WordPress measurement (1.15 MPKI) stands in for the PHP class |
| Ceph OSD | needs a cluster; ~1 day of setup |

## Files
`services.csv` (Scylla / MySQL / Rails, all rates and both regimes), `batch.csv` (single-process workloads), `logs/`,
`svc_screen.sh` (pinned service + rate sweep), `batch_screen.sh` (single process), `colocate.sh` / `colocate_rails.sh` (B regime),
`build_armfe.sh` (ARM frontend generation + build), `openmm_bench.py`, `rails_screen.sh`.
