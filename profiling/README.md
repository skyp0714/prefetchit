# Profiling Layout

- `runscript/`: benchmark run scripts + parsing helpers
- `config/`: counter/workload config
- `results/`: measured CSV, logs, and PNG outputs
- `required_package.txt`: python package list for the profiling venv

# Main Flow

1) Create/update venv:

```bash
cd profiling
./setup_venv.sh
```

2) Run full profiling flow (4 app benchmarks + SPEC 602/605/641):

```bash
cd profiling
PROFILE_CORE=1 PCM_CORE_BIN=/abs/path/to/pcm-core ./run_profile_all.sh
```

# Useful Knobs

```bash
RUN_SPEC_BUILD=1        # build SPEC intspeed before run (default: 1)
APP_SAMPLE_INTERVAL=1   # pcm-core sampling period for app benchmarks (sec)
APP_WARMUP_SAMPLES=60   # drop initial app samples for steady-state MPKI
SPEC_SAMPLE_INTERVAL=0  # 0: end-to-end, >0: periodic samples for SPEC
SPEC_SIZE=test          # optional quick sanity override for SPEC run scripts
```
