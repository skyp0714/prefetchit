# Reference host

This file records the machine on which the existing results were collected. It
is evidence, not a script to reproduce the boot configuration blindly.

- OS: Ubuntu 22.04.5 LTS
- Kernel: custom Linux 6.0.0, PREEMPT_DYNAMIC
- CPU: Intel Xeon 6787P, family 6 model 173 stepping 1
- Topology: 1 socket, 86 physical cores, 1 thread per core
- Cache: 64 KiB L1I/core, 2 MiB L2/core, 336 MiB shared L3
- LLVM/Clang: 19.1.7
- GCC/G++: 12.3.0; GFortran: 11.4.0
- CMake: 3.22.1; Python: 3.10.12
- Verilator experiment build: 5.046
- Boot isolation used by the reference host: `isolcpus=10-31 nohz_full=10-31 rcu_nocbs=10-31`
- Other boot parameters included `intel_pstate=disable`, 2 MiB huge pages, and a
  host-specific persistent-memory `memmap`; do not copy the `memmap` argument.
- The checked-in `kernel-6.0.0.config` has SHA-256
  `05291ac76635933c63b2cf0bf159f7c00aefcfe97b9358670102de1682b4e4c2`.

At migration time `/usr/bin/perf` did not have a matching 6.0.0 backend. A new
host must install or build `perf` from the exact running kernel before profiling.
The experiment scripts accept `PERF_BIN=/path/to/perf`.
