# FleetBench proto: latency and coverage follow-up

The target for this follow-up is at least 1.03x baseline throughput on the
unchanged upstream Arena operation mix. A prefetch/NOP improvement alone does
not satisfy that target. The earlier confirmed 0.53–0.56% result is recorded in
[the preceding search](class_a_proto_search_20260922.md).

## Confirmed result: 3.44–3.48% CPU speedup

The selected `ctorgrand8` policy meets the 1.03x target in both independent
campaigns. Speedups below are ratios of medians, not screening maxima.

| Campaign | Reps × iterations | Baseline / PF CPU ms per iteration | CPU speedup | Wall speedup | PF vs NOP |
|---|---:|---:|---:|---:|---:|
| Seed 0 confirmation | 5 × 100 | 139.301 / 134.611 | **1.034844x** | **1.035163x** | 1.044008x |
| Seed 1 holdout | 5 × 100 | 139.115 / 134.482 | **1.034446x** | **1.034390x** | 1.044625x |

Every one of the ten paired rounds exceeds 1.03x for both CPU and wall time.
CPU paired ratios span 1.033678–1.036781 for seed 0 and 1.031968–1.036015 for
seed 1. Instructions rise 1.02–1.03%; absolute speculative L2 code misses per
fixed work fall 21.25–21.27%. L2 code MPKI is 16.593 → 12.935 (seed 0) and
16.572 → 12.914 (seed 1). The [confirmed summary](../llvm_prefetchit/migration/evidence/fleetbench_proto_lead_20260922/confirmed_summary.csv)
contains the exact values and paired ranges.

The policy predicts exactly second-level descendants rather than redundantly
issuing both parent and grandparent hints for the same type. It covers up to
eight entry lines, omits offsets beyond the baseline target function size, and
includes child default constructors in MergeImpl and typed Add helpers. It
uses a static descriptor/type graph and binary symbols/sizes, with no runtime
profile as planner input. The search itself is measurement-guided.

The result applies to this upstream workload and operation mix. Changing seeds
does not establish generalization to another workload. ITLB/BTB behavior is not
fixed by this policy.

Separate final 30-iteration profiles show that the improvement reaches exposed
frontend stalls, not just the miss counter:

| Event | Baseline | Selected PF | Change vs baseline |
|---|---:|---:|---:|
| Retired L2 code miss | 12,406,465 | 7,032,095 | **−43.3%** |
| I-cache stalled cycles | 1,434,258,257 | 1,060,285,610 | **−26.1%** |
| FE starvation ≥64 cycles, uninterrupted by BE stall | 10,179,406 | 6,292,731 | **−38.2%** |
| FE starvation ≥128 cycles, uninterrupted by BE stall | 3,798,913 | 2,066,750 | **−45.6%** |
| Zero-uop cycles, backend ready | 3,678,074,698 | 3,276,926,231 | **−10.9%** |
| Execution stalls with outstanding L1D miss | 690,285,836 | 750,340,531 | +8.7% |
| Execution stalls with outstanding L2 data miss | 470,820,566 | 518,737,715 | +10.2% |

The NOP twin has 14,197,432 retired L2 miss events and 1,500,289,154 I-cache
stalled cycles; PF reduces them by 50.5% and 29.3%, respectively. Top-down
FE-bound is 56.1% → 54.1%, fetch latency 43.9% → 40.0%, and BE-bound
11.4% → 11.8%. Data-related stalls still increase, so the result does not mean
prefetch has no backend cost. The measured end-to-end gain survives that cost.
Counters include process startup and are separate diagnostic runs, not
confidence intervals or an additive decomposition of benchmark cycles.
See the [profile summary](../llvm_prefetchit/migration/evidence/fleetbench_proto_lead_20260922/final_profile_summary.csv)
for all events and NOP comparisons.

## Why fewer misses did not mean a proportional speedup

The earlier separate profiles showed 20.4% fewer retired L2 code misses, but
only 6.6% fewer `ICACHE_DATA.STALLS`. Those stalls were about 17.2% of baseline
cycles, so their reduction corresponds to about 1.1% of baseline cycles before
considering overlap, insertion costs, or changes in other stalls. This is a
scale comparison, not an additive decomposition or a speedup upper bound.

Fresh 30-iteration profiles of the unchanged baseline and previous winner
give the following counts. Each event family is a separate invocation.

| Event | Baseline | Previous winner | Change |
|---|---:|---:|---:|
| Retired L2 code miss | 12,379,776 | 10,073,940 | −18.6% |
| I-cache stalled cycles | 1,436,542,572 | 1,359,657,036 | −5.4% |
| FE starvation ≥16 cycles | 20,234,921 | 21,653,863 | +7.0% |
| FE starvation ≥32 cycles | 12,337,953 | 12,242,947 | −0.8% |
| FE starvation ≥64 cycles | 10,187,237 | 8,996,573 | −11.7% |
| FE starvation ≥128 cycles | 3,809,520 | 2,727,834 | −28.4% |
| Zero-uop cycles, backend ready | 3,684,573,161 | 3,589,703,641 | −2.6% |
| Execution stalls with outstanding L1D miss | 708,278,958 | 746,742,590 | +5.4% |
| Execution stalls with outstanding L2 data miss | 482,279,336 | 517,402,782 | +7.3% |

