# Paper-Goal Campaign 2026-08-15 — Config Log

Goal: show static or manual prefetch (a) significantly beats baseline and
(b) approaches or beats PGO, per workload. Every experiment in this campaign
records its exact config here.

## Machine state (differs from July campaigns!)

- Intel Xeon 6787P, 86 cores, 1 socket, NUMA 1.
- cpufreq driver is now **acpi-cpufreq** (July campaigns ran intel_pstate).
  Set: governor=performance, scaling_min/max=2000000 kHz on all policies,
  `/sys/devices/system/cpu/cpufreq/boost=0` (turbo off).
  `scripts/final_campaign_common.sh` patched to assert frequency under both
  drivers (fc_turbo_disabled/fc_perf_pct helpers).
- kernel.perf_event_paranoid=-1, kptr_restrict=0 (for perf stat/record).
- Disk cleanup (user-approved): ~/.cache/bazel (14G), benchmarks/downloads
  (7.4G), benchmarks/gem5/m5out (9.5G) deleted → 31G free.

## Baseline verdict (from audited July campaigns, no rerun)

Sources: `results/final_campaign_20260711/final_report/final_report.md`,
`results/pgo_goal_20260713/final_report/report.md`.

| Workload | static/manual (audited) | PGO (audited) | Goal status |
|---|---:|---:|---|
| Django (DCPerf) | manual 1.805x±0.009 | N/A (JIT-free manual path only) | ✓ manual ≫ baseline, no PGO counterpart |
| FeedSim (DCPerf) | manual 1.085x±0.004 | N/A | ✓ |
| Verilator qsort COND | static 1.226x±0.003 (fetch-gap top100k) | 1.257x (cov50) | ✓ static ≈ 90% of PGO |
| Verilator qsort RET | static 1.170x (nested top5000 spread64 b8) | 1.189x (cov100) | ✓ |
| PostgreSQL | manual 0.999x | **1.0609x±0.019** (cov25_d8_32_b1_o0, simple, c8) | ✗ → this campaign attacks this gap with static plans |
| memcached | manual 0.995x (audited; old +15% was low-MPKI-artifact) | 1.0048x | – both neutral at true MPKI 0.22-1.2 |
| Router / SetAlgebra / Recommend / HDSearch | neutral/invalid | neutral (historical +198%/+20% rejected by audit) | – |
| TailBench 7 native | neutral | neutral | – |

## Experiment 1: PostgreSQL static compiler-pass plans

- Binary: `llvm_prefetchit/work/datacenter_goal_20260708/postgres/install_base/bin/postgres`
- Planner: `static_return_prefetch/tools/static_branch_target_plan.py`
- FAILED FIRST ATTEMPT (kept for the record): `--rank-by structural-hotpath
  --max-injections {84,336,1000}` with planner defaults produced 0-injection
  plans — the planner's `--function-regex` defaults to "VTestDriver"
  (Verilator-fit) and `--top-functions 4`; on postgres nothing matches.
- Working config (mirrors the audited "general-v5" pattern from
  `scripts/generate_setalgebra_stable_static_plans.sh`):
  `--top-functions 0 --min-function-size 16 --branch-types CALL,COND,RET,UNCOND
   --target-modes body --site-depth 8 --rank-by structural-hotpath
   --max-injections-per-target-function 16 --max-injections-per-target-cacheline 1
   --body-cachelines-per-function 64 --min-body-target-size 16
   --skip-same-cacheline --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0`
