# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

This is a CPU prefetching research microbenchmark designed to evaluate Intel's PREFETCHI instruction performance. The codebase focuses on measuring instruction cache latency and miss rates with and without prefetching.

**Core Components:**
- **latency.c**: Main C benchmark that generates 1024 synthetic NOP-padded tasks
- **utils.c/utils.h**: Utility functions for system management, perf counters, and I/O operations
- **lat_bench**: Compiled executable (ELF 64-bit) for running latency measurements  
- **run_lat_bench_stats.py**: Python wrapper for statistical analysis across multiple benchmark runs

## Key Architecture Details

**Task Generation System** (latency.c:180-199):
- Creates 1024 individual task functions (`task_0` through `task_1023`) using C macros
- Each task has a small NOP body plus a 256-byte NOP pad to create a controlled instruction footprint
- Tasks are placed in a special `.text.tasks` section for controlled memory layout

**PREFETCHI Integration** (latency.c:109-125):
- Uses `__builtin_ia32_prefetchi` when `ENABLE_PREFETCHI` is defined
- Prefetching is selected at compile time via Makefile targets
- CPU feature detection via CPUID instruction

**Performance Measurement Framework**:
- TSC (Time Stamp Counter) for high-precision timing
- Linux perf_event interface for hardware counter access (L1I misses, iTLB misses, L2 counters, instructions)
- Real-time scheduling and CPU affinity pinning for consistent measurements

## Development Commands

### Build the benchmark:
```bash
cd microbench/src
make
```

### Run single benchmark:
```bash
cd microbench/src
# Basic run: ./lat_bench [rounds] [queue_length]
./lat_bench 1 4096
./lat_bench_prefetch 1 4096
```

### Run statistical analysis:
```bash
cd microbench/src  
python3 run_lat_bench_stats.py --cmd "./lat_bench_perf 1 4096" --iters 100
python3 run_lat_bench_stats.py --cmd "./lat_bench_prefetch_perf 1 4096" --iters 100
```

## Important Implementation Notes

**Memory Management**: Tasks are compiled into a special section with controlled alignment to ensure predictable instruction cache behavior.

**PREFETCHI Requirements**: The `-mprefetchi` compiler flag and `ENABLE_PREFETCHI` define are required for prefetch instruction generation. CPU must support the PREFETCHI feature. The Makefile defaults to Clang because older GCC versions may not support `-mprefetchi`.

**Root Privileges**: CPU frequency locking and some perf events require root access for accurate measurements.

**Benchmark Parameters**:
- `rounds`: Number of complete task queue executions
- `queue_length`: Number of tasks to run per round
