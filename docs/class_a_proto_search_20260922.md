# FleetBench proto: expanded prefetch search (2026-09-22)

Later follow-up: [latency/coverage experiments](class_a_proto_lead_20260922.md)
confirmed **3.44–3.48%** CPU speedup. The smaller results below remain the record
of the preceding search.

Follow-up to [the initial five-policy experiment](class_a_proto_20260922.md).
The workload remains upstream `BM_PROTO_Arena`, fixed work, CPU 36 alone at
2 GHz with deep C-states off. No workload, message, allocator, compiler
optimization-level, or layout-PGO changes. All changed platform controls are
restored after each campaign. The original baseline binary is reused.

## Best confirmed result: static schema-directed prefetch

The best of 30 screened policies uses protobuf's static message-field type graph.
At a parent's `Clear`, `MergeImpl`, `ByteSizeLong`, or `_InternalSerialize` entry,
it prefetches the entry of the same operation on up to four distinct child message
types. Both optional and repeated message fields are included. It emits 5,484
PC-relative T1 instructions across 3,300 sites through the existing LLVM cold-plan
mode. No execution profile determines sites or targets. Concrete field types
provide targets that the generic protobuf runtime's indirect calls can hide from
an ordinary direct-call graph.

| Independent campaign | Repetitions | Base / prefetch CPU ms/op | Speedup vs base | vs NOP | L2 code MPKI |
|---|---:|---:|---:|---:|---:|
| Seed 0 confirmation | 5 | 139.335 / 138.600 | **1.005301x** | **1.011358x** | 16.593 → 15.651 |
| Seed 1 holdout | 5 | 139.426 / 138.653 | **1.005578x** | **1.011329x** | 16.590 → 15.650 |

Each run uses 100 benchmark iterations. All ten paired rounds beat baseline and
NOP. Baseline/prefetch paired ratios span 1.004807–1.005301 for seed 0 and
1.003581–1.005578 for seed 1. The gain is about **0.53–0.56%**, not the 1.13%
prefetch/NOP difference: insertion/layout cost consumes the rest. Instructions
increase about 0.52%, and absolute speculative L2 code misses per fixed work fall
about 5.2%. Both seeds retain the same upstream operation mix; this is not
cross-application generalization.

A separate 30-iteration diagnosis confirms cache effects beyond the MPKI
denominator. Retired L2 misses fall 12,341,647 → 9,821,821 (**−20.4%**), compared
with 13,132,007 in the NOP twin (**−25.2%** vs twin). ICACHE_DATA.STALLS falls
**6.6% vs base / 8.9% vs twin**. Retired L2 MPKI is 1.527 → 1.209, FE-bound
56.41% → 55.29%, fetch latency 43.87% → 42.75%, and BE-bound 11.01% → 11.37%.
These profiling counts are separate runs, not statistical confidence intervals.

`proto_schema_prefetch_plan.py` currently targets the FleetBench namespace and
these four protoc C++ methods. The demonstrated result is a static type-informed
policy for this workload, not a generic solution for arbitrary C++ programs.

## General callee policy: smaller confirmed improvement

`dom1lead128` is a profile-free compiler policy: one T1 to a known direct callee's
entry, moving backward through dominating basic blocks toward 128 IR instructions
of lead. Callees have at least eight IR instructions. Selection uses the workload
namespace (`fleetbench5proto`), not a list of sampled hot functions. The explicit
in-image-link setting permits direct references to weak/COMDAT definitions that
the previous callee policy skipped. Prefetching can execute on paths that do not
ultimately call the target; this costs work but does not change program results.

| Independent campaign | Repetitions | Speedup vs base | vs same-layout NOP | L2 code MPKI |
|---|---:|---:|---:|---:|
| Seed 0 confirmation | 5 | 1.001076x | 1.006219x | 16.597 → 15.464 |
| Seed 1 holdout | 5 | 1.000928x | 1.005805x | 16.593 → 15.443 |

These are ratios of median benchmark CPU times, each with 100 benchmark
iterations per invocation. Every one of the ten paired rounds is faster than
its baseline; the seed-0 paired ratios span 1.000906–1.001444 and seed-1 ratios
1.000213–1.001896. The gain is small (about 0.1%), not a large application speedup.
The single-round screening campaigns are excluded from these estimates.
No tuning used the seed-1 timing results before this candidate was selected.