- Variants (aggressiveness = body-target-functions / max-injections):
  - `pg_body_top8_b84_d8_o0` (8 funcs, ≤84 inj — matches PGO winner's 84-injection budget)
  - `pg_body_top16_b168_d8_o0` (16 funcs, ≤168)
  - `pg_body_top32_b336_d8_o0` (32 funcs, ≤336)
  - `pg_body_top64_b672_d8_o0` (64 funcs, ≤672)
- SECOND FAILURE + fix (plans_v2): plans generated against
  `install_base/bin/postgres` have **no DWARF** (installed copy is stripped of
  debug sections), so addr2line returned `file-basename:0`; the pass requires
  `site.line > 0` (`findSiteInstructions` returns empty on line==0) →
  `missing_site_loc`, 0 injections in all built binaries (assembly_prefetches=0,
  sha identical to baseline). Fix: rebuild the backend in the build tree
  (`-O3 -g`, `-ffile-prefix-map` to datacenter_sources/postgres so plan srclines
  match compile-time DILocations), snapshot it as
  `postgresql_static/postgres.baseline.debug`, regenerate the same 4 variants
  against that binary (`plans_v2/`), then build (`bins_v2/`) and eval.
  Orchestrated by `scripts/run_paper_goal_fixup_20260815.sh`; the first
  campaign's stage-4 evals of the 0-injection binaries were skipped (master
  killed after stage 3 launched; verilator measurement kept running).
- Structural targets sanity check (top8 plan): get_rule_expr, _jumbleNode,
  RewriteQuery, transformFromClauseItem, ExecInitExprRec, ServerLoop,
  create_plan_recurse — parser/planner/executor path, plausible for
  simple-protocol tpcb-like without any profile input.
- Build: `scripts/build_postgresql_lbr_pgo_variants.sh` with
  `BUILD_ROOT=work/pgo_goal_20260713/bins/postgresql_simple_c8_tune1/build` (reuse),
  `PLANS=results/paper_goal_20260815/postgresql_static/plans`
- Eval: `scripts/run_final_postgresql_paired.sh`, QUERY_MODE=simple CLIENTS=8
  DURATION=30 REPS=5 (matches audited PGO row config); PGO reference arm =
  existing `cov25_d8_32_b1_o0` binary rerun same-day.
- Pinning: server cores 1-30, client 31-70, control 0 (built into harness).

## Experiment 2: Verilator cross-payload static transfer

- Binaries (all built June 28, same toolchain):
  - base: `benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig`
  - static: `results/static_cond_autotune/static_cond_autotune_20260628_212242/runs/static_gap100k_cur0_skip/bin/...` (fetch-gap 100k, current-site, skip-same-cacheline, b1, o0 — the qsort static winner)
  - pgo: `results/cond_sampleip_compare/cond_sampleip_compare_20260628_014845/runs/pgo_cond_cov50/bin/...` (qsort-profile PGO winner)
- Payloads: riscv-tests mm/dhrystone/median (+qsort control), `+max-cycles` per payload chosen after duration probe.
- Question: does the qsort-tuned static plan transfer to other payloads of the
  same simulator binary, and does the qsort-PGO plan overfit?
- Runner: perf stat `instructions,cycles,cpu/event=0x24,umask=0x24/u`, sim
  pinned via taskset, interleaved variant order, ≥3 reps.

## Machine-state regression discovered (2026-08-15)

Full-length qsort reproduction (same June binaries, +max-cycles=538240, 3 reps,
`verilator_qsort_fullcycle/`): baseline 533.5s vs June's 343.5s (55% slower),
identical MPKI 58.5, IPC 0.88→0.57. Static/PGO gains shrink from 1.226x/1.257x
to 1.033x/1.049x — same direction/ordering, much smaller magnitude, because the
baseline is now backend-bound by something other than the frontend.

Root-cause evidence: kernel cmdline now carries `intel_pstate=disable`
(acpi-cpufreq active; July campaigns ran intel_pstate + HWP hints via
x86_energy_perf_policy). Uncore frequency scaling is unconstrained
(min 800MHz / max 2.2-2.5GHz, driver intel_uncore_frequency); without HWP/EPP
hints the uncore likely idles low, inflating L2/LLC/memory latency. Follow-up:
pin uncore min=max and re-measure one qsort baseline.

Cross-payload transfer (150k cycles, 3 reps, `verilator_crosspayload/runs.csv`):
static 1.034-1.040x and PGO 1.048-1.054x on ALL of mm/dhrystone/median/qsort,
baseline MPKI 58.5 payload-invariant → the qsort-tuned static plan transfers
unchanged; ordering static ≈ 70% of PGO holds everywhere.

