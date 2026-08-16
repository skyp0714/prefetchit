# Paper Status: Results Tables and Feedback

Date: 2026-08-15. Compiled from `DATACENTER_BENCHMARK_ATTEMPT_MATRIX.md`,
`DATACENTER_PREFETCH_5BENCH_SUMMARY.md`, and raw CSVs (spot-verified against
`llvm_prefetchit/results/datacenter_goal_20260708/` and
`static_*_prefetch/results/`).

## Table 1 — Datacenter workloads: manual/static source injection vs PGO compiler injection

"Manual" = source-level `__builtin_prefetch` of control-flow data structures.
"PGO" = LBR/L2I-miss profile → plan → LLVM `prefetchit-inject` pass.

| Workload (suite) | Baseline L2I MPKI | Manual/static source | PGO compiler pass | Notes |
|---|---:|---:|---:|---|
| Django (DCPerf) | 84.5 | **+135.9% QPS** (2.36x, `d16`, MPKI→47.0) | – | Generated `ICache_Buster` method-pointer array prefetch |
| FeedSim (DCPerf) | 3.0–7.1 | **+7.4…+31.2% QPS** (best confirmed `i50m_q20_t2 d64`, MPKI 5.0→1.3) | – | `ICacheBuster::methods_` future-target prefetch |
| memcached 1.6.14 | 10.7 | **+15.3% mean / +28.8% best** over 5×120s paired reps (4/5 positive) | +5.6% | `struct conn` function-pointer targets (`allpf`) |
| Router (MicroSuite) | 85.1 | −8.0% (manual `ProcessRequest` pf) | **+198.3% QPS** (cov100, d32) | ⚠ validity check needed: treatment variant is `_noomp`; instructions/response drops 542k→326k, which prefetch cannot explain |
| SetAlgebra (MicroSuite) | 24.5 | no valid positive | **+20.0% QPS** (cov25, d32) | Higher coverage over-injects |
| Recommend (MicroSuite) | high | – | +3.9% | |
| HDSearch (MicroSuite) | 79.5 | invalid runs | +6.6% (30s screen only; 120s unstable) | Not countable |
| PostgreSQL | high | +0.87% TPS | +0.2% | High MPKI but no meaningful gain |
| Silo (TailBench) | mid | −0.3% | +2–3% (short runs, not robust) | |
| Other TailBench (Xapian/Moses/Masstree/Shore/…) | mixed | – | neutral to slower | |
| FleetBench proto arena | high | +1.1% | +0.8% | Neutral |
| HAProxy / Redis / nginx / LevelDB / RocksDB / interpreters / TAO / video | low | ≤+0.5% or screen-only | neutral | Low MPKI ⇒ nothing to gain |

## Table 2 — Static compiler pass vs PGO oracle (Verilator chipyard-qsort, real machine, 3 reps)

This is where the *automated* static analysis (profile-free) is actually
compared against the LBR oracle through the same LLVM pass.

| Branch class | Baseline runtime | PGO-oracle best | Static best | Static / oracle |
|---|---:|---:|---:|---:|
| COND | 343.50 s | **+25.7%** (cov50, 60.9k inj) | **+22.6%** (fetch-gap 100k) | 88% of oracle gain |
| RET | 343.24 s | **+18.9%** (cov100, 11.3k inj) | **+17.0%** (nested top5000 + spread-64k, b8, 38.5k inj) | 90% of oracle gain |

Sources: `llvm_prefetchit/results/static_cond_autotune/latest/summary.md`,
`static_return_prefetch/results/ret_cost_v2_runtime/.../ret_pgo_static_injection_scaling_points.csv`.

Note the static plans need ~1.6–3.4× more injections than the oracle to get
there — a good "cost of being profile-free" framing for the paper.

## Feedback

### Biggest gap: the static-compiler story has one workload

The central claim (static analysis approaching the LBR oracle) is currently
proven only on the Verilator qsort binary. The datacenter successes are either
manual source changes (FeedSim/Django/memcached) or PGO. The attempt matrix
itself flags this. Priority actions:

1. Run the static COND/RET pipelines through the compiler pass on the three
   manual-positive workloads and on Router/SetAlgebra. Even partial capture
   (e.g. static gets 1.3x of Django's 2.36x) makes the generality claim.
2. If static analysis fundamentally cannot find the data-structure-driven
   targets (FeedSim/Django/memcached), say so explicitly and position the
   three techniques as a hierarchy: static (free) < PGO (profile cost) <
   manual (semantic knowledge). That taxonomy is a solid paper skeleton.

### Validity issues to fix before submission

- **Router 2.98x**: baseline `clang_base` vs treatment `cov100_noomp` differ
  in more than prefetching (OpenMP setting; instructions/response drops 40%).
  Re-run with an identical-except-plan baseline (`base_noomp`) or the number
  will not survive review.
- **memcached noise**: 4/5 reps positive, one 0.94x. Report all reps with a
  paired test / confidence interval, not just the mean.
- **FeedSim spread**: gains range 1.07–1.50x across configs; report the full
  config matrix, not the best cell.
- **PGO cov75 qsort stdev 26s** (vs <1s elsewhere) — investigate or rerun.

### Missing baselines a reviewer will demand

- **Standard FDO/BOLT/Propeller comparison.** In this project "PGO" means
  profile-guided *prefetch* insertion. Reviewers will ask whether profile-
  guided *code layout* (BOLT) removes the same L2I misses for free. Show
  prefetch gains on top of a BOLT-optimized binary, or explain why layout
  cannot fix these misses (e.g. dynamic dispatch targets are layout-hostile
  — the FeedSim/Django/memcached cases actually support this well).
- **Hardware context**: quantify what FDIP already covers; the microbenchmark
  TLB finding (data `prefetcht0` warms iTLB/STLB, `prefetchit0/1` does not)
  is a genuinely novel ISA-level observation — promote it to a first-class
  section, it also justifies using `prefetcht1` for code.
- **Overhead accounting**: code-size growth, instruction-count increase
  (visible in the CSVs: up to +24% instructions on qsort cov100), and a
  "do-no-harm" table on low-MPKI workloads.

### Benchmark coverage

Coverage of suites is already broad (DCPerf, TailBench, MicroSuite,
FleetBench, SPEC, services). What is missing is not more workloads but:

- A one-page **screen table**: workload → L2I MPKI → included/excluded reason.
  The many "low MPKI, skipped" rows are evidence of applicability limits, not
  failures — present them as such.
- 1–2 **large-code JIT/managed workloads** (DaCaPo/Renaissance on JVM are
  already in `benchmarks/tools`) would counter the "only C/C++" critique;
  even a negative result with an explanation (JIT code moves, plans go stale)
  is publishable discussion.
- A **cross-workload generalization** experiment for the static ranker: tune
  feature weights on qsort, evaluate untouched on another Verilator config or
  workload — this directly addresses the overfitting concern stated in the
  project goal.

### Statistical/presentation checklist

- Paired A/B interleaved runs (already done for memcached — do everywhere).
- Report median + IQR or mean ± CI over ≥5 reps for service benchmarks.
- Injection-count vs speedup scaling curves (data already exists for qsort)
  make the static-vs-oracle "efficiency gap" visual and compelling.

---

## REVISION 2026-08-15 (evening) — frozen-platform re-measurement supersedes the tables above

Platform forensics (full chain in
`llvm_prefetchit/results/paper_goal_20260815/CONFIG_LOG.md`) found every
pre-existing Verilator number and the July datacenter numbers were
frequency-confounded: on default/partial configs the uncore floats, baseline
demand code misses do not trip the uncore boost heuristic (~17% IPC penalty),
and prefetch variants "wake" the uncore and get credit for it. All rows below
are frozen-platform (core min=max fixed + uncore min=max pinned, EPP=0):
`scripts/configure_fixed_frequency_v2.sh`.

### Verilator qsort (fixed 3.8GHz, full 538240 cycles, 3 reps)

| variant | runtime | speedup | injections |
|---|---:|---:|---:|
| baseline | 284.80s ± 0.3 | – | – |
| **static_top1k_callsite_b1 (RET static)** | 264.22s ± 0.18 | **1.078x** | **1,000** |
| pgo_cond_cov25 (best PGO) | 264.93s ± 0.21 | 1.075x | 20,573 |
| pgo_ret_cov90 | 265.54s ± 0.21 | 1.073x | 7,240 |

Headline change: June's "static ≈ 90% of PGO oracle (1.226x vs 1.257x)"
becomes **"profile-free static ≥ PGO oracle at 20x fewer injections"**. The
June variant ranking itself was DVFS-contaminated; the honest winner is the
RET/callsite static family, not the COND fetch-gap family. Cross-payload
transfer (mm/dhrystone/median): static 1.075–1.079x ≡ PGO 1.076–1.077x,
zero re-tuning. Combined RET+COND plans reduce MPKI further (to 50.7) but
injection overhead cancels the time gain — ~1.08x is the workload's honest
ceiling and the 1000-injection plan sits on it. Over-injection actively
hurts (pgo_cond_cov100: 0.948x).

Dual-regime framing for the paper: fixed-platform 1.078x microarchitectural
+ default-platform ~1.2x wall-clock (sw code prefetch also wakes the uncore
— a real deployment effect worth reporting separately, not conflating).

### Datacenter manual rows re-verified (2GHz fixed + uncore pinned)

| workload | July claim | frozen-platform | verdict |
|---|---:|---:|---|
| Django d4_next | 1.805x (audited) / 2.36x (raw) | **1.490x ± 0.01** (MPKI 84.6→35.0, 3 reps) | real, still headline |
| FeedSim seed2_d16_target_next | 1.085x | **1.050x** (MPKI 7.2→1.6, 3 reps) | real, compressed |
| memcached allpf | +15.3% mean | **1.0002x ± 0.005** (5 pairs) | neutral under paired harness (MPKI 0.04 there — July's c2048_w8 stress config still unchecked) |
| PostgreSQL top32 vs NOP | +1% | 1.0232x ± 0.0210 vs PGO 1.0117x ± 0.0267 | static ≈ PGO, no PGO advantage |

Router +198% remains quarantined (baseline confound, Table 1 note).

### 2026-08-16 addendum — target-driven exploration (≥5%/≥10% outside error bars)

Final standings: Django **1.490x** ✓✓, Verilator static **1.078x** ✓ (honest
ceiling proven ~1.08x), FeedSim **1.073x** ✓ (best config ICACHE_ITERS=200M
t2; curve peaks there), PostgreSQL ✗ structural — misses diffuse over
thousands of lines, 336-injection plan cuts only ~3% of misses, more
coverage self-defeats (top64: 0.983x); best config found (c8 tpcb
synchronous_commit=off, CPU-bound, MPKI 25) still yields 1.006±0.015.
memcached ✗ dropped (neutral under all controlled configs).

Broad new-workload screens all excluded (loaded L2I MPKI): clang 0.37,
node.js 1.71, Cassandra 0.44 (idle JVM reads 11.9 — screen under load!),
QEMU TCG 0.005. i-cache-bound workloads are rare; the showcase set is
representative.
