# PrefetchIT reproducibility contract

This is the handoff document for deciding whether a new server has reproduced
the project. It intentionally separates current controlled results from older
exploratory peaks. Paths are relative to the umbrella `prefetchit` checkout.

## Acceptance levels

1. **Source restore:** `migration/verify.sh --source-only` passes, every first-party checkout
   matches `repos.lock.tsv`, archives match SHA-256, and every local third-party
   patch applies to the revision in `benchmarks.lock.tsv`.
2. **Pipeline restore:** the LLVM pass smoke test passes; one PEBS+LBR sample is
   decoded; a plan is generated; and `objdump` confirms injected prefetches.
3. **Performance restore:** frequency, affinity, workload completion, binary
   identity, and NOP-layout controls are recorded. Direction should reproduce;
   exact speedup is host-specific. Do not compare raw MPKI across different CPU
   event definitions without first validating the event semantics.

## Canonical results

The machine-readable form is `core_results.tsv`. These are the latest results
that survived the fixed-frequency and matched-binary audits.

| workload | mechanism | controlled result | key setting |
|---|---|---:|---|
| Verilator qsort | profile-free static LLVM plan | **1.080x runtime** | 3.8 GHz core, pinned uncore, core 40, 100k cycles, 3 reps, top1k callsite |
| Verilator qsort | LBR-PGO LLVM plan | **1.076x runtime** | same baseline/protocol, RET cov90 |
| Django | manual future method-pointer prefetch | **1.490x QPS**, MPKI 84.6 to 35.0 | `d4_next`, 3 paired reps, all threads audited and pinned |
| FeedSim | manual future method-pointer prefetch | **1.073x QPS**, MPKI 8.07 to 1.71 | 200M I-cache iterations, 2 CPU threads, d16, 300 s, 3 reps |
| arcilator MegaBoom | static IR callsite prefetch | **1.051x runtime**, MPKI 76.7 to 71.2 | stride 4, lookahead 16, matched NOP binary, 15 interleaved reps |
| JCodeStream | HotSpot C2 V4 entry burst | **1.285x runtime** | ahead 128, 32 lines, 5 reps; 93.2 baseline MPKI |
| WideApi | gated HotSpot C2 V4 entry burst | **1.110x QPS** | 4,000 handlers, min bytecode 256, 5 reps |

The canonical source data are:

- `llvm_prefetchit/migration/evidence/` (small final CSVs copied out of ignored result trees)
- `llvm_prefetchit/results/paper_goal_20260815/FINAL_REPORT.md`
- `llvm_prefetchit/results/paper_goal_20260815/CONFIG_LOG.md`
- `flat_codegen/docs/PLAN.md`
- `jit_prefetch/docs/PLAN.md`, `jit_prefetch/results/jcs3_final.csv`, and
  `jit_prefetch/results/wideapi_confirm.csv`

The latest short Verilator values have summary-level evidence only; see
`migration/evidence/README.md`. Django and FeedSim retain every accepted raw
paired row and their affinity/migration audit fields.

### Results that are evidence, but not acceptance targets

- The old Verilator static 1.226x and PGO 1.257x runs were uncore-DVFS
  confounded. The default-OS effect is real deployment behavior, but it is not
  the isolated prefetch effect.
- Router 2.98x was a `_noomp` baseline/build mismatch; matched NOP reruns were
  0.983x. HDSearch and SetAlgebra July peaks also failed matched reruns.
- The old Django 2.36x, FeedSim 1.21-1.31x, and memcached 1.15x rows predate the
  frozen-platform audit. Django and FeedSim remain positive above; memcached is
  neutral in the controlled harness.
- SPEC CPU2026 (maximum about 0.6 L2I MPKI) and gem5 SE (about 0.001 MPKI) are
  screen/exclusion results, not optimization targets.

## Reference machine and measurement protocol

See `HOST_REFERENCE.md` and `kernel-6.0.0.config`. The original host was an
Intel Xeon 6787P, 86 physical cores without SMT, with 64 KiB L1I, 2 MiB private
L2, and 336 MiB shared L3. LLVM/Clang 19.1.7 and Verilator 5.046 were used.

