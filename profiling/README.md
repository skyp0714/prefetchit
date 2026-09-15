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

`setup_venv.sh` installs the captured environment from `requirements.lock.txt`.
Set `PROFILING_REQUIREMENTS` to use another requirements file.

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

# Verilator Detailed Profile

```bash
cd profiling
sudo ./run_detailed_profile.sh --workload verilator-qsort --iterations 3 --profile-core 0
```

Outputs: `results/detailed_profile/<workload>/`

# PEBS + LBR Trace (Frontend 4-way Split)

```bash
cd profiling
sudo ./run_pebs_sampling.sh --workload verilator-qsort --trace-mode split --duration-sec 60 --profile-core 0
```

Per-trace tuning (for sparse ITLB/STLB events) is supported:

```bash
sudo ./run_pebs_sampling.sh \
  --duration-l2-sec 60 --duration-mid-sec 20 --duration-itlb-sec 150 --duration-stlb-sec 150 \
  --sample-period-l2 127 --sample-period-mid 511 --sample-period-itlb 31 --sample-period-stlb 31
```

Default split traces:
- `frontend_retired.l2_miss:upp`
- `frontend_retired.dsb_miss:upp` (auto fallback when `l3_miss` alias is unavailable)
- `frontend_retired.itlb_miss:upp`
- `frontend_retired.stlb_miss:upp`

Outputs: `results/trace/<workload>/<trace_name>/`
- `l2miss_profile.data`
- `lbr_raw_dump.txt`
- `lbr_symbolic_dump.txt`
- `branch_type_distribution.csv`
- `target_branch_counts.csv` (miss target x branch type count table)
- `hierarchical_miss_report.md` (symbol/srcfile/lines 계층 리포트)
- `hierarchical_miss_report.txt` (legacy mirror)
- `detailed_trace_report.md` (상세 리포트)
- `trace_summary.md` (핵심 요약)

Cross-trace outputs are auto-generated under `results/trace/<workload>/` when `--trace-mode split --run-analyze 1`:
- `ab_comparison.md`
- `ab_summary.csv`
- `ab_validation.md`
- `top10_target_branch_stacked_detail.png` (각 {miss,branch} local Top10 + Others, 절대비율)
- `top10_target_branch_stacked_detail.csv` (detail plot source + local top target names)
- `top10_target_branch_stacked_merged.png` (각 {miss,branch} Top10 합산 + Others, 절대비율)
- `top10_target_branch_stacked_merged.csv` (merged plot source)

Cross-trace A/B comparison + validation:

```bash
python3 runscript/build/build_trace_ab_comparison.py \
  --trace-root results/trace/verilator-qsort \
  --trace-names l2_miss,dsb_miss,itlb_miss,stlb_miss \
  --out-md results/trace/verilator-qsort/ab_comparison.md \
  --out-csv results/trace/verilator-qsort/ab_summary.csv \
  --out-validation-md results/trace/verilator-qsort/ab_validation.md
```
