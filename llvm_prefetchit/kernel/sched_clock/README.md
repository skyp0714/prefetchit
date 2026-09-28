# Scheduler age for dominator prefetch

This experimental x86-64 module publishes the TSC at `sched_switch`, after the
incoming task is selected. It does not prefetch, inspect user memory, or start
timers. The compiler places prefetches along the running application's CFG.

Each logical CPU owns one 64-byte slot. The first three u64 words hold deadlines
at start + 10, 20, and 40 microseconds; the fourth holds start. A read-only mapping
contains 4096 slots (256 KiB). Linux x86's RDTSCP TSC_AUX low 12 bits identify the
CPU. `tsc_khz`, not the variable core frequency, converts microseconds to ticks.
Every context switch updates that CPU's slot, including switches between threads
of the same process. Migration requires no per-thread registration.

The compiler uses RDTSCP at an issuance group and checks its CPU's deadline. All
groups are eligible for 0–10 us, approximately half for 10–20 us, approximately a
quarter for 20–40 us, and none later. These are **static eligibility fractions**;
execution frequency, group size and path selection determine the actual number
of hints. Gates remain in the instruction stream after 40 us. A group contains
up to four deduplicated targets; several groups can share one dominator.

The age includes the remaining context-switch and syscall-return work, and
interrupt time. It is not time since the first user instruction. A gate samples
time once; a preemption or migration during/after that sample can skip a useful
hint or issue a hint with stale age. This affects hint quality, not program data.
The start-time check rejects a newer epoch than the sampled timestamp. No claim
of an atomic scheduler/user transaction or an exact periodic issue rate is made.

Build in a dedicated generated directory using the supplied Makefile and matching
running-kernel headers. Load with `insmod prefetchit_sched_clock.ko`; optional
read-only parameters are `dense_us=10 medium_us=20 sparse_us=40`, or `flat=1` to
keep every group eligible. Bounds: 0 < dense <= medium <= sparse <= 1000 us.
Link `runtime.c` once into the executable. It opens `/dev/prefetchit_sched_clock`
and maps the clock before normal constructors. The device is mode 0600. Use
`PREFETCHIT_SCHED_REQUIRED=1` in accepted measurements to fail startup if mapping
fails. Without that flag/device the weak NULL pointer disables hints.

The mapping rejects writable/executable mappings and later `mprotect` upgrades.
The VMA's file reference pins the module after close(fd), through fork, and until
unmap or process teardown. The hook is synchronized before unloading. `smoke.c`
checks permissions and 160 reschedules across four threads; also test that
`rmmod` fails while a mapping survives close(fd), then succeeds after unmap.

This is a lab-only module for the measured Linux 6.8 x86 host. It depends on the
sched_switch callback signature, invariant/nonstop TSC and RDTSCP. The shared
page contains timestamps only, no task IDs, kernel pointers or task code bytes.

Primary references: [Linux tracepoint lifecycle](https://www.kernel.org/doc/html/v6.8/trace/tracepoints.html)
and [Linux x86 TSC_AUX encoding](https://github.com/torvalds/linux/blob/v6.8/arch/x86/kernel/cpu/common.c).
