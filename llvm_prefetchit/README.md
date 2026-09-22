# llvm_prefetchit — the pass, the plan tools, and the measurement harness

Stage-2 hub of the PrefetchIT flow (see the umbrella `README.md`), and home
of the stage-3 DCPerf harness. Migration manifest: `migration/`.

```
profiling/ PEBS+LBR trace ──► tools/prefetchit_trace_to_plan.py ──► prefetchit.plan.v1 (targets + sites)  [profile-guided]
static_*_prefetch/ planners ─────────────────────────────────────► prefetchit.plan.v1                         [profile-free]
                                                                          │
                     opt-19 -load-pass-plugin build/PrefetchITPass.so -passes=prefetchit-inject -prefetchit-plan=...
                                                                          ▼
                     rebuilt workload  ──► tools/make_nop_control_binary.py (layout twin) ──► paired A/B (scripts/)
```

## Build and test

```bash
cmake -S . -B build -G Ninja -DLLVM_DIR="$(llvm-config-19 --cmakedir)" \
  -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19
cmake --build build
tests/smoke/run_smoke.sh build          # toy C file → inject → validate IR + asm
python3 -m pytest tests                  # plan tools
```

LLVM 19 is required (`CMakeLists.txt` refuses anything else). Default
mnemonic is `prefetcht1`; `prefetcht2/t0/nta` and `prefetchit0/1` are
selectable (`-prefetchit-mnemonic=`). Design and plan schema: `docs/design.md`,
variable reference: `docs/prefetch_experiment_variables.md`.

## Layout

| path | purpose |
|---|---|
| `lib/PrefetchITPass.cpp` | the pass: resolves plan sites by function + debug location + branch type, emits `prefetcht1 sym+off(%rip)` inline asm (exact symbol-offset mode) or `blockaddress` fallback; GOT-anchored operands for DSO targets |
| `tools/` | `prefetchit_trace_to_plan.py` (trace → plan, coverage/depth/site policies), `merge_prefetch_plans.py`, `select_prefetch_plan_injections.py`, `prune_plan_by_residual_targets.py`, `apply_target_aware_offsets.py`, `prefetchit_external_got_plan.py`, `validate_prefetch_asm.py`, `resolve_plan_layout_shift.py` + `reanchor_prefetch_targets.py` (post-link: anchor targets on call order — required, see docs/design.md), `check_prefetch_drift.py` (operand vs real continuation gate), `make_nop_control_binary.py`, `mask_prefetch_instructions.py`, `compare_static_plan_to_pgo.py`, `summarize_*`, `django_http_load.py`, `pthread_core_pin.c`, `evict_cpu_caches.cc` |
| `scripts/platform/` | `freeze_platform.sh` (core/uncore pinning, both cpufreq drivers), `campaign_common.sh` (per-thread pinning, affinity audits, frequency asserts), `screen_l2i_mpki.sh` (30 s L2I MPKI screen of any command), `build_pthread_core_pin.sh`, `build_cache_evictor.sh`, `configure_benchmark_core_isolation.sh` |
| `scripts/static/` | stage 2 on Verilator/arcilator: **`run_verilator_repro.sh`** (end-to-end reference reproduction, `STEP=traces|plans|build|nop|measure`), `run_l2_trace_aggregation.sh` (N traces → cov50/75/100 plans), `run_prefetcht1_l2_eval.sh` (plan → rebuild → validate → profile; `EXTERNAL_PLAN=` for static planners), `run_prefetcht1_autotune.sh`, `run_static_cond_autotune_round.sh`, `run_verilator_crosspayload_transfer.sh`, `probe_variant_binaries.sh`, `run_prefetch_scheme_compare_from_best.sh`, `generate_lbr_pgo_plan_matrix.sh` |
| `scripts/dispatch/` | stage 3 on DCPerf: `build_feedsim_manual_variants.sh` / `run_feedsim_closedloop.sh` / `run_feedsim_manual_sweep.sh` / `run_feedsim_profile.sh`, `build_django_icache_variants.sh` / `run_django_manual.sh`, memcached `build_*`/`run_*` (neutral result, kept as the control) |
| `migration/` | `bootstrap.sh`, `verify.sh`, `apply_patches.sh`, lock files, source patches for every third-party tree, canonical evidence CSVs, `REPRODUCIBILITY.md` |
| `results/paper_goal_20260815/`, `results/verilator_repro_20260915b/` | tracked raw evidence (run CSVs, plans, validation) behind the umbrella README tables |
| `archive/` | retired campaign scripts/tools (MicroSuite, TailBench, PostgreSQL, autotune drivers) — see `archive/README.md` |

## Typical stage-2 run (Verilator qsort)

`scripts/static/run_verilator_repro.sh` does all of the below (traces → PGO + static plans → pass → resolve/re-anchor → drift gate → NOP twins → interleaved A/B). Status 2026-09-15: PGO 1.021x vs NOP twin (MPKI −6.6%), profile-free plans neutral — umbrella `README.md` §2.

```bash
sudo MODE=3.8ghz scripts/platform/freeze_platform.sh          # intel_pstate needed
TRACE_RUNS=3 TRACE_DURATION_SEC=60 scripts/static/run_l2_trace_aggregation.sh      # PGO plans
python3 ../static_prefetch/tools/static_plan.py --binary $SIM --kinds ret --out-dir work/static --output static.plan.json
EXTERNAL_PLAN=$PWD/static.plan.json PREFETCH_LABEL=static_top1k \
  scripts/static/run_prefetcht1_l2_eval.sh                                          # static plan through the same pass
```

## Typical stage-3 run (DCPerf FeedSim / Django)

```bash
sudo MODE=2ghz scripts/platform/freeze_platform.sh
DISTANCES="16" NEXT_MODES="1" scripts/dispatch/build_feedsim_manual_variants.sh
LABELS="base d16_target_next" REPS=3 ICACHE_ITERS=200000000 SERVICE_THREADS=2 DURATION=300 \
  scripts/dispatch/run_feedsim_closedloop.sh
DISTANCES="4" NEXT_MODES="1" scripts/dispatch/build_django_icache_variants.sh
JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 VARIANT_SEQUENCE=base,d4_next scripts/dispatch/run_django_manual.sh
```

Both harnesses write `runs.csv` with QPS, L2I MPKI, IPC, and affinity/migration
audit columns; a row is `valid` only with zero migrations and pinner errors.
