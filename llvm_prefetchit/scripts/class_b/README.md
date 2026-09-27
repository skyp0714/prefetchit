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
- `confirm_best.py`: freeze the exploratory winner, remove superseded generated
  binaries, and compare seven new seed blocks against baseline and old wake16.
  A distinct layout NOP is included in three blocks. Promotion requires positive
  individual 95% lower bounds against both baseline and old wake16; screen
  measurements are never pooled into confirmation.
- `retain_artifacts.py`: hash/record explicitly selected generated files before
  deleting them. Reject symlinks, original inputs and reference executables.
- `collect_evidence.py`: after completion, archive compact results and verify
  every recorded platform/HWP restoration. Keep a file hash manifest; exclude
  executables, raw/decoded traces and mapped ELF copies.

Run measurements through the archived `run_platform.py`; it fixes the measured
CPUs at 2 GHz with C6 disabled and restores the prior platform on exit. Do not
overlap builds, trace decoding, NAS transfers, or other experiments with timing.
Use a fresh output directory for every run. Keep rejected measurements and
their exclusion reasons; remove their generated bulk files immediately.

Kernel trials additionally need `kernel/wake_prefetch/wake_prefetch.ko` built
for the running kernel. Module-off, loaded-empty and registered NOP controls
distinguish hook overhead from useful cache fills. A target-cgroup saving alone
is insufficient because the switch callback runs in the outgoing task.

The five-service follow-up uses the readable canonical harness under
`migration/schemes/class_b_extension_20260926` and adds MovieId to the two Media
and two Social targets. Media retains 100% application tracing and Social 10%,
matching each family's existing reference regime. These are not changes made
between performance arms.

- `fullset.py prepare` stages/hash-checks all references locally. `qualify`
  compares baseline pools of 4/6/8 at 600 RPS, then selects by geometric-mean
  code MPKI across each family's targets, before seeing candidate results.
  Redirect qualification output to `OUT/qualification.log`. `campaign` builds
  and tests the kernel extension and calls `candidates`; the latter captures
  separate training/validation PT windows and retired-L2 samples, trains bounded
  kernel profiles and builds the coverage policy plus exact-layout NOP twins.
- `kernel_emission_study.py campaign` screens 13 emission patterns on MovieId
  and UserTimeline with paired NOPs, module-off and loaded-empty controls. Each
  screen uses one fresh baseline stack with serial steady-load phases: 8 s to
  settle, 20 s clean CPU ROI, then 10 s separate PMU. Pre/post cache diagnostics
  are separate. The frozen finalist gets seven fresh baseline stacks, each
  rotating off/NOP/candidate with 10 s settling and 30 s clean CPU ROI. Only
  this confirmation supplies confidence intervals for the selected kernel arm.
- `fullset_study.py streams` tests each new service separately, then confirms
  simultaneous Media3 and Social2 deployments over seven fresh seed blocks.
  Every block includes baseline, retained artifact reference, all-new policy
  and all-new layout NOPs. Separate one-block PMU comparisons follow. The old
  MovieId reference uses its original build; it is an artifact comparison, not
  a pure one-setting ablation. Rating's rejected old binary was removed, so
  baseline is its retained reference. Primary metrics cover every target, the
  whole stack and the shared pool; a bundle's effects are not assumed additive.
- `fullset_finish.py --preparation-pid PID` serializes the two completed stages
  after preparation exits. `fullset_cleanup.py` preserves hashes/settings and
  unlinks explicit unused trace copies or rejected generated binaries without
  following symlinks. Confirmed reference binaries and original inputs remain.
- `fullset_report.py` collects final CPU intervals, trace validation, kernel
  diagnostics, post-hoc user/system CPU decomposition and restoration checks.
  Curated JSON evidence is published; detailed logs, generated plans and the
  compressed reproduction archive remain under `OUT/evidence_archive` locally.

The first MovieId kernel screen was excluded as a whole because its load ended
before the last PMU window. The repeated block used the same seed/order with a
larger duration margin and explicit load-deadline checks. Before independent
confirmation, kernel finalist ranking was amended to use adjacent NOP pairs:
the initial off phase of a long screen cannot control for later workload drift.
The original ranking and diagnostics remain recorded. Seven fresh, rotated
off/NOP/candidate blocks still determine promotion; screen data are not pooled.

Completed results: [five-service report](../../../docs/class_b_fullset_20260926.md).

Default follow-up roots are `/storage/prefetchit/class_b_fullset_20260926` and
`/trace/prefetchit/class_b_fullset_20260926`; override `CLASS_B_FULLSET_OUT` and
`CLASS_B_FULLSET_TRACE` for another campaign. The existing build root must also
be isolated with `CLASS_B_STORAGE_ROOT` when rebuilding arms with the same name.
Do not rerun into an existing experiment directory. Python runtime uses the
system SciPy/PyYAML; the existing `profiling/.venv/bin/python` supplies pytest
for the kernel ABI tests. A 10% gain is a target, not a qualification gate or
an assumed result.
