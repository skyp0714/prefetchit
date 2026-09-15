# profiling — PEBS/LBR frontend-miss traces (stage 2 input)

Collects `L2I_CODE_RD_MISS`-precise samples with LBR call/branch history on
the Granite Rapids host and turns them into the symbolised dumps that
`llvm_prefetchit/tools/prefetchit_trace_to_plan.py` (profile-guided plans) and
the `static_*_prefetch` evaluators (oracle recall) consume.

```
run_pebs_sampling.sh ──► results/trace/<workload>/<trace>/perf.data
                         │  analyze_pebs_trace.sh / runscript/build/build_pebs_trace_outputs.py
                         ▼
                         lbr_raw_dump.txt, lbr_symbolic_dump.txt, target_branch_counts.csv,
                         hierarchical_miss_report.md, trace_summary.md
```

## Setup

```bash
./setup_venv.sh                       # matplotlib/numpy env from requirements.lock.txt
sudo -v                                # perf needs PMU access (or perf_event_paranoid=-1)
```

Event encodings for Xeon 6787P live in `config/gnr_frontend_perf_events.txt`;
`FRONTEND_RETIRED.*` is not always available through `perf list` on stock
kernels, so the raw `cpu/event=0x24,umask=0x24/` encoding is the default.

## Main flows

```bash
# PEBS + LBR trace (split into l2/mid/itlb/stlb traces) for the Verilator workload
sudo ./run_pebs_sampling.sh --workload verilator-qsort --trace-mode split \
  --duration-l2-sec 60 --sample-period-l2 127 --profile-core 40

# symbolise an existing perf.data (used by the llvm_prefetchit dispatch/static scripts)
./analyze_pebs_trace.sh --data perf.data --out-dir results/trace/x --binary /path/to/bin

# runtime + MPKI profile, N iterations, one core
sudo ./run_detailed_profile.sh --workload verilator-qsort --iterations 3 --profile-core 40

# cross-trace A/B comparison + validation
python3 runscript/build/build_trace_ab_comparison.py --trace-root results/trace/verilator-qsort \
  --trace-names l2_miss,dsb_miss,itlb_miss,stlb_miss --out-md ab_comparison.md \
  --out-csv ab_summary.csv --out-validation-md ab_validation.md
```

`runscript/bench/bench_common.sh` sets up the Verilator/Chipyard environment
(`benchmarks/tools/verilator-5.046-install`, `benchmarks/chipyard`) and is
sourced by `llvm_prefetchit/scripts/static/run_prefetcht1_l2_eval.sh`.
`runscript/build/build_verilator_qsort.sh` builds the simulator
(`CHIPYARD_CONFIG=DualMegaBoomAndSingleRocketConfig`).

Outputs stay under `results/` (ignored); durable conclusions go to
`../docs/`.

## Archive

`archive/` keeps the phase-1 frontend characterisation (JVM context-switch,
kernel idle/busy, SPEC single-thread screens) and the pre-LLVM-pass
source-patching pipeline (`prepare_prefetch*_variants.py`,
`run_prefetchit_eval_pipeline.sh`). They are superseded by the LLVM pass flow
and kept only for provenance.
