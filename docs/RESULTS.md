# Results — what is proven, and what was re-verified on 2026-09-15

Source of truth for the canonical numbers: `llvm_prefetchit/migration/core_results.tsv`
and `REPRODUCIBILITY.md` (frozen-platform, NOP-controlled, ≥3 interleaved reps).
The "re-verified" column is the single-shot check made after the September
restore on the same Xeon 6787P host, frozen at **2.0 GHz** (acpi-cpufreq; the
canonical Verilator/JCodeStream rows were taken at 3.8 GHz with intel_pstate,
Django/FeedSim at 2 GHz). One rep each — direction and mechanism (MPKI, IPC)
are the acceptance criteria, not the exact ratio.

| stage | workload | mechanism | canonical | re-verified 2026-09-15 (1 rep) | status |
|---|---|---|---|---|---|
| 2 | Verilator qsort (Chipyard DualMegaBoom) | profile-free static plan through the LLVM pass | **1.080x** (PGO 1.076x), L2I −5% | simulator rebuilt from the pinned sources (clang-19 -g, single TU; base 48.15 s / 57.0 MPKI at 3.8 GHz vs reference 51.29 s / 58.6). **First pass: static 1.001x, PGO 0.999x, MPKI unchanged** — root cause found and fixed (below); post-fix run: PGO RET cov90 **1.014x vs base / 1.021x vs its NOP twin**, MPKI 57.1→53.3 (−6.6%); static top1k callsite 1.004x / 1.003x, MPKI −0.2%; static top5k / nested top3k / mixed b8 all ≤1.003x (`results/verilator_repro_20260915b/measure/summary.md`) | **not reproduced**: mechanism confirmed (PGO cuts misses as in the reference) but time gain 2% not 7.6%, and the profile-free plan is inert (see below) |
| 2 | arcilator MegaBoom | static IR callsite prefetch (s4la16) | **1.051x**, MPKI 76.7→71.2 | not run (its static plan is a callsite plan too — re-check with the re-anchoring tools before trusting it) | pending |
| 3 | Django (DCPerf) | manual `d4_next` method-pointer prefetch | **1.490x**, MPKI 84.6→35.0, IPC 0.351→0.603 | base 6.54 QPS / MPKI 85.4 / IPC 0.340 → d4_next 9.57 QPS / MPKI 35.3 / IPC 0.599 = **1.463x**, 100% availability, 0 migrations | reproduced |
| 3 | FeedSim (DCPerf) | manual `d16_target_next` | **1.073x** (300 s), MPKI 8.07→1.71, IPC 0.326→0.409 | 0.175 → 0.217 QPS (**1.24x**, 21 vs 26 responses in 120 s — coarse), MPKI 7.84→1.38, IPC 0.322→0.419 | reproduced (mechanism exact; QPS ratio needs the 300 s × 3 protocol) |
| 4 | JCodeStream | HotSpot C2 V4 entry burst (128 B × 32 lines) | **1.285x**, MPKI 14.9→4.7 | stock 18.40 ms → v4 16.71 ms = **1.101x** at 2.0 GHz, MPKI 71.8→22.1 (−69%), IPC 0.753→0.956 | reproduced (smaller time gain at 2 GHz: fewer core cycles per L3-hit code miss — the frequency axis) |
| 4 | WideApi (4000 handlers, fixed 4-core capacity) | gated V4 (`MinBytecode=256`) | **1.110x** QPS, p99 −19.5%, MPKI 34.9→12.3 | stock 14461 → v4_g256 16037 QPS = **1.109x**, p50 6.22→5.72 ms, p99 13.62→11.05 ms, MPKI 38.55→13.41, IPC 0.782→0.920 | reproduced |
| 1 | microbenchmark | `prefetchit0/1` vs `prefetcht1` | prefetchit: no iTLB/STLB warming, no L1I/L2I change (HW no-op) | binaries rebuilt (clang 19.1.7); sweep not re-run | pending |

Negative / boundary results (unchanged, see `docs/archive/PAPER_RESULTS_AND_FEEDBACK.md`):
memcached 1.000x, PostgreSQL TPC-C prefetch-only ≤ +0.3% (PGO layout +8%),
DeathStarBench PostStorage neutral (diffuse, DSO-resident misses), MicroSuite
Router/HDSearch/Recommend neutral under matched NOP baselines (the July +198%
was a build confound), 40+ DaCapo/Renaissance workloads L2-resident.

## Verilator: the layout-shift bug found by the re-verification

