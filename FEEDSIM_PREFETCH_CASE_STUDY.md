# FeedSim I-cache Prefetch Case Study

This note records the FeedSim experiment that produced a clear speedup from
prefetching control-flow targets. It is intended as paper-writing/reference
material, not as a polished artifact.

## Summary

- Workload: DCPerf FeedSim `LeafNodeRank`.
- Stressor: FeedSim's generated `ICacheBuster` indirect-call stream.
- Bottleneck selected by: L2I miss sampling with LBR branch traces.
- Optimization used: static control-flow-data-structure prefetch.
- Prefetch site: immediately before `ICacheBuster::RunNextMethod()` dispatches
  the next function pointer.
- Prefetch target: future entry of the shuffled function-pointer vector.
- Best measured result so far: average achieved QPS improved from `1.343` to
  `1.627` across 3 paired runs, or `+21.1%`.
- L2I MPKI improved from `5.060` to `1.659`, or `-67.2%`.

This is not an LLVM PGO-pass result. It validates the separate hypothesis that
some high-L2I-MPKI datacenter workloads expose an explicit data structure
containing future control-flow targets, and that prefetching through that data
structure can reduce instruction-side misses.

## Workload Configuration

The runs used FeedSim directly rather than full benchpress orchestration. The
leaf process was pinned together with all descendants by the measurement wrapper
over core range `0-10`. FeedSim itself was started with `--noaffinity` so that
the external pinner controlled placement.

Leaf:

```bash
MALLOC_CONF=narenas:20,dirty_decay_ms:5000 \
LeafNodeRank \
  --port=$PORT \
  --monitor_port=$((PORT - 1000)) \
  --graph_scale=21 \
  --graph_subset=2000000 \
  --threads=2 \
  --cpu_threads=2 \
  --timekeeper_threads=1 \
  --io_threads=1 \
  --srv_threads=2 \
  --srv_io_threads=2 \
  --num_objects=2000 \
  --graph_max_iters=1 \
  --noaffinity \
  --min_icache_iterations=50000000
```

Driver:

```bash
scripts/search_qps.sh \
  -s 95p \
  -t 20 \
  -m 0 \
  -q 20 \
  -o ../RESULT.txt \
  -- build/workloads/ranking/DriverNodeRank \
     --server 0.0.0.0:$PORT \
     --monitor_port $((PORT - 2000)) \
     --threads=4 \
     --connections=4
```

The run waits 20 seconds after starting the leaf before launching the driver.
The fixed requested QPS is 20. The achieved QPS is much lower in this high
I-cache setting, which makes it easy to see both throughput and latency changes.

## Initial L2I Screening

Screening result:

| config | elapsed_s | L2I MPKI | IPC | note |
|---|---:|---:|---:|---|
| `--min_icache_iterations=1600000` | 52.290 | 0.329 | 1.520 | default-ish icache setting |
| `--min_icache_iterations=50000000` | 52.500 | 3.789 | 0.496 | high-L2I candidate |

Source file:

```text
llvm_prefetchit/results/tailbench_crossmodule_20260707/feedsim_icache_screen/summary_feedsim_icache.md
```

## Profile Collection

Three L2I profiles were collected with LBR enabled:

```bash
perf record \
  -e cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp \
  -b \
  -c 100000 \
  ...
```

Profile directory:

```text
llvm_prefetchit/results/tailbench_crossmodule_20260707/feedsim_i50m_profiles
```

Sample counts:

| profile | samples |
|---|---:|
| rep1 | 4045 |
| rep2 | 2283 |
| rep3 | 4003 |

Branch type distribution was dominated by indirect calls:

| profile | IND_CALL | RET | other |
|---|---:|---:|---:|
| rep1 | 93.10% | ~6.7% | <1% |
| rep2 | 93.52% | ~6.1% | <1% |
| rep3 | 92.83% | ~6.7% | <1% |

The top target in every profile was `ICacheBuster::RunNextMethod()`:

| profile | top target count | total samples | share |
|---|---:|---:|---:|
| rep1 | 3771 | 4045 | 93.249% |
| rep2 | 2136 | 2283 | 93.602% |
| rep3 | 3722 | 4003 | 93.027% |

Weighted Jaccard overlap over `(symbol, srcline, branch_type)`:

| pair | weighted Jaccard |
|---|---:|
| rep1 vs rep2 | 0.5105 |
| rep1 vs rep3 | 0.8631 |
| rep2 vs rep3 | 0.5169 |

The pairwise overlap is lower for rep2 because it collected fewer samples, but
all three profiles agree on the dominant miss target and branch type. For this
case, the target is deterministic enough to justify a targeted transformation.

## Code Structure

Relevant source:

```text
benchmarks/dcperf/benchmarks/feedsim/src/workloads/search/gen_icache_buster.py
benchmarks/dcperf/benchmarks/feedsim/src/build/workloads/search/ICacheBuster.cc
```

`ICacheBuster` builds a vector of generated function pointers:

```cpp
std::vector<void (*)()> methods_;
size_t current_index_;
size_t num_subset_methods_;
```

The constructor fills `methods_` with generated `ICBMethod_N` functions and then
shuffles the vector. The hot dispatch path calls:

```cpp
methods_[current_index_]();
current_index_ = (current_index_ + 1) % num_subset_methods_;
```

This means the future indirect-call target is already stored in a stable data
structure. A software prefetch can look ahead in `methods_` without changing the
dispatch order.

## Static Prefetch Patch

The evaluated patch used a lookahead distance of 16 entries:

