# Datacenter Prefetch Search, 2026-07-08

## Current Outcome

Confirmed 1 benchmark so far: FeedSim `LeafNodeRank`. Within that single
benchmark, 5 configurations show at least 10% QPS improvement from static
control-flow-data-structure prefetching.

The optimization prefetches a future function pointer target from FeedSim's
generated `ICacheBuster::methods_` vector before the indirect call in
`ICacheBuster::RunNextMethod()`.

This counts as one benchmark toward the broader search target. It is a
static/data-structure result, not an LLVM PGO-pass result.

## Measurement Setup

- Workload root: `benchmarks/dcperf/benchmarks/feedsim`
- Baseline binary:
  `llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.base_nopf`
- Prefetch binary:
  `llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d64`
- Leaf startup sleep: 20 seconds
- Driver duration: 20 seconds
- Driver warmup: 0 seconds
- Graph options:
  `--graph_scale=21 --graph_subset=2000000 --num_objects=2000 --graph_max_iters=1`
- FeedSim affinity: `--noaffinity`
- External pinning: `PIN_THREADS=1` through
  `llvm_prefetchit/scripts/run_workload_l2_screen.sh`
- Core ranges:
  - t2 configs: `CORE=0-10`
  - t4 config: `CORE=0-18`
- Perf event:
  `cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/`
- All repeated results below use 3 paired samples: one screen run plus two
  confirmation runs.

## Prefetch Binary Check

`objdump` confirms the d64 binary contains a code prefetch and the baseline does
not.

d64:

```asm
<ICacheBuster::RunNextMethod()>:
  ...
  lea    0x40(%rsi),%rax
  divq   0x20(%rdi)
  mov    (%rcx,%rdx,8),%rax
  prefetcht0 (%rax)
  call   *(%rcx,%rsi,8)
```

baseline:

```asm
<ICacheBuster::RunNextMethod()>:
  ...
  mov    0x18(%rdi),%rdx
  mov    (%rdi),%rax
  call   *(%rax,%rdx,8)
```

## Confirmed FeedSim Config Results

| config | core range | reps | base QPS | d64 QPS | QPS speedup | base p95 ms | d64 p95 ms | base L2I MPKI | d64 L2I MPKI | base IPC | d64 IPC | avg migrations | observed CPUs union |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `i20m_q20_t2` | `0-10` | 3/3 | 2.180 | 2.563 | +17.6% | 13722.2 | 9572.5 | 2.970 | 0.807 | 0.681 | 0.849 | 24.5 | `0,1,2,3,4,6,7,8,9,10` |
| `i50m_q20_t2` | `0-10` | 3/3 | 1.270 | 1.667 | +31.2% | 19551.6 | 15622.8 | 5.052 | 1.282 | 0.472 | 0.619 | 23.8 | `0,1,2,3,4,5,6,7,8,9,10` |
| `i100m_q20_t2` | `0-10` | 3/3 | 0.890 | 1.147 | +28.8% | 17387.2 | 24919.6 | 6.668 | 1.651 | 0.379 | 0.517 | 16.8 | `0,1,2,3,4,5,6,7,8,9,10` |
| `i50m_q40_t2` | `0-10` | 3/3 | 1.307 | 1.603 | +22.7% | 19846.0 | 20027.2 | 5.007 | 1.258 | 0.472 | 0.617 | 20.0 | `0,1,2,3,4,5,6,7,8,9,10` |
| `i100m_q20_t4` | `0-18` | 3/3 | 2.643 | 3.113 | +17.8% | 18284.5 | 18268.1 | 7.052 | 1.718 | 0.365 | 0.494 | 35.2 | `0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18` |

Additional measured config that did not pass the 10% threshold:

| config | base QPS | d64 QPS | QPS speedup | base p95 ms | d64 p95 ms | base L2I MPKI | d64 L2I MPKI |
|---|---:|---:|---:|---:|---:|---:|---:|
| `i100m_q40_t2` | 0.987 | 1.060 | +7.4% | 18548.1 | 23513.5 | 6.646 | 1.605 |