The pass emits exact `symbol+offset` targets taken from the baseline binary.
Every injected rip-relative `prefetcht1` (7 bytes) pushes the rest of its
function forward, so in `eval_nba__0` (985 of the 1,000 static sites) the k-th
site's prefetch pointed 14·k bytes *before* its real return continuation —
only 13 of 1,968 prefetches hit the planned cacheline, and neither the static
nor the PGO plan changed MPKI (`llvm_prefetchit/results/verilator_repro_20260915/measure/`,
3 reps: static 1.0011x vs base / 0.9979x vs its NOP twin; PGO 0.9985x /
1.0066x, MPKI 57.0→55.5). The restored pass source (pinned `8f6f704`) has no
compensation, so the canonical 1.078x/1.076x could not have come from this
exact code path; treat them as unverified until the post-fix run below
reproduces them. Fix: the pass now defers emission and adds the bytes of all
prefetches injected earlier in the target's function
(`-prefetchit-layout-compensation`, default on; `docs/design.md`).

### Second finding: the static site choice, not only the operands

After exact re-anchoring (`tools/reanchor_prefetch_targets.py`, 1968/1968
prefetches on their continuation) the `static_top1k_callsite_b1` plan still
executes its prefetches only ~5·10⁷ times per 100k simulated cycles (+0.09%
instructions) and leaves MPKI unchanged. The traces explain it: of 12,629
RET-miss samples with an identifiable producing call, only **15.3%** are
produced by one of the 1,000 planned call sites, while the 1,000 hottest
producing calls would cover 65%. The profile-free footprint ranking picks, for
each hot continuation cacheline, the call with the largest callee — usually
not the call that actually returns into it on this build. The re-verification
therefore swept three more profile-free RET plans (mixed-call-ret-d1 b8,
top-5k callsite, nested top-3k callsite) against the PGO ceiling — all
neutral (≤1.003x vs their NOP twins). Verdict for stage 2 on Verilator:

| variant (3 reps, 3.8 GHz, uncore pinned) | vs base | vs NOP twin | L2I MPKI |
|---|---:|---:|---:|
| PGO RET cov90 (8,577 sites, 14,184 prefetches) | 1.0136x | **1.0211x** | 53.31 (−6.6%) |
| static top1k callsite b1 (2,000) | 1.0043x | 1.0025x | 56.94 |
| static nested top3k callsite b1 (6,000) | 1.0028x | 0.9999x | 57.03 |
| static top5k callsite b1 (10,000) | 1.0026x | 1.0002x | 56.95 |
| static top1k mixed-call-ret-d1 b8 (7,750) | 0.9974x | 0.9993x | 56.92 |
| base | 1.0000x | – | 57.05 |

The profile-guided placement removes the same share of misses as the
reference (−6.6% vs −7.2%) but buys 2% instead of 7.6%: this host's baseline
is 6% faster than the reference at identical instruction counts (IPC 0.62 vs
0.56, MPKI 57.0 vs 58.6), i.e. code misses are cheaper here, and the NOP twin
shows the 14k injected instructions themselves cost 0.7%. The static family
does not reach the ceiling because of site selection (above). The pass-level
fixes (layout compensation, ranked site anchoring) and the post-link
re-anchoring/drift tools are now part of the pipeline; the site-selection
problem is the open research item (`docs/PLAN.md`, stage 2).

## Why the numbers move between hosts/clocks

- Gains grow with core clock where misses are cold (Django 1.49x @2 GHz →
  1.72x @3.4 GHz) and shrink where the code stays warm (FeedSim 1.073 → 1.043).
- Uncore left floating credits the prefetch arm ~17% (June's 1.22x Verilator
  numbers). Always `freeze_platform.sh`.
- FeedSim at 200M i-cache iterations completes ~0.2 responses/s: 120 s runs
  quantise QPS to ±5%; use 300 s and 3 reps for a citable ratio.

## Files

- Raw rows of the re-verification: `llvm_prefetchit/results/repro_20260915/`
  (`feedsim_closedloop/runs.csv`, `django_manual/runs.csv`, `jcs_ab.csv`,
  `wideapi_ab.csv`); Verilator: `llvm_prefetchit/results/verilator_repro_20260915/`
  (pre-fix) and `verilator_repro_20260915b/` (post-fix: traces, plans, resolved
  plans, binaries, NOP twins, `measure/runs.csv`).
- Canonical evidence CSVs: `llvm_prefetchit/migration/evidence/`,
  `jit_prefetch/results/{jcs3_final,wideapi_confirm}.csv`, `flat_codegen/results/`.
