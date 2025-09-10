# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

This is a CPU prefetching research microbenchmark designed to evaluate Intel's PREFETCHI instruction performance. The codebase focuses on measuring instruction cache latency and miss rates with and without prefetching.

**Core Components:**
- **latency.c**: Main C benchmark that generates 256 synthetic tasks with different execution patterns
- **utils.c/utils.h**: Utility functions for system management, perf counters, and I/O operations
- **lat_bench**: Compiled executable (ELF 64-bit) for running latency measurements  
- **run_lat_bench_stats.py**: Python wrapper for statistical analysis across multiple benchmark runs

## Key Architecture Details

**Task Generation System** (latency.c:180-199):
- Creates 256 individual task functions (`task_0` through `task_255`) using C macros
- Each task has unique computational patterns to create diverse instruction cache behavior
- Tasks are placed in a special `.text.tasks` section with 256-byte alignment for controlled memory layout

**PREFETCHI Integration** (latency.c:109-125):
- Uses Intel intrinsics (`_mm_prefetch` with `_MM_HINT_IT0/IT1`) when `ENABLE_PREFETCHI_INTRIN` is defined
- Supports prefetch position tuning via NOP window insertion
- CPU feature detection via CPUID instruction

**Performance Measurement Framework**:
- TSC (Time Stamp Counter) for high-precision timing
- Linux perf_event interface for hardware counter access (L1I misses, iTLB misses, instructions)
- Real-time scheduling and CPU affinity pinning for consistent measurements

## Development Commands

### Build the benchmark:
```bash
cd microbench/src
gcc -march=x86-64-v4 -m64 -no-pie -fno-plt \ 
        -mprefetchi -DENABLE_PREFETCHI_INTRIN \
        latency.c utils.c -o lat_bench
```

### Run single benchmark:
```bash
cd microbench/src
# Basic run: ./lat_bench [rounds] [queue_length] [prefetch_position] [prefetch_enable]
./lat_bench 1 256 28 0  # 1 round, 256 tasks, position 28, prefetch disabled
sudo ./lat_bench 1 256 28 1  # Enable prefetch (requires root for freq locking)
```

### Run statistical analysis:
```bash
cd microbench/src  
python3 run_lat_bench_stats.py --cmd "./lat_bench 1 256 28 0" --iters 100
# For prefetch testing (requires root):
python3 run_lat_bench_stats.py --cmd "sudo ./lat_bench 1 256 28 1" --iters 100
```

## Important Implementation Notes

**Memory Management**: Tasks are compiled into a special section with controlled alignment to ensure predictable instruction cache behavior.

**PREFETCHI Requirements**: The `-mprefetchi` compiler flag and `ENABLE_PREFETCHI_INTRIN` define are required for prefetch instruction generation. CPU must support the PREFETCHI feature.

**Root Privileges**: CPU frequency locking and some perf events require root access for accurate measurements.

**Benchmark Parameters**:
- `rounds`: Number of complete task queue executions
- `queue_length`: Number of tasks to run per round  
- `prefetch_position`: Where in NOP window to place prefetch (0-32)
- `prefetch_enable`: 0=disabled, 1=enabled