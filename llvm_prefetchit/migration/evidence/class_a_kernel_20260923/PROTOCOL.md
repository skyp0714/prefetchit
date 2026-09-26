# Kernel boundary experiment, 2026-09-23

No kernel binary, kernel module, sysctl, mitigation or workload operation mix is
modified. Fixed 2 GHz/cpufreq+HWP, turbo off, fixed uncore and participant C6 off
are scoped and restored by the existing platform wrapper. Builds and tests never
run concurrently with measurements.

Media retains the production info-log full stack and dataset at 2,500 offered
RPS, with fresh stack/data for every arm. Primary cost is cgroup user+kernel CPU
per achieved external request, separately per service. A joint screen instruments
all three dedicated service instances; any selected follow-up must distinguish
joint-stack effects from per-service isolated effects. LD_BIND_NOW=1 is identical
for originals and interposer runs.

The interposer loads the caller return address from the unmodified stack, issues
1/2/4 T1 hints (or two T0 hints), and tail-jumps to the original libc function.
It preserves arguments, return values, errno and the original return address.
I/O-only and I/O+pthread scopes are screened. These hints target user code, not
kernel code; they can only mitigate the user-side consequence of kernel activity.
Same-layout NOP twins retain the pointer load, tail jump and dynamic linker cost.
Kernel PMU diagnostics and profiling are not timing confirmation runs.

Keep every trial, including setup failures. Require zero socket errors, <=0.1%
HTTP errors and achieved RPS >=98% of offered. A one-round screen is exploratory.
Promote a plausible >=0.5% candidate to fresh paired base/prefetch/NOP runs;
report paired log-ratio confidence intervals and baseline drift. A meaningful
>=1% result needs repeatable benefit against both base and NOP, not just fewer
misses. Do not interpret missing samples as zero opportunity.

A kernel-modification potential estimate must distinguish a broad optimistic
frontend/fetch-latency scenario from code-miss-attributable time. Top-down slots
and I-cache stall counters are not additive or equivalent to removable runtime.
No claimed hardware-perfect-prefetch ceiling can be established from these PMU
counters alone. Preserve kernel fraction, MPKI, stall counters and sampled paths
so assumptions in a conditional estimate are explicit.

Additional workloads are screened with normal upstream settings. Report >=1 and
>=10 L2 code MPKI separately; do not substitute L1I or branch MPKI, C6 wake misses,
invalid workload runs, or cross-service core sharing for Class A capacity misses.

Pthread forwarding revision: failed unversioned condition-variable forwarding
was reproduced in the benchmark Jammy image with CLOCK_MONOTONIC. Explicit
GLIBC_2.3.2 lookup/export passes that regression plus thread/socket/errno checks.
The three failed pre-measurement setups are excluded in EXCLUDE_pthread_v1.json.
The I/O-only variants do not interpose condition-variable functions.

Static continuation policy: replace an existing canonical 7–15 byte NOP in the
scan region preceding an imported I/O/pthread call (<=256 bytes)
with a same-size RIP-relative hint to the instruction after that call. Reset
selection at recognized function labels, symbolic direct calls, j* branches, returns and syscalls. This prototype is not a full CFG analysis; indirect calls and loop-family instructions are not explicit reset points. 22/14/14 sites in
MovieId/ComposeReview/Rating; exact reversal reconstructs baseline bytes.