Intel defines `FRONTEND_RETIRED.LATENCY_GE_N` as retired instructions following
no-uop intervals not interrupted by a backend stall. Event definitions are from
[Intel's Granite Rapids PMU database](https://github.com/intel/perfmon/blob/main/GNR/events/graniterapids_core.json).
Different latency thresholds share frontend MSR 0x3f7, so the harness measures
them in separate runs. `LATE_SWPF` is deliberately not used: Intel defines it for
PREFETCHIT0/1, while these experiments use data `PREFETCHT1` targeting code.

These results show that useful, exposed long frontend stalls did decrease.
They do not support attributing the small gain entirely to backend overlap.
Shorter frontend starvation and data-related stall counts increased, consistent
with additional execution/cache costs, but these counters overlap and do not
establish a causal decomposition. Instruction-count MPKI is supplemented with
absolute misses and stalls per fixed work. No claim is made that ITLB/BTB misses
are solved, or that an IR lead parameter measures actual runtime lead cycles.
The latency thresholds are cumulative counts, not cycle-weighted costs: a
reshaping or fragmentation of longer pauses can also change shorter-threshold
counts. Their increase alone does not prove newly added stall time.

## Experiment design

All timing comparisons retain CPU 36 at 2 GHz, uncore fixed, turbo/deep C-states
off, workset 10 and the original upstream operation mix. Each context restores
the original sysfs and HWP settings. Builds and timing runs do not overlap.
Exploratory runs use 50 iterations; promoted candidates require new 100-iteration
campaigns against baseline and the same-layout NOP twin, including seed 1.

The first screen separates explicit padding, sparse child selection, ancestor
depth, one/two lines per target, method restriction, and cache hints. Its best
single-round candidate (`deep8lines2`: two descendant levels, eight distinct
types, two lines, no explicit padding) was 1.02024x baseline and 1.03268x NOP.
This is exploratory, not the final reported performance gain.

Baseline retired-miss samples also reveal a coverage hole: 2,794 of 12,139
samples (23.0%) are in FleetBench message constructors, including 2,601 in
default constructors. The previous planner covered four message methods only.
The trace identifies a mechanism to investigate; it is not a selection input
for the static schema plans. Constructor variants predict child default
constructors from MergeImpl operations and typed repeated-field Add helpers.

Further variants compare four lines, three descendant levels, constructor
coverage, and lifting a callee's static schema targets into its caller. The
caller mode uses the same target plan with lead 0/128, making placement an
explicit experimental variable. Optional size caps omit offsets beyond a
target's baseline function size; the size estimate is static, not a profile.

The second screen found 1.02700x for the size-capped four-line policy, versus
1.01257x for unconditionally issuing four lines. The equal-count caller modes
were 1.01907x at lead 0 and 1.01869x at lead 128; simply adding IR lead did not
help in that comparison. The third screen reached 1.03057x for `ctorgrand4`,
which predicts exactly second-level descendants, caps offsets to function size,
and adds constructor targets. These remain single-round exploration results.

Initial constructor plans also requested copy-constructor C1 entry sites. Those
names are LLVM aliases rather than function bodies, so none of those requests
were emitted. Their target counts exactly account for the difference between
requested and emitted instructions. The planner now omits those ineffective
sites; constructor targets themselves remain valid, defined code symbols. The
final policy is described by its actual MergeImpl/Add behavior, not by the
discarded alias-site requests.

The fourth screen selected `ctorgrand8` (1.03352x baseline CPU time). Its final
plan has 2,764 sites, 19,718 emitted T1s, and 6,511 distinct defined target
symbols. The plan regenerates exactly from the final planner and baseline;
all target symbols are present in the final executable. Removing the ineffective
alias sites also reproduced the earlier `ctorgrand4` binary byte for byte.
The complete search contains 22 additional policies and 53 exploratory runs;
those runs are excluded from confirmation estimates.

## Reproduction

Use a fresh output directory, the unchanged baseline build, and the descriptor
generation command from the [previous report](class_a_proto_search_20260922.md).
Generate the selected static plan with:

```bash
python3 llvm_prefetchit/tools/proto_schema_prefetch_plan.py \
  "$R/plans/messages.pb" "$R/bin/base" "$R/plans/selected.json" \
  --compact --depth 2 --min-depth 2 --max-children 8 \
  --lines 8 --cap-lines-to-size --constructors
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py \
  --out "$R" --plan "$R/plans/selected.json" cold_static
sudo python3 llvm_prefetchit/scripts/static/measure_class_a.py \
  --out "$R/confirm_seed0" --iterations 100 --reps 5 --seed 0 \
  base="$R/bin/base" prefetch="$R/bin/cold_static" \
  prefetch_nop="$R/bin/cold_static_nop"
```

Repeat timing with `--seed 1` and a fresh output directory. For separate stall
diagnosis, use `--profile BINARY --iterations 30 --latency-profile` for each arm.
The selected executable SHA-256 is
`c55964d4ecec91ad06abd109829d57c0c11119b34974f913d9dd6317839e24cb`.
Compiler/tool source fingerprints, build commands, binary hashes and counters
are retained in the review archive; platform snapshots remain in the ignored raw
result directory. All 22 regression tests
pass (the test environment needs `google.protobuf` as well as pytest).
All 11 measurement contexts restored their original sysfs and HWP values;
every recorded counter ran at 100%, and measured binary hashes match the
saved artifacts. The final host governor is the original `powersave` and
`perf_event_paranoid` remains 4.

Raw data: `llvm_prefetchit/results/class_a_proto_lead_20260922/`.
Small archived evidence: `llvm_prefetchit/migration/evidence/fleetbench_proto_lead_20260922/`.