For a performance run:

1. Run only one workload at a time.
2. Assign every server/client/helper thread to a distinct physical core and
   save `taskset -apc` plus sampled `/proc/<tid>/stat` processor IDs.
3. Use `scripts/configure_fixed_frequency_v2.sh`; record core and uncore
   state before and after. Use 3.8 GHz mode for single-core Verilator and a
   sustainable fixed mode for multicore services.
4. Interleave A/B (or AB/BA), use at least 3 reps and 5 for services. Compare
   injected binaries with layout-identical NOP-patched binaries when possible.
5. Validate equal completed work, zero/acceptable failures, the expected
   prefetch count in `objdump`, and no CPU migrations before accepting timing.
6. Record the exact binary SHA-256, command, environment, core list, kernel,
   microcode, governor/EPP/turbo, and PMU event encoding with every run.

The Granite Rapids L2 instruction-miss event used by the project is generally
`cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/`. Validate it on the new CPU;
do not assume the raw encoding is portable.

## Destination-server command sequence

Start from an Ubuntu 22.04/24.04 host with GitHub SSH access:

```bash
mkdir -p "$HOME/work" && cd "$HOME/work"
git clone git@github.com:skyp0714/prefetchit.git
cd prefetchit
git clone git@github.com:skyp0714/llvm_prefetchit_injection.git llvm_prefetchit

# Review before running because this installs host packages and Docker.
llvm_prefetchit/migration/install_host_deps_ubuntu.sh

# Restore every first-party repository at its pinned, tested commit.
llvm_prefetchit/migration/bootstrap.sh --root "$PWD"

# Restore pinned third-party source and all unpublished source modifications.
llvm_prefetchit/migration/bootstrap.sh --root "$PWD" \
  --with-benchmarks --apply-patches

# Install SPEC CPU2017/2026 from licensed media, then copy PrefetchIT configs.
llvm_prefetchit/migration/bootstrap.sh --root "$PWD" --copy-spec-configs

# Recreate the analysis environment and LLVM pass.
profiling/setup_venv.sh
cmake -S llvm_prefetchit -B llvm_prefetchit/build \
  -G Ninja -DLLVM_DIR="$(llvm-config-19 --cmakedir)"
cmake --build llvm_prefetchit/build -j"$(nproc)"
llvm_prefetchit/tests/smoke/run_smoke.sh llvm_prefetchit/build
python3 -m pytest llvm_prefetchit/tests

# Source-level gate first; the second command additionally validates host tools.
llvm_prefetchit/migration/verify.sh --root "$PWD" --source-only
llvm_prefetchit/migration/verify.sh --root "$PWD"
```

Install the exact external versions in `tools.lock.tsv` before full benchmark
reproduction. In particular: Verilator 5.046, the recorded CIRCT bundle,
Temurin 17.0.18+8, GraalVM CE 17.0.9, DaCapo 23.11-MR2, Renaissance 0.16.1,
and a `perf` binary matching the destination kernel.

## Minimal end-to-end PGO check

After building a workload binary, collect at least three profiles. LBR[0].to is
the miss target and older entries provide candidate injection sites.

```bash
cd "$HOME/work/prefetchit"
sudo -v
sudo profiling/run_pebs_sampling.sh \
  --workload verilator-qsort --trace-mode split \
  --duration-l2-sec 60 --sample-period-l2 127 --profile-core 40

python3 llvm_prefetchit/tools/prefetchit_trace_to_plan.py --help
# Invoke it with the new trace directory and baseline binary, then build via
# the workload-specific build script recorded under llvm_prefetchit/scripts/.

objdump -d /path/to/injected-binary | rg -c 'prefetcht1|prefetchit[01]'
```

Use `docs/prefetch_experiment_variables.md` for plan fields and
`migration/README.md` for what is intentionally regenerated. A migration is
not performance-complete merely because source verification passes.
