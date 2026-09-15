# profiling/archive

Superseded material, kept for provenance:

- `run_profile_all.sh`, `run_jvm_*.sh`, `run_kernel.sh`, `run_runtime_only.sh`,
  `run_spec_singlethread_l2_mpki.sh`, `config/benchmarks.txt`,
  `runscript/bench/run_{finagle_*,spec_*,tomcat}.sh`, `runscript/plot/*`:
  phase-1 frontend characterisation (MPKI screens of JVM/SPEC/Verilator,
  context-switch and kernel idle/busy studies).
- `runscript/build/{apply_,prepare_}prefetch*`, `validate_prefetch*`,
  `run_prefetchit_eval_pipeline.sh`, `launch_prefetchit_builds.sh`,
  `run_dtcov_eval_and_trace.sh`: source-level `RIP+disp` patching of
  Verilator C++ before the LLVM pass existed (design.md explains why it was
  replaced).
