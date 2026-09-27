# Bounded switch-in prefetch experiment

This is a **compile- and lifecycle-tested research prototype**. Three initial
real-service T1 policies failed to improve shared-pool CPU cost and were rejected;
see the [campaign report](../../../docs/class_b_headroom_20260926.md).
It was built against Ubuntu 6.8.0-142-generic x86-64.
The root-only smoke helper passed NOP/T1 callback, exclusive/repeated registration,
FD-close disable and exec-mm disable checks; the module was unloaded afterwards.
Callback counts alone do not establish cache fill or performance benefit.
Run `sudo python3 smoke.py --out NEW_DIRECTORY` to reproduce the
smoke checks; this loads/unloads the module and deletes its generated helper.

The module registers a `sched_switch` probe, matches one explicitly registered
thread group and address-space identity, and issues at most 64 prefetch
instructions across all phases of one matched scheduling interval. The first callback executes after the next task has
been selected, before `context_switch()`/`switch_mm()`.
It therefore uses the kernel direct mapping of pinned code pages, **never the
next process's user VA**. No allocation, page walk, user copy, blocking operation,
or executable code modification occurs inside the callback.

Profiles can match the saved user return IP and/or syscall number in `pt_regs`.
First match wins. A method or later user-space return frame inferred from PT is
not a valid switch-in classifier without an independently available predictor.
An unconditional fallback must come last. Begin with 8 or 16 lines; 32/64 are
separate coverage/queue-pressure experiments, not presumed improvements.

The v2 emission options preserve this selected-next-task timing:

- `--spacing 4|16 --group 1|2|4|8|16` inserts a bounded number of NOP instructions
  between groups. There is no timer, busy wait or `pause` loop.
- `--split-after N` emits the first N lines at `sched_switch`, then the remainder
  at a dynamically registered entry kprobe on `finish_task_switch.isra.0`.
  The latter symbol is specific to this tested kernel build. Registration fails
  on unsupported kernels. It never probes `__switch_to`, which Linux forbids.
- `--hint t1|t0|nta` selects the cache hint. `--mode nop` preserves matching,
  address loads, grouping, spacing and the optional completion probe.
- `--diagnostic 1` samples a data load before emission; `--diagnostic 2` samples
  after the architectural switch and records issue-to-completion delay. Each
  samples one rotating first-phase line per 64 matches per CPU. Pre and post
  experiments are separate so the diagnostic pre-load cannot warm the post
  sample. All units are invariant TSC ticks. Histograms describe pinned-alias
  data access, not instruction-fetch latency, cache-level identity or PMU cycles.
  Diagnostics are disabled for performance comparisons.

The unchanged v1 ABI remains accepted. v2 uses five option bytes in reserved[0];
reserved[1] and unused high bytes must be zero. The optional detail ioctl returns
second-phase counts, cancellations and diagnostic histograms. Scheduler counters
are per-CPU and snapshot totals can span an in-flight callback. Deferred state
contains only a registration generation, numeric TID and indices; no plan/page
pointer crosses RCU critical sections. A new generation cannot consume an old
pending operation. Close disables the plan and unregisters the completion probe.

The v3 wave options add actual microsecond spacing, separately from the v2
NOP gaps. For example, `--interval-ns 2000 --batch 4 --max-age-us 40` emits four
lines at selection and at most four more per pinned hard hrtimer callback while
the same thread continues running. The whole interval still has a 64-line cap.
Intervals are bounded to 1–16 us, batches to 1–16 lines, and the expiration
deadline to 4–64 us. Split emission, artificial NOP spacing, and diagnostic loads
cannot be combined with waves. Existing v1/v2 byte layouts remain unchanged;
v3 uses reserved[1] for these bounded settings.

Every task switch cancels the previous CPU's pending wave, including switches
between threads of the registered process. Each timer callback checks generation,
CPU, numeric TID, TGID object, and mm identity before using pinned aliases. No
plan pointer escapes RCU. Closing the controller first removes the plan and
waits for readers, then synchronously cancels all timers before reopening or
module unload. Callbacks at or beyond the deadline issue no hints; a callback
inside the deadline can still be late for an individual target. Each further
interval starts after the previous emission, with no catch-up loop.
Consequently requested spacing is a minimum delay, not an exact phase clock.

The wave ioctl reports callback/emission/line counts, switch cancellations,
deadline expiration, identity rejections, and actual delayed-emission ages in
2 us bins (last bin >=30 us). These are attempted hints, not cache fills.
All timer/IRQ work is part of the measured end-to-end and shared-pool cost.
The same-layout NOP module runs these same callbacks; module-off remains the
deployment reference. The expanded smoke test pauses its private helper for
coherent counter checks and exercises both 2/4 us wave intervals, NOP/T1,
close, exec, and unload.

The v2 lifecycle test passed 17 checks on the running 6.8.0-142 kernel.
The v3 wave extension passed 21 checks each with the prefetch module and its
exact-layout NOP twin, including both emission phases, spacing, hint variants,
timed waves and exec/close teardown. Application results are reported separately
in the E2E study; passing lifecycle checks does not imply a speedup.

Registration requires `CAP_SYS_ADMIN` and `/dev/wake_prefetch` is mode 0600.
Only one open controller is allowed. Closing its FD removes the RCU-published
plan, waits for readers and releases its pins. Module references prevent unload
while a controller is open. PID-object and mm references prevent a registered
plan from following PID reuse or exec to a new address space.