PostgreSQL current-state paired results (plain baseline, AB/BA n=5 each):
PGO cov25 ref 0.9795x±0.0065 (July layout-controlled: 1.0609x — does NOT
reproduce), static top8/16/32/64: 1.0078/1.0009/1.0100/1.0103 (±~0.01-0.02).
NOP-layout-controlled reruns queued (`run_pg_nop_controls_20260815.sh`).

gem5 screen: L2I MPKI 0.001 (base) / 0.002 (eventq-prefetch-v1) with X86O3CPU
se.py busy loop → excluded as an i-prefetch workload; its code footprint is
too small. (Its eventq work targeted data prefetch, separate thread.)

## Experiment 3: gem5 as new simulator workload

- `prefetchit/build/X86/gem5.opt` (+ existing `gem5.opt.eventq-prefetch-v1`
  manual variant and `worktrees/gem5-callback-prefetch`) — screen L2I MPKI
  first, then evaluate existing manual eventq-prefetch variant if MPKI is high.

## Platform forensics — regression root-caused (2026-08-15, post-reboot)

Timeline of the machine states (from `last reboot` + apt history):
- Jun 7–Jul 24: kernel 6.8.0-124, clean cmdline, **Ubuntu defaults**
  (powersave governor, EPP 128, turbo free, uncore unpinned) — the June
  campaigns ran HERE with no frequency fixing at all
  (`configure_fixed_frequency.sh` did not exist until Jul 11, and no June
  run.log records any freq setup).
- Jul 24: GRUB edit added `intel_pstate=disable ...` (+ 2 reboots 25 min
  apart); Jul 28: unattended-upgrade installed kernel 6.8.0-136 (not booted
  until Aug 15).
- Aug 15: GRUB reverted, rebooted into 6.8.0-136, intel_pstate active again.

Elimination results (all same binaries, qsort, uncore pinned min=max unless
noted):
| config | 150k probe | full 538240 | core GHz | IPC |
|---|---:|---:|---:|---:|
| acpi-cpufreq 2.0 + uncore floor (Aug 14) | – | 533.5s | 2.0 | 0.57 |
| intel_pstate 2.0 + uncore floor (Aug 15) | – | 532.5s | 2.0 | 0.57 |
| intel_pstate 2.0 + uncore pinned | 127.9s | 456.9s | 2.0 | 0.67 |
| fixed 3.8 (EPP=0, min=max) + uncore pinned | 79.9s | 285.1s | 3.801 | 0.560 |
| **Ubuntu defaults (June state)** | **93.7s** | (≙343.5s) | 3.795 | 0.476 |

Kernel 124 vs 136: no effect. BIOS: no reflash (AMI 1.5, 12/2025), HW
prefetchers enabled (MSR 0x1a4=0), memory 8×64GB@6400, SNC off, turbo MSRs
normal. LLC-load-misses ≈ 0 during qsort → everything is served from LLC;
only core clock and uncore (mesh/CHA) clock matter.

**June's 1.226x/1.257x are uncore-DVFS-contaminated.** Under defaults all
variants run at the same ~3.795GHz core clock, but the uncore floats: base's
demand code misses do not trip the uncore boost heuristic (IPC 0.476 vs
0.557 with uncore pinned = 17% penalty), while the prefetcht1 traffic of the
static/PGO binaries drives the uncore up (static IPC 0.595 floating vs 0.604
pinned; pgo 0.628 vs 0.635 — nearly insensitive). Reproduction under
defaults today: base 93.7s / static 77.9s (1.203x) / pgo 75.8s (1.236x) vs
June-scaled 95.7/78.1/76.2s — exact.

Honest fixed-clock full-length numbers (3.8GHz min=max, EPP=0, uncore
pinned; MPKI matches June to 0.1): base 285.1s, static 275.0s (**1.037x**),
pgo 269.0s (**1.060x**).

Frozen config from here on: `scripts/configure_fixed_frequency_v2.sh`
(MODE=3.8ghz for single-core Verilator; MODE=2ghz for multi-core
PostgreSQL). Paper framing: default-configured servers really do see ~1.2x
wall-clock (sw code prefetch also wakes the uncore); the fixed-frequency
decomposition isolates the ~1.04-1.06x microarchitectural component.
