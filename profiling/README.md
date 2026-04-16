# Profiling Layout

- Main scripts (`profiling/`)
  - `run_profile_all.sh`
  - `run_jvm_profiling.sh`
  - `run_jvm_thread_scaling.sh`
  - `run_kernel.sh`
- `runscript/bench/`: benchmark runners + perf invocation helpers
- `runscript/build/`: build + CSV aggregation scripts
- `runscript/plot/`: plotting scripts
- `config/`: experiment config
  - `gnr_frontend_perf_events.txt`
  - `benchmarks.txt`

# Results Layout

- `results/benchmark_profiling/csv`
- `results/benchmark_profiling/png`
- `results/jvm_context_switch/csv`
- `results/jvm_context_switch/png`
- `results/kernel/csv`
- `results/kernel/png`
- logs stay in `results/logs`

# Main Flow

```bash
cd profiling
./setup_venv.sh
sudo PROFILE_CORE=1 ./run_profile_all.sh
```

Notes:
- unified benchmark list is `config/benchmarks.txt` (JVM + Verilator + SPEC together)
- if `benchmarks.txt` includes Verilator, set `CHIPYARD_CONFIG=<your BOOM config>` first
- `run_profile_all.sh` writes:
  - main CSV to `results/benchmark_profiling/csv/main_frontend_all.csv`
  - frontend PNGs to `results/benchmark_profiling/png`
  - JVM core0 comparison PNG to `results/jvm_context_switch/png`

# JVM Context Switch

```bash
cd profiling
sudo ./run_jvm_thread_scaling.sh
./run_jvm_profiling.sh
```

# Kernel Idle/Busy

```bash
cd profiling
sudo ./run_kernel.sh
```