```cpp
void ICacheBuster::RunNextMethod() {
  constexpr size_t kPrefetchDistance = 16;
  const size_t prefetch_index =
      (current_index_ + kPrefetchDistance) % num_subset_methods_;
  __builtin_prefetch(reinterpret_cast<const void*>(methods_[prefetch_index]), 0, 3);
  methods_[current_index_]();
  current_index_ = (current_index_ + 1) % num_subset_methods_;
}
```

The generator was patched so regenerated sources preserve this transformation:

```text
benchmarks/dcperf/benchmarks/feedsim/src/workloads/search/gen_icache_buster.py
```

The generated build-tree source was also patched for the already-generated
build:

```text
benchmarks/dcperf/benchmarks/feedsim/src/build/workloads/search/ICacheBuster.cc
```

Build command:

```bash
ninja -C benchmarks/dcperf/benchmarks/feedsim/src/build workloads/ranking/LeafNodeRank
```

Saved binaries:

```text
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.base_nopf
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d16
```

## Paired Evaluation Result

Evaluation directory:

```text
llvm_prefetchit/results/tailbench_crossmodule_20260707/feedsim_prefetch_d16_repeats
```

Per-run result:

| rep | variant | achieved_qps | p95_ms | avg_ms | L2I MPKI | IPC |
|---:|---|---:|---:|---:|---:|---:|
| 1 | base | 1.260 | 20469.2 | 14371.1 | 5.122 | 0.470 |
| 1 | pref_d16 | 1.700 | 16495.4 | 10422.4 | 1.666 | 0.619 |
| 2 | base | 1.330 | 21786.5 | 12446.1 | 5.037 | 0.470 |
| 2 | pref_d16 | 1.630 | 16673.0 | 11163.2 | 1.647 | 0.614 |
| 3 | base | 1.440 | 16530.3 | 12098.0 | 5.021 | 0.470 |
| 3 | pref_d16 | 1.550 | 14776.6 | 9792.9 | 1.665 | 0.617 |

Aggregate:

| metric | baseline | prefetch d16 | change |
|---|---:|---:|---:|
| achieved QPS | 1.343 | 1.627 | +21.1% |
| p95 latency ms | 19595.3 | 15981.7 | -18.4% |
| avg latency ms | 12971.7 | 10459.5 | -19.4% |
| L2I MPKI | 5.060 | 1.659 | -67.2% |
| IPC | 0.470 | 0.617 | +31.3% |

## 2026-07-08 Follow-up: Config Sweep With d64

After the initial d16 case, a CMake cache variable was added so that
`ICACHE_BUSTER_PREFETCH_DISTANCE` can be rebuilt without hand-editing generated
source:

```cmake
set(ICACHEBUSTER_PREFETCH_DISTANCE 16 CACHE STRING
    "Lookahead distance for ICacheBuster code-target prefetch")
target_compile_definitions(icachebuster PRIVATE
                           ICACHE_BUSTER_PREFETCH_DISTANCE=${ICACHEBUSTER_PREFETCH_DISTANCE})
```

Built binaries:

```text
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d4
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d8
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d16
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d32
llvm_prefetchit/work/tailbench_crossmodule_20260707/feedsim_bins/LeafNodeRank.prefetch_d64
```

The d64 binary was verified with `objdump`; it contains `prefetcht0 (%rax)` in
`ICacheBuster::RunNextMethod()`, while the baseline binary has only the indirect
call.

Confirmed 3-repetition d64 results:

| config | base QPS | d64 QPS | QPS speedup | base L2I MPKI | d64 L2I MPKI |
|---|---:|---:|---:|---:|---:|
| `i20m_q20_t2` | 2.180 | 2.563 | +17.6% | 2.970 | 0.807 |
| `i50m_q20_t2` | 1.270 | 1.667 | +31.2% | 5.052 | 1.282 |
| `i100m_q20_t2` | 0.890 | 1.147 | +28.8% | 6.668 | 1.651 |
| `i50m_q40_t2` | 1.307 | 1.603 | +22.7% | 5.007 | 1.258 |
| `i100m_q20_t4` | 2.643 | 3.113 | +17.8% | 7.052 | 1.718 |

Detailed results and run logs:

```text
DATACENTER_PREFETCH_SEARCH_20260708.md
llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_combined.csv
llvm_prefetchit/results/datacenter_goal_20260708/feedsim_confirm_d64_reps23
llvm_prefetchit/results/datacenter_goal_20260708/feedsim_config_screen_d64
llvm_prefetchit/results/datacenter_goal_20260708/feedsim_d_sweep_i50m_q20
```

## Interpretation

This workload exposes a control-flow data structure directly: a shuffled vector
of function pointers. The profile says most sampled L2I misses occur while
executing the indirect-call stream. Looking ahead in the vector prefetches the
future code target early enough to reduce L2I misses and improve throughput.

The current case supports the "data-structure-aware static prefetch" path more
strongly than the generic PGO-injection path. The PGO branch target is stable,
but the actual source-level injection site is clearer when using the semantic
structure of `ICacheBuster`.

## Caveats

- Some short runs reported an empty PSR sample in the pinner monitor even though
  the command used a fixed core range. The migration counts remained low enough
  for the paired comparison, but longer runs should keep the pinner monitor
  alive and report per-thread core assignment explicitly.
- The workload uses a synthetic I-cache stressor inside FeedSim. It is still a
  DCPerf workload component, but it should be presented as an I-cache-stressed
  FeedSim configuration rather than as a default FeedSim production-like
  configuration.
- This result should be reported separately from LLVM-pass PGO results unless
  the pass is extended to express this exact data-structure lookahead pattern.
