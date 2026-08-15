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