Only read-only, executable, file-backed mappings are accepted. The experiment
assumes their identity stays fixed during each arm: use a fully initialized
native service without text rewriting, mprotect/COW, or dlclose/unmap. Pinning
keeps the physical pages alive; it does **not** automatically retarget a changed
mapping. DAX and other unsupported long-term pins can reject registration.

Build after checking disk space:

```sh
df -h . /storage
make -C llvm_prefetchit/kernel/wake_prefetch -j4
```

The controller accepts this JSON structure. Every target is bound to the exact
mapped file's SHA-256 and ELF virtual address, not a file offset or old ASLR VA:

```json
{
  "profiles": [
    {
      "syscall_nr": 7,
      "resume_ip": {
        "path": "/usr/lib/x86_64-linux-gnu/libc.so.6",
        "sha256": "REPLACE_WITH_CURRENT_FILE_SHA256",
        "elf_va": "0xREPLACE_WITH_SAVED_RETURN_IP"
      },
      "targets": [
        {
          "path": "/custom/UserTimelineService",
          "sha256": "REPLACE_WITH_CURRENT_FILE_SHA256",
          "elf_va": "0xREPLACE_WITH_64_BYTE_ALIGNED_ELF_VA"
        }
      ]
    }
  ]
}
```

Omit `resume_ip` for a syscall-wide profile; omit `syscall_nr` for any syscall or
user preemption. The retained old trace's inferred `recv` label is insufficient
to select `syscall_nr`: it can include a run that resumes from `poll` and calls
`recv` later. Collect the actual saved return IP/syscall context first.

Validate addresses with `control.py PLAN --pid PID --out NEW.json --validate-only`.
No device is opened in this mode. Loading and running, once host access is ready:

```sh
sudo insmod llvm_prefetchit/kernel/wake_prefetch/wake_prefetch.ko
sudo python3 llvm_prefetchit/kernel/wake_prefetch/control.py PLAN.json \
  --pid PID --mode nop --seconds 180 --out NEW_NOP.json
sudo python3 llvm_prefetchit/kernel/wake_prefetch/control.py PLAN.json \
  --pid PID --mode t1 --seconds 180 --out NEW_T1.json
sudo rmmod wake_prefetch
```

These commands illustrate control, not an A/B protocol: timing must use fresh
processes, balanced order, fixed workload/platform, independent traces and
separate timing. Registration should finish before the measured window.
Controller output must show nonzero matched switches. `attempted_lines_including_nop` counts
attempts (also in NOP mode), never successful prefetch fills.

Initial arms: module unloaded; loaded without a plan; matching NOP plan; T1
plan; best user-space stream. A combined stream+NOP/stream+T1 study is a follow-up
only if the kernel policy passes the initial screen. The NOP path
retains target loads, matching logic, loop and counters; it is a control path
in the same module, not a byte-identical whole-module binary.

The follow-up emission study additionally creates `wake_prefetch_nop.ko` from
the built module by replacing only the three 3-byte prefetch instructions in
`emit` with equal-length NOPs. It verifies all six changed bytes and identical
file size, then runs the expanded smoke test against that copy. Both performance
arms use config mode 1, so hint selection, mode branches, spacing, counters and
split probes follow the same path. Each module is unloaded before the next is
loaded. The study records both hashes and the complete byte-difference list.
The runtime NOP mode remains available for the original controller and functional
checks; it is not the new study's primary timing control.

**Account scheduler cost to the whole shared CPU pool.** The probe runs in the
outgoing task's context, so target-cgroup CPU alone can hide prefetch overhead in
another service or idle. Record pool non-idle CPU/request, whole-stack cgroup
CPU/request, target user+kernel CPU/request, latency/errors and PMU separately.
Per-service cost savings without pool/stack net savings are insufficient to
promote the kernel arm. This prototype cannot train the BTB/BPU or populate the
user ITLB by prefetching a kernel alias.

`cache_probe.py` is a separate synthetic functional check. After all application
timing has ended, it flushes one unused executable line, sleeps, and times a
**data load** from that line. It rotates kernel NOP, kernel T1 and a user T1
positive control over three blocks of 500 samples. Run it as root through the
fixed-platform wrapper with `--out NEW_DIRECTORY --cpu 42`, after rebuilding the
module. It retains the helper source, every cycle sample, mapping/hash audit and
counters, then unloads the module and removes the helper executable. Remove
unused module build artifacts separately after recording their hashes. This
diagnostic can demonstrate cache warmth; it cannot establish application speedup
or restoration of L1I, ITLB or branch-predictor state.

Sources: [Linux 6.8 scheduler](https://github.com/torvalds/linux/blob/v6.8/kernel/sched/core.c),
[Linux 6.8 hrtimers](https://github.com/torvalds/linux/blob/v6.8/kernel/time/hrtimer.c),
[Linux 6.8 page pinning API](https://docs.kernel.org/6.8/core-api/pin_user_pages.html),
[x86 switch restrictions](https://github.com/torvalds/linux/blob/v6.8/arch/x86/kernel/process_64.c),
[kprobe restrictions](https://docs.kernel.org/6.8/trace/kprobes.html).