Single-run candidates not yet repeated:

| config | base QPS | d64 QPS | QPS speedup | base L2I MPKI | d64 L2I MPKI | note |
|---|---:|---:|---:|---:|---:|---|
| `i50m_q20_t1` | 0.590 | 0.670 | +13.6% | 4.252 | 1.054 | low absolute QPS |
| `i100m_q20_t1` | 0.370 | 0.440 | +18.9% | 6.041 | 1.491 | low absolute QPS |
| `i50m_q20_t4` | 4.270 | 4.350 | +1.9% | 5.530 | 1.391 | MPKI improves but QPS does not |

## Distance Sweep

Single-run sweep on `i50m_q20_t2`:

| variant | QPS | p95 ms | L2I MPKI | IPC |
|---|---:|---:|---:|---:|
| baseline | 1.48 | 21945.7 | 4.977 | 0.474 |
| d4 | 1.44 | 17782.0 | 1.323 | 0.618 |
| d8 | 1.74 | 24028.8 | 1.969 | 0.619 |
| d16 | 1.59 | 19022.9 | 1.383 | 0.621 |
| d32 | 1.52 | 16273.3 | 1.640 | 0.618 |
| d64 | 1.74 | 24028.8 | 1.263 | 0.619 |

d64 was used for the configuration sweep because it tied for best QPS in this
single-run screen and had the lowest L2I MPKI among the tied winners.

Earlier d16 repeated result on `i50m_q20_t2`:

| variant | avg QPS | avg p95 ms | avg L2I MPKI | avg IPC |
|---|---:|---:|---:|---:|
| baseline | 1.343 | 19595.3 | 5.060 | 0.470 |
| d16 | 1.627 | 15981.7 | 1.659 | 0.617 |

QPS speedup for d16 was +21.1%.

## Profile Determinism

Existing L2I/LBR profiles for `i50m_q20_t2`:

| profile | samples | IND_CALL share | top target | top target share |
|---|---:|---:|---|---:|
| rep1 | 4045 | 93.10% | `ICacheBuster::RunNextMethod()` | 93.249% |
| rep2 | 2283 | 93.52% | `ICacheBuster::RunNextMethod()` | 93.602% |
| rep3 | 4003 | 92.83% | `ICacheBuster::RunNextMethod()` | 93.027% |

Weighted Jaccard over `(symbol, srcline, branch_type)`:

| pair | weighted Jaccard |
|---|---:|
| rep1 vs rep2 | 0.5105 |
| rep1 vs rep3 | 0.8631 |
| rep2 vs rep3 | 0.5169 |

The sample-set overlap is lower for the smaller rep2 profile, but the dominant
target and branch type are the same across all three profiles. The control-flow
data structure is explicit: `ICacheBuster::methods_` stores the future indirect
call targets.

## Existing Non-FeedSim Context

Earlier screening found high L2I MPKI in TailBench `specjbb`, `silo`, `shore`,
and `masstree`, but existing PGO/static-injection experiments did not produce
10% QPS gains. The best Silo variants were in the low single digits by QPS.

Earlier DCPerf official/rootless screening was low L2I MPKI for TAO, video,
WDL, and default FeedSim fixed-QPS runs. The high-MPKI FeedSim results here come
from increasing `--min_icache_iterations` and directly pinning the workload.

Fleetbench is not installed under `benchmarks/` in this workspace. The upstream
project is a Google workload microbenchmark suite
(`https://github.com/google/fleetbench`), but it would need a new Bazel
build/install path before it can be included in the same pipeline.

## Artifacts

- Main FeedSim case note:
  `FEEDSIM_PREFETCH_CASE_STUDY.md`
- d64 combined repeated results:
  `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_combined.csv`
- d64 repeated run logs:
  `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_reps23`
- d64 screen:
  `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_config_screen_d64`
- distance sweep:
  `llvm_prefetchit/results/datacenter_goal_20260708/feedsim_d_sweep_i50m_q20`
- profile directory:
  `llvm_prefetchit/results/tailbench_crossmodule_20260707/feedsim_i50m_profiles`