Seed 0 instructions increase 0.53%, while absolute speculative L2 code misses
per fixed work fall 6.34%. A separate 30-iteration profile measures retired L2
misses 12,405,929 → 10,413,806 (−16.1%; retired MPKI 1.535 → 1.282), and
ICACHE_DATA.STALLS 1,430,818,466 → 1,373,503,946 (−4.0%). Top-down FE-bound changes
56.08% → 55.69%, while BE-bound changes 10.98% → 11.37%. Counts come from separate
profiling runs, not confidence intervals. Much of the cache benefit is offset by
prefetch/insertion cost and other bottlenecks.
The retired counter uses event `0xc6`, umask `0x03`, frontend MSR value `0x13`,
matching [Intel's Granite Rapids event definition](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

## Search design

- Sequential distance 128/256/512/1024/2048 B; original and half density; T1/T0.
  These variants share a single compiled layout and an all-injected-prefetch NOP
  twin. Binary retuning touches only verified prefetch displacements, hint bits,
  or equal-length NOPs. Upstream data prefetches remain intact.
- Entry prefetch of four/eight lines of the function's own code; early one-line
  callee prefetch within a block; callee prefetch across dominators at leads
  32/128. The within-block methods did not improve baseline in screening.
- Existing indirect targets prefetched after their SSA definition, before loop
  setup or other work. This mode adds no pointer loads and skips loop-varying
  targets. Its observed screening improvement was also present in the NOP twin,
  so it was not promoted as a prefetch win.
- Canonical 7/8-byte in-function NOPs replaced by same-length prefetches, targeting
  following code or a following direct callee. The control is byte-identical to
  baseline. Differences were too small to promote from single-round screening.
- Further cost/coverage candidates: callee size thresholds, cross-TU direct
  callees, and protobuf schema-derived parent/child method targets. The schema
  graph is static input-type information and uses no miss profile.

The final single-round screen found smaller preliminary improvements from callee
size thresholds (32/64 IR instructions), cross-TU calls, and repeated-fields-only
schema plans. They were not independently confirmed. The matched within-block
callee policy, with the same minimum size and in-image references, was 0.9957x
vs base and 1.0004x vs its twin, versus 1.0021x / 1.0075x for the dominator policy
in that screen. Moving earlier across blocks therefore deserves further study;
these screening numbers alone are not final effect estimates.

The retired-miss trace helped select *which mechanism to investigate*, but the
confirmed policy does not consume it. Approximately 81% of executable samples
fall within the first 64 bytes of a function. Of those entry-region samples,
6,641 have a matching recent direct CALL transition and 2,359 an indirect CALL;
the rest include indirect tail jumps and other branches. The first 64 bytes are
a function-relative region, not necessarily a single aligned cache line. This
supports targeting earlier caller sites rather than assuming long sequential
streams dominate this benchmark.

## Reproduction

Raw campaign directory: `llvm_prefetchit/results/class_a_proto_search_20260922/`.
Tracked small evidence: `llvm_prefetchit/migration/evidence/fleetbench_proto_search_20260922/`.
The [confirmed summary](../llvm_prefetchit/migration/evidence/fleetbench_proto_search_20260922/confirmed_summary.csv)
contains all four confirmation/holdout campaigns; the adjacent screening summary
keeps exploratory results separate.
There are 111 timing runs: 51 exploratory runs and 60 independent confirmation/
holdout runs across the two promoted policies. Profiles are additional runs.

To reproduce the best schema policy from the repository root (create `R/plans`
first, and build `R/bin/base` with the same helper's `base` arm):

```bash
R=NEW_RESULTS
protoc -Ibenchmarks/fleetbench --descriptor_set_out="$R/plans/messages.pb" \
  benchmarks/fleetbench/fleetbench/proto/Message*.proto
python3 llvm_prefetchit/tools/proto_schema_prefetch_plan.py \
  "$R/plans/messages.pb" "$R/bin/base" "$R/plans/schema_all.json"
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py \
  --out "$R" --plan "$R/plans/schema_all.json" cold_static
sudo python3 llvm_prefetchit/scripts/static/measure_class_a.py \
  --out "$R/confirm" --iterations 100 --reps 5 --seed 0 \
  base="$R/bin/base" schema_all="$R/bin/cold_static" \
  schema_all_nop="$R/bin/cold_static_nop"
```

The planner uses the installed `protoc` and Python `google.protobuf` descriptor
reader. The `cold_static` arm here is simply the helper's existing cold-plan
injection configuration; supplying the schema plan gives the tested policy.

Use the helper's `--config` argument to pass a JSON dictionary of environment
settings. The smaller, general callee policy's dictionary is:

```json
{
  "PREFETCHIT_CALLEE_BURST_LINES": "1",
  "PREFETCHIT_CALLEE_BURST_LEAD": "128",
  "PREFETCHIT_CALLEE_BURST_MIN_CALLEE_INSNS": "8",
  "PREFETCHIT_CALLEE_DOMINATOR": "1",
  "PREFETCHIT_COLD_DIRECT_IN_PIC": "1",
  "PREFETCHIT_SEQ_FUNCTIONS": "fleetbench5proto"
}
```

```bash
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py \
  --out NEW_RESULTS --config CONFIG.json dom1lead128
sudo python3 llvm_prefetchit/scripts/static/measure_class_a.py \
  --out NEW_RESULTS/confirm --iterations 100 --reps 5 --seed 0 \
  base=BASE_BINARY dom1lead128=NEW_RESULTS/bin/dom1lead128 \
  dom1lead128_nop=NEW_RESULTS/bin/dom1lead128_nop
```

Repeat with a fresh output directory and `--seed 1` for holdout. The build helper
puts the plugin SHA in Bazel's action environment, since the compiler flag alone
does not make Bazel track the plugin file's contents. No measurements overlap
builds. Screening uses 50 iterations and one round to select candidates only;
confirmation uses the upstream explicit count of 100 and five rounds.

The NOP helper additionally handles an objdump prefix such as `data16 prefetcht1`.
This was required by the eight-byte padding experiment and verified before its
timing runs. Regression tests cover prefixed instructions, executable sections,
binary retuning, exact padding-twin equivalence, dominance placement, and the
absence of newly speculated loads in the indirect-target mode.
An independent rebuild reproduced the confirmed `dom1lead128` binary byte for
byte (SHA-256 `e48766891d02c47fba62622b7e4771070172eb8c4bb20aa2453dab571294db42`).
Rebuilding the winning `schema_all` policy with the final pass source also
reproduced its measured binary byte for byte (SHA-256
`f81cb7bcdd39e73a3fea9e7464096809422dc88bd06f2217af01f290d364d912`).
All 18 Python tests pass. Cross-TU call prefetching preserves the original strong
call reference: an initial `.weak` directive prevented static archive extraction
and failed linking; the failed build is retained and was never measured.
