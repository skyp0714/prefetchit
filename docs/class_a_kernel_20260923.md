# Class A: kernel misses and user return-code prefetch (2026-09-23)

**The no-kernel Media return-prefetch experiment did not confirm a meaningful
gain.** Twenty fresh trials (five paired rounds) gave only +0.14% CPU efficiency
for the three measured services combined with static T1; its 95% interval is
−0.64% to +0.93%. The dynamic I/O hint was −0.10% against its NOP twin. The
exploratory screen's approximately 1% gains did not reproduce. This does not
establish a ceiling for every return-prefetch policy.

The experiment changes no kernel binary, module, mitigation, syscall mix or
application operation settings. It tests whether prefetching **user code before
an I/O/synchronization call** can reduce the cost of returning from a kernel-heavy
path. It does not prefetch privileged kernel text from user mode.

Full local evidence is in `llvm_prefetchit/results/class_a_kernel_20260923/`
(`R` below). The preceding workload qualification and FeedSim v2 result are in
[the A-2 campaign](class_a2_campaign_20260923.md).

## Protocol and scope

- Xeon 6787P, fixed 2 GHz core/HWP, turbo off, fixed uncore, participant C6 off.
  The existing platform wrapper restores every saved setting in `finally`.
  Builds, disassembly, other benchmarks and large evidence analysis are serialized
  outside accepted measurement windows.
- Media uses the unchanged production info-log full stack at 2,500 offered RPS,
  a fresh stack/dataset per trial, the same request seed, and dedicated two-core
  instances for MovieId, ComposeReview and Rating. Backends, client and nginx
  retain their previous affinities. `LD_BIND_NOW=1` is identical in all timing arms.
- Primary Media cost is **cgroup user+kernel CPU per achieved external request**.
  Achieved rate must be at least 98% of offered, HTTP failures at most 0.1%, with
  no socket errors, service restarts or cgroup throttling. The accounting window
  must be 25–26 seconds; PMU scheduling must be 100%.
- All three measured services receive the treatment together. Their individual
  costs are joint-stack observations, not three independent applications or
  isolated service treatment effects. Their summed CPU cost excludes the other
  stack components. Fixed-rate CPU efficiency is not capacity throughput.
- Nine policies/controls were screened once, bracketed by two baselines. Five
  **fresh** randomized rounds compare `base`, `static_t1`, `io2t0`, and the exact
  `io2t0_nop` twin. Screen observations are not pooled into confirmation.
  Report geometric paired speedups and two-sided log-ratio t intervals (n=5,
  df=4); intervals are unadjusted for multiple endpoints.

## Kernel-only diagnostics

The event is Granite Rapids `L2_RQSTS.CODE_RD_MISS` (event 0x24, umask 0x24),
divided by retired instructions in the **same privilege mode**, times 1,000.
User and kernel MPKIs cannot be added. Top-down entries below are percentages of
kernel slots, not percentages of whole-service runtime.

| Workload and normal setting | Kernel L2I MPKI | Kernel CPU share | Kernel FE | Kernel BE | Bad speculation | Retiring |
|---|---:|---:|---:|---:|---:|---:|
| Media MovieId, 2,500 RPS | 0.802 | 81.0% | 22.4% | 51.2% | 4.7% | 21.6% |
| Media ComposeReview, 2,500 RPS | 1.902 | 82.4% | 22.9% | 50.8% | 4.7% | 22.0% |
| Media Rating, 2,500 RPS | 0.814 | 78.0% | 21.8% | 51.8% | 4.7% | 22.7% |
| MySQL, durable OLTP read/write, 400 TPS | 5.877 | 28.1% | 37.3% | 39.5% | 4.3% | 19.3% |
| Rails, production Puma 4×8, 800 RPS | 16.393 | ≈13.1% | 39.3% | 38.7% | 6.3% | 15.7% |
| Django v2, 20 connections | 14.920 | ≈10.5% | 40.6% | 32.8% | 8.7% | 17.9% |
| FeedSim v2, full defaults, 40 QPS | 8.506 | 5.1% | 28.8% | 45.7% | 5.7% | 20.2% |

