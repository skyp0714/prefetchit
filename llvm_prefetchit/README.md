# PrefetchIT LLVM Pass

This directory contains a standalone LLVM pass for injecting `prefetchit0`
instructions from PEBS/LBR profiling traces.

The implementation is split into two stages:

1. `tools/prefetchit_trace_to_plan.py` converts the current profiling trace
   format into a compact JSON plan.
2. `lib/PrefetchITPass.cpp` consumes that plan and injects prefetches before
   selected branch/call/return sites.

The pass uses LLVM `blockaddress` constants for exact target basic-block
labels, so generated assembly can use PC-relative operands such as:

```asm
prefetchit0 .Ltmp42(%rip)
```

Build with LLVM 19:

```bash
cmake -S llvm_prefetchit -B llvm_prefetchit/build \
  -DLLVM_DIR=/usr/lib/llvm-19/lib/cmake/llvm
cmake --build llvm_prefetchit/build
```

Convert a current trace into the pass input format:

```bash
python3 llvm_prefetchit/tools/prefetchit_trace_to_plan.py \
  --trace-dir results/trace/verilator-qsort-highrate/l2_miss \
  --binary results/prefetchit_builds/binaries/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig-baseline \
  --top-k 10 \
  --depth 16 \
  --site-budget-per-target 10 \
  --output /tmp/prefetchit.plan.json
```

Run the pass on IR:

```bash
opt-19 \
  -load-pass-plugin llvm_prefetchit/build/PrefetchITPass.so \
  -passes=prefetchit-inject \
  -prefetchit-plan=/path/to/prefetchit.plan.json \
  input.ll -S -o output.prefetchit.ll
```

Run the smoke test:

```bash
llvm_prefetchit/tests/smoke/run_smoke.sh llvm_prefetchit/build
```

## Plan Format

The pass consumes JSON with schema `prefetchit.plan.v1`. The converter emits
one `injections` entry per selected `(target, site)` pair. Each entry carries:

- `target`: mangled function, demangled function, file, line, and representative
  binary address for the missed target instruction.
- `site`: mangled function, demangled function, file, line, LBR branch type,
  selected LBR depth, and representative binary address for the injection site.
- coverage fields: observed samples, newly covered samples, and cumulative
  target coverage after greedy site selection.

The pass matches functions by mangled IR name first. It then matches source
locations using debug metadata, accepting full-path or suffix-path matches.

## Selection Policy

The converter reads `lbr_symbolic_dump.txt`, optionally pairs it with
`lbr_raw_dump.txt`, and uses `nm` plus `addr2line` to recover binary-relative
addresses and source locations.

Selection is:

1. Resolve each LBR target to `function:file:line`.
2. Choose the top K resolved target source locations.
3. For each selected target, collect candidate branch/call/return source
   locations from LBR depth `1..depth`.
4. Greedily choose up to `site-budget-per-target` candidates that cover the
   most not-yet-covered samples.

Targets without source lines are skipped by default because the LLVM pass needs
debug metadata to create a precise `blockaddress` anchor. Use
`--allow-unresolved-targets` only for diagnostics.

## Codegen Notes

The pass injects inline assembly of the form:

```llvm
call void asm sideeffect "prefetchit0 ${0:c}(%rip)", "i,~{memory}"(
  ptr blockaddress(@target_function, %prefetchit.target)
)
```

Lowering with LLVM 19 produces PC-relative assembly such as
`prefetchit0 .Ltmp2(%rip)`. The target basic block is named before the
`blockaddress` is created so the IR remains valid after the target function has
already appeared earlier in the module.
