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

Run the pass on IR:

```bash
opt-19 \
  -load-pass-plugin llvm_prefetchit/build/libPrefetchITPass.so \
  -passes=prefetchit-inject \
  -prefetchit-plan=/path/to/prefetchit.plan.json \
  input.ll -S -o output.prefetchit.ll
```
