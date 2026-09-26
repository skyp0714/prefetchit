# Class B headroom campaign

These drivers qualify a real SocialNetwork operating point before comparing
prefetch candidates. They require the local DeathStarBench inputs, Docker
images, retained baseline binaries, root access, and the existing fixed-platform
harness. They never create synthetic cache thrashing or disable application
logging/tracing to amplify an effect.

The exact reference harness and helper files are retained in
`../../migration/evidence/class_b_headroom_20260926/reference_harness.tar.gz`,
with SHA-256 manifest. On another checkout, inspect that archive and restore its
missing files at the repository root; do not overwrite unrelated local work.
The archive contains source, not benchmark data or executables. `reference/run_paths.py`
is a readable frozen copy of the trace parser so offline training/tests do not
depend on an ignored results directory. Build/input manifests identify the
separately retained datasets and binaries.

- `social_headroom.py`: fresh stack/process, 50-second warmup, separate 30-second
  CPU and 20-second PMU windows; target, whole-stack, and CPU-pool accounting.
- `advance_headroom.py`: select the highest qualified baseline MPKI, validate
  isolated-core control, capture two temporal PT windows, fit kernel lists.
- `capture_context.py`: record syscall-exit saved user IP alongside PT and a
  separate retired-L2 PEBS sample. Preserve nanosecond diagnostics; independent
  recorder clocks are not assumed identical.
- `train_kernel_wake.py`: require a first PT trace-start return IP, an unambiguous
  observed syscall/IP mapping, and the actual preceding SYSCALL opcode in the
  ELF. Do not use later branches, future method labels, or widened time joins.
  Require supported contexts and a Wilson lower confidence bound for admission.
  Probability and miss-weighted ranking produce budgets 8/16/32/64. Held-out
  path precision is explicitly separate from cache-miss accuracy and speedup.
- `prepare_streams.py`: service-only accuracy/balanced/coverage builds, each with
  a NOP twin. This does not rebuild or instrument dependency internals.
- `padding_stream.py`: fill existing canonical 7/8-byte in-function NOPs with
  trace-ranked, same-length RIP-relative hints. Static library functions in the
  main image are eligible; shared libraries are unchanged. Exclude direct
  backward-branch loops, cap sites per function and avoid repeated targets.
  Reversing the recorded patches recovers the unchanged baseline exactly.
- `prepare_padding_study.py`: after the first screen, test/prepare two NOP-space
  coverage budgets and compare them against a fresh baseline.
- `paired_study.py`: fresh seeded blocks from a JSON manifest, separate
  exploratory/confirmation results, individual paired-log-ratio t intervals.
- `retain_artifacts.py`: hash/record explicitly selected generated files before
  deleting them. Reject symlinks, original inputs and reference executables.

Run measurements through the archived `run_platform.py`; it fixes the measured
CPUs at 2 GHz with C6 disabled and restores the prior platform on exit. Do not
overlap builds, trace decoding, NAS transfers, or other experiments with timing.
Use a fresh output directory for every run. Keep rejected measurements and
their exclusion reasons; remove their generated bulk files immediately.

Kernel trials additionally need `kernel/wake_prefetch/wake_prefetch.ko` built
for the running kernel. Module-off, loaded-empty and registered NOP controls
distinguish hook overhead from useful cache fills. A target-cgroup saving alone
is insufficient because the switch callback runs in the outgoing task.
