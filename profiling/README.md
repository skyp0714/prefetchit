# Profiling Layout

- `runscript/`: benchmark run scripts + perf/parse helpers
- `config/`: perf events + workload config
- `results/`: measured CSV, logs, and PNG outputs
- `required_package.txt`: python package list for venv

# Main Flow (perf stat)

```bash
cd profiling
./setup_venv.sh
sudo PROFILE_CORE=1 ./run_profile_all.sh
```

Notes:
- this machine uses `perf_event_paranoid=4`, so root is required for perf counters.
- warmup-skipping is done by `PERF_DELAY_MS=<ms>` in workload config lines.
- main outputs are:
  - `results/main_frontend_all.csv` (single source of truth for main MPKI rows)
  - `results/frontend_l1i_l2_mpki_jvm1c.png`
  - `results/frontend_itlb_stlb_mpki_jvm1c.png`
  - `results/frontend_l1i_l2_mpki_jvm86c.png`
  - `results/frontend_itlb_stlb_mpki_jvm86c.png`
  - `results/main_jvm_core0_cmp_l1i_l2.png` (1c vs 86c, read from `main_frontend_all.csv`)
- finagle settings are tuned for steady-state MPKI:
  - use `GraalVM CE 17` (`benchmarks/tools/graalvm-ce-java17/bin/java` by default)
  - enable `-XX:+PrintCompilation` in log
  - delay perf start by `PERF_DELAY_MS=180000` (about 3 min warmup)
- for `verilator` on Chipyard BOOM:
  - install Chipyard at `benchmarks/chipyard`
  - set `CHIPYARD_CONFIG` to your large multi-core BOOM config class (>=2 BOOM cores)
  - build first: `CHIPYARD_CONFIG=<...> ./runscript/build_verilator_qsort.sh`
  - measured runs only execute simulation and reject `FORCE_REBUILD=1`.

# Config Files

- `config/perf_events_frontend_mpki_gnr.txt`: alias + raw perf event specs
- `config/workloads_bench4_singlecore.txt`: 4 benchmarks (with per-workload delay)
- `config/workloads_spec_singlecore.txt`: 3 SPEC workloads

# Context-Switch Experiments

- core0 MPKI comparison plot (uses `main_frontend_all.csv`, no duplicate MPKI CSV):

```bash
cd profiling
CORE_SMALL=1 CORE_LARGE=86 ./runscript/run_ctxswitch_core0_mpki.sh
```

- thread scaling (single CSV + two plots, fixed 1-minute measurement):

```bash
cd profiling
sudo ./runscript/run_ctxswitch_thread_scaling.sh
```

Outputs:
- `results/contextswitch_thread_scaling.csv`
- `results/contextswitch_percore_threads.png` (thread scaling)
- `results/contextswitch_core0_mpki.png` (MPKI comparison)
- `results/contextswitch_frequency_vs_cores.png` (Core0 count/frequency side-by-side)

Notes:
- context-switch experiments default to `user-only` perf counting (`--all-user`).
- override with `PERF_USER_ONLY=0` if you intentionally want user+kernel.
- `.perfraw` files are deleted automatically after CSV rows are written.
- If you want to keep raw perf files in `perfinvoke.py`, use `--keep-perfraw`.

# Kernel Idle/Busy (All-Kernel)

Use this script to compare kernel frontend MPKI with and without a frontend-heavy workload:

```bash
cd profiling
sudo ./runscript/run_kernel_idle_busy.sh
```

Default behavior:
- kernel-only counting (`--all-kernel`)
- cores `0-85`
- busy workload: `tomcat` pinned to `0-85` with `ActiveProcessorCount=86`

Outputs:
- `results/kernel_idle_busy.csv`
- `results/kernel_idle_busy.md`