Media uses cgroup-filtered kernel PMU counts and cgroup `system_usec/usage_usec`.
MySQL/FeedSim use process-attached kernel events and kernel cycles divided by
fixed-frequency total task-clock. Rails/Django use per-CPU kernel events; their
CPU shares approximate user+kernel cycles/request from separate normal-load
measurements. These scopes are retained in `R/kernel_inventory.json`.
Top-down quantization/measurement means rounded entries need not sum to exactly
100%. Do not interpret per-CPU counts as perfectly isolated process counts.

Separately measured misses, normalized by achieved request rate, suggest kernel
shares of roughly 77–83% for Media, 45% for Rails, 35% for Django, 26% for MySQL,
and 5% for FeedSim. These are cross-run estimates, not simultaneous partitions.
Thus Media is the strongest kernel-heavy target despite modest kernel MPKI.
Rails/Django's double-digit **kernel-only** MPKI does not establish double-digit
whole-workload MPKI or a dominant kernel runtime contribution.

## How much could a kernel change recover?

Additional normal-load baselines measure kernel I-cache stalls with sampling
disabled, using the same cgroup/process/per-CPU scopes described above.
`ICACHE_DATA.STALLS` counts L1 instruction-fetch stall cycles;
it does not isolate L2 misses or prove that these cycles delay useful retirement.
iTLB walk-active and branch-clear counts are retained separately and are not
added to the instruction-cache budget. Event definitions are from
[Intel's Granite Rapids event reference](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

Define `f` as the kernel CPU fraction and `s` as kernel I-cache-stall cycles / kernel
cycles. The **conditional scenario**, not an architectural upper-bound proof, is

`speedup(h) = 1 / (1 - f × s × h) - 1`.

Here `h` includes the fraction relevant to L2 code misses, target coverage,
timeliness, and conversion of fetch stalls into actual saved CPU time after
overlap. It is not an observed prefetch hit rate. The formula does not deduct
extra hint/instrumentation cost, so the resulting gains remain optimistic.

| Service | Kernel I-cache stall cycles | h=25% | h=50% | h=100%, optimistic reference | h required for +3% / +5% |
|---|---:|---:|---:|---:|---:|
| MovieId | 4.62% | +0.95% | +1.91% | +3.89% | 77.7% / 127.1% |
| ComposeReview | 5.91% | +1.23% | +2.48% | +5.09% | 60.1% / 98.3% |
| Rating | 4.26% | +0.83% | +1.68% | +3.42% | 88.0% / 143.9% |
| MySQL | 10.99% | +0.79% | +1.58% | +3.22% | 93.4% / 152.7% |
| Rails | 18.53% | +0.62% | +1.25% | +2.53% | 117.9% / 192.8% |
| Django v2 | 16.12% | +0.42% | +0.85% | +1.71% | 173.5% / 283.6% |
| FeedSim v2 | 11.97% | +0.16% | +0.32% | +0.64% | 460.4% / 752.8% |

These additional stall runs have kernel CPU fractions of 28.4/13.3/10.4/5.3%
for MySQL/Rails/Django/FeedSim; Rails/Django remain cross-run approximations.
All four loads pass their established rate/error criteria, including FeedSim's
latency criterion. Exact values and sources are in
`R/other_kernel_icache_scenarios.json`.

This supports investigating percent-scale kernel-side gains in Media/MySQL/Rails,
with Compose the best first target. Django and especially FeedSim have less
kernel-only opportunity. Three percent requires recovering most of the modeled
opportunity even for Media/MySQL; 3–5% for every workload is unsupported by this
scenario. FeedSim's already-confirmed user-space array gain remains valuable.
A data
prefetch does not directly fill L1I, and the counter includes L1I misses that hit
L2, making the h=100% assumption especially generous. Backend-bound slots are
about half the Media kernel total. Removing all fetch-latency slots produces a much
larger model, but includes costs that code data-prefetch cannot remove and is
not used as the predicted gain.
Lock contention and queueing can change after an optimization, so this simple
scaling also omits secondary effects; its 100% column is not a hard bound.

The separate `cycles:k` call-stack profile has zero lost samples. It shows TCP
send/receive, IP/softirq processing, locks, skb allocation/release and scheduling
paths. These identify code regions to investigate, not code-miss attribution.
The next kernel prototype should issue selective kernel-text hints **inside**
the kernel sufficiently ahead of predictable callees, then sweep lead time and
compare identical-layout NOP controls. Merely hinting the syscall entry target
at dispatch risks too little lead time and poor coverage of later paths.

## No-kernel prototypes

The static prototype identifies imported I/O/pthread calls and an existing
canonical 7–15-byte NOP at most 256 bytes before the call. It replaces that NOP
with an equal-length RIP-relative T1/T0 data hint to the instruction after the
call. Recognized function labels, direct calls with symbolic targets, `j*`
branches, returns and syscalls reset the search. This disassembly heuristic is
not a full CFG analysis; it does not explicitly reset on indirect calls or the
`loop` instruction family. No address or layout moves; reversing every patch
reconstructs the original bytes. Media has 22/14/14 sites. This is a static
binary-analysis prototype, not yet an integrated LLVM compiler transform.

The dynamic prototype reads the original return PC, hints one/two/four contiguous
cache lines, and tail-jumps to libc with the original arguments and stack.
I/O-only and I/O+pthread scopes were screened. Matching NOP twins retain the
pointer load, tail jump, linker cost and layout. A hint-free interposer can itself
change performance; comparison only with the original would be insufficient.

Unversioned condition-variable forwarding failed a CLOCK_MONOTONIC regression
inside the benchmark Jammy image. Explicit `GLIBC_2.3.2` lookup/export corrected
the tested cases. Three pre-measurement setup attempts are excluded; the selected
I/O-only confirmation arm does not interpose condition-variable functions.
Other collection/setup exclusions are explicit in `R/EXCLUSIONS.json`.

The complete screen is in `R/analysis.json`. Against the geometric mean of the
bracketing baselines, static T1 observed +1.16/+1.36/+1.27% CPU efficiency across
MovieId/Compose/Rating; these are **selection observations, not confirmed gains**.

The fresh confirmation gives the following CPU-efficiency speedups. Brackets
are paired 95% log-ratio t intervals, five pairs per comparison.

| Service | Static T1 vs original/exact NOP twin | Dynamic I/O two-line T0 vs same-layout NOP |
|---|---:|---:|
| MovieId | +0.27% [−0.37%, +0.92%] | −0.04% [−0.60%, +0.52%] |
| ComposeReview | +0.02% [−0.23%, +0.27%] | −0.17% [−0.83%, +0.50%] |
| Rating | +0.33% [−3.43%, +4.23%] | +0.01% [−1.65%, +1.69%] |
| Sum of the three measured service CPU costs | +0.14% [−0.64%, +0.93%] | −0.10% [−0.65%, +0.45%] |

Dynamic T0 versus original gives +0.14/+0.06/+0.19% for the individual services
and +0.11% [−0.55%, +0.78%] for their sum. Every comparison includes zero.
All 20 trials pass request-rate/error/restart/accounting checks. Rating is noisy;
retain every pair rather than exclude inconvenient observations. Fixed-offered-
rate normalization is retained as a sensitivity calculation; it does not support
a 1% claim either. CPU/request uses the counter window and the full-run achieved
request rate, so it is not an exact per-window request counter.

There is also no consistent user-code miss reduction in confirmation. Static T1
changes user L2I misses/request by +4.7/+0.9/+25.6%; dynamic T0 versus NOP changes
them by +0.5/−0.3/+12.2%. These are auxiliary cross-trial observations, not kernel
miss measurements or proof of the source of timing variability.

The tested policy has low priority as a universal Class A optimization. It
targets a small user return region; the dominant Media kernel paths remain
outside its direct target set. The requested all-workload ≥1%, ideally 3–5%,
goal remains unmet. Earlier confirmed FeedSim/FleetBench gains retain their
specific target-prediction mechanisms and do not establish this generalization.

The same static rule was transferred to the unchanged durable MySQL workload,
adding standard file-I/O APIs (`pread/pwrite`, `fsync/fdatasync`, `open`, etc.) to
the eligible call families. It finds 143 padding sites among 2,701 eligible
static calls. Actual `/proc/PID/exe` hashes match each selected executable.
At 400 offered TPS, the bracketed screen observes **T0 +0.38%, T1 +0.33%** CPU
efficiency; baseline end/start drift is −0.08%. All four trials have zero ignored
errors, approximately 402 TPS, and eligible baseline utilization. These small
single-screen observations are not confirmed gains or support for a 1% target.
The original executable is the exact NOP twin for both variants.

## Additional MPKI candidates

All standard SPEC CPU2026 refrate inputs were run to completion with unchanged
optimization flags, one saturated core and fixed 2 GHz. LLVM output SHA-512
digests and GCC assembly outputs match the reference. This is direct workload
profiling, not an official SPEC score.

| Workload/input scope | User L2I MPKI | FE | BE | Bad speculation | Retiring |
|---|---:|---:|---:|---:|---:|
| 723.llvm_r, both reference inputs | 1.489 | 39.6% | 15.5% | 17.7% | 27.5% |
| 721.gcc_r, all three reference inputs | 0.672 | 26.2% | 31.0% | 13.3% | 29.8% |
| GCC `gcc-pp.c -O2 -fpic` only | 1.098 | 35.0% | 17.7% | 17.0% | 30.6% |

Aggregate MPKI uses summed misses / summed instructions, not an average of input
MPKIs. LLVM is a new validated ≥1-MPKI AOT candidate with a useful frontend share.
GCC's selected compilation job qualifies individually; its full reference mix
does not. Both spend less than 1% of CPU time in the kernel in the resource-checked
non-interval runs. Their opportunity is user call-chain/code behavior.

Long single-read Top-down totals were inconsistent for some compiler inputs.
All five inputs were rerun with one-second `perf stat -I 1000` reads, following
[Linux perf's counter-reset guidance](https://github.com/torvalds/linux/blob/master/tools/perf/Documentation/topdown.txt).
Final breakdowns use those intervals. Outer child-resource accounting with this
perf interval mode captured only profiler CPU time, so compiler kernel fractions
come from the original runs whose CPU totals agree with task-clock; those two
sources are explicitly separated in the analysis.

No new general A-2 AOT workload with **whole-workload L2I MPKI ≥10** is established
by this campaign. Existing FleetBench Proto and the generated A-1 cases remain
the high-MPKI examples. Silo's MPKI around 9 does not make it frontend-bound
(earlier BE about 75%). Kernel-only, L1I, branch, idle-wakeup and artificial
interleaving MPKIs must not be substituted for this criterion.

## Related work and next decision

[pTask (MICRO 2016)](https://ieeexplore.ieee.org/document/7783706/) uses OS task
boundaries to capture/prefetch OS and application instruction streams, with
kernel routines and additional hardware registers. Its reported gains are not
a software-only upper bound for this host.
[Hierarchical Prefetching (ASPLOS 2025)](https://www.research.ed.ac.uk/en/publications/hierarchical-prefetching-a-software-hardware-instruction-prefetch/)
uses software-identified code bundles with hardware replay. It supports exploring
coarser, earlier targets, but likewise does not establish a deployable x86
software-only gain.

User-mode prefetch of privileged kernel addresses is not a reliable supported
substitute for an in-kernel hint. PTI can also remove kernel mappings from user
page tables; see [Linux PTI](https://kernel.org/doc/html/v5.18/x86/pti.html).
Historical supervisor-prefetch side-channel interpretations require care; see
[Speculative Dereferencing of Registers](https://arxiv.org/abs/2008.02307).
No mitigation or mapping changes were made here.

## Validation and retention

All ten platform wrappers restored their saved state across 400 CPU contexts.
The audit checked 130 counter files, all 31 accepted Media screen/confirmation
trials, twelve valid diagnostic loads, four MySQL transfer trials, and reference
output validation for both sets of five compiler runs. Counter values are
numeric and fully scheduled. Five interval-counter aggregates reproduce their
raw interval sums. The original five compiler Top-down breakdowns and one MySQL
end-baseline breakdown have explicit quality warnings; they are not used as
final Top-down evidence. Primary timing/MPKI and the kernel stall model do not
depend on those breakdowns.

All sixteen prefetch/NOP interposer variants rebuild byte-identically to the
experiment binaries. Thirty-four socket/thread/errno/monotonic-condition tests
pass in the actual benchmark container image. Static patches reverse exactly
to their original binaries; MySQL verifies the loaded executable hash.

The [published analysis](../llvm_prefetchit/migration/evidence/class_a_kernel_20260923/analysis.json)
and accompanying protocol/exclusion summaries are retained in Git. Raw confirmation
counters, CPU accounting, client logs and the full reproduction archive remain local.
See the [publication inventory](../llvm_prefetchit/migration/evidence/README.md) for
the exact committed subset; generated binaries, plans and traces are omitted.
