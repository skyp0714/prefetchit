# Class A-3: future function targets and static-graph composition (2026-09-23–24)

A-3 denotes runtime-readable future function targets. FeedSim's existing array
lookahead belongs here. A-2 denotes static target prediction (including protobuf
schema graphs). One workload can support both; the categories do not imply
independent or additive benefits. These experiments are source prototypes, not
a general compiler transformation for arbitrary C++ loads/calls.

FleetBench's new A-3 policies did not improve baseline. Five fresh paired rounds
reproduced the static schema graph gain, but composition was worse than graph
alone. FeedSim's existing lead-four A-3 policy reproduced a **+6.13%** CPU
efficiency gain; graph alone did not improve performance, and combining it with
A-3 gave **+6.17%**, with no confirmed incremental benefit. Keep **G alone for
FleetBench and F alone for FeedSim**. No new success on arbitrary C++ call graphs
or general automatic future-pointer prediction was established.

## FleetBench outcome

Unchanged upstream Proto Arena, workset 10, seed 0, 100 iterations/run, CPU36,
2 GHz cpufreq/HWP, turbo/C6 off, fixed uncore; five randomized paired rounds.
All nine arms run once per round. CPU efficiency = baseline CPU time / arm CPU
time minus one. Intervals are unadjusted paired log-t95% (n=5, df=4).

| Independently built policy | CPU efficiency vs baseline | 95% interval | vs its exact NOP twin |
|---|---:|---:|---:|
| F: future Clear target, deduplicated, four lines | -0.4603% | [-0.5291%, -0.3914%] | +0.0602% |
| G: unchanged static schema graph (`ctorgrand8`) | +3.4523% | [+3.3999%, +3.5047%] | +4.5670% |
| F+G | +2.8083% | [+2.7305%, +2.8861%] | +4.4081% |

Adding F to the deployed G binary family loses 0.6225% (CI -0.6712 to -0.5738%).
These are speedups, not execution-time reductions. G is byte-identical to the
previous confirmed binary (SHA256 c55964d4ecec91ad06abd109829d57c0c11119b34974f913d9dd6317839e24cb).
The five-pair negative F result does not demonstrate absence of every possible
future-target opportunity in protobuf or C++.

For equal completed work, F reduces speculative L2 code misses by 3.35% while
increasing retired instructions by 0.69%. G reduces misses by 21.13%; F+G reduces
them by 22.66% but increases instructions by 1.72%. Thus the lowest miss count
does not select the fastest policy. These counts do not identify which misses
were on the critical path or distinguish late prefetch from backend overlap.

At the **same combined layout**, remove register hints, RIP-relative hints or
both. All address loads, branches, cursor work and layout remain. The combined
binary has 19,718 graph hints and eight register hints; graph GOT count is zero,
so the two addressing forms identify the two interventions for this experiment.

| Same-layout comparison | CPU efficiency | 95% interval |
|---|---:|---:|
| F hints alone vs all hints NOP | +0.1195% | [+0.0243%, +0.2147%] |
| G hints alone vs all hints NOP | +4.5404% | [+4.4815%, +4.5994%] |
| Both hints vs all hints NOP | +4.4081% | [+4.3052%, +4.5112%] |
| Add F hints with G already enabled | -0.1266% | [-0.1973%, -0.0558%] |

The interaction multiplier S_FG/(S_F*S_G) is -0.1630% across independent builds
and -0.2457% at the combined layout (the latter CI -0.3410 to -0.1503%). These
ratios describe non-additivity, not an additive attribution of processor stalls.

## What was implemented and screened

The private protobuf copy changes no messages, input mix, allocations or method
call order. The x86-64 Itanium ABI resolver reads the virtual Clear code address
from live generated protobuf objects. Short arrays are bounds-checked before
reading a future element. A separate variation hints already-known copy/merge
function pointers before reserve/allocation work. No predicted target method is invoked to obtain its address; merge uses the
existing class-data accessor. These assumptions are specific to the generated protobuf workload;
a general compiler may not speculate pointer loads across arbitrary user code
without proving object lifetime and memory dependencies.

The independently retained first screen used 50 iterations, one round:

| Policy | vs baseline | vs NOP | L2 code misses per fixed work |
|---|---:|---:|---:|
| First Clear target once + copy/merge, one line | -0.8720% | -0.0216% | -1.2176% |
| One element ahead + copy/merge, one line | -0.9485% | +0.1250% | -1.2492% |
| Four elements ahead + copy/merge, one line | -0.8669% | -0.0415% | -1.3970% |
| One ahead, deduplicated + copy/merge, four lines | -1.0669% | +0.0547% | -5.5138% |
| Clear only, one ahead, deduplicated, four lines | -0.4581% | +0.0299% | -3.5276% |

No arm met the prospective +0.5% promotion threshold against both baseline and
NOP. The least-regressing Clear-only arm was selected for the separate negative
confirmation/composition experiment; it is not described as a screening win.
Repeated protobuf elements often share a concrete type, unlike FeedSim's
shuffled function array; repeated target loads can therefore add cost without
finding a new cold target. This is a structural explanation, not a measured
critical-path decomposition.

## FeedSim outcome

Five fresh paired rounds, seven arms per round, randomized order. All 35 trials
are retained separately from the nine-arm screen. Gains and intervals use the
same paired log-t method as FleetBench. F is the existing lead-four, one-entry-line
policy, revalidated in this new build experiment; it is not a newly discovered
improvement over the earlier +5.48% result. The two campaigns' intervals overlap.

| Independently built policy | CPU efficiency vs baseline | 95% interval | vs its exact NOP twin (95% interval) |
|---|---:|---:|---:|
| F: future function pointer | **+6.1271%** | [+5.2573%, +7.0040%] | +6.1793% [+5.4480%, +6.9157%] |
| G: depth-two direct call graph | -0.4298% | [-1.2537%, +0.4009%] | -0.1742% [-1.2136%, +0.8760%] |
| F+G | **+6.1728%** | [+5.4732%, +6.8770%] | +6.1907% [+5.6957%, +6.6881%] |

Adding G to F gives **+0.0431%**, CI **[-0.8363%, +0.9303%]**. It is not a
confirmed additional gain. Adding F to G gives +6.6312%, CI [+5.4791%, +7.7958%].
The independent-build interaction multiplier is +0.4750%, CI [-0.5339%,
+1.4941%]; this also does not establish synergy. Do not add the standalone
percentages to estimate the combined result. F's +6.1271% CPU efficiency
corresponds to **5.7733% less CPU per request**, not a measured capacity increase.

| Policy | Mean CPU ms/request | L2 code MPKI | Retiring | Bad speculation | FE-bound | BE-bound | Fetch latency (subset of FE) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 171.913 | 3.596 | 36.62% | 10.04% | 39.54% | 14.16% | 29.29% |
| F | 161.989 | 3.396 | 39.76% | 10.68% | 33.20% | 16.52% | 21.90% |
| G | 172.659 | 3.607 | 36.55% | 9.87% | 40.60% | 13.48% | 29.68% |
| F+G | 161.918 | 3.400 | 39.60% | 11.02% | 32.55% | 17.16% | 22.13% |

Top-down and code-miss counters are user-mode only; CPU time includes user and
kernel execution in Leaf. Each entry is a mean of per-trial ratios; raw slot
ratios are retained without forcing their sum to 100%. F reduces estimated code
misses/request by 5.49%. The larger backend *fraction* after F is not an additive
measurement of backend overlap or a proof that backend time increased.

Confirmation achieved 39.47–39.99 QPS at requested 40 QPS, p95 430.70–500.47 ms,
utilization 80.32–87.40%, and zero recorded driver errors. Every trial passed
the >=98% rate, <=700 ms p95, >=15% utilization gates and full counter scheduling.

## FeedSim composition scope

The new G planner combines the unchanged binary's direct-call graph with
optimized LLVM IR edges from the seven insertion translation units. FeedSim's
large code model lowers source-level direct calls to register-indirect machine
calls, which the binary-only planner missed. The initial empty plan was a setup
failure, not a performance result, and was never measured. IR recovers only
statically named callees; unknown SSA callees remain unresolved. No execution
profile is used. Depth is two, one line/target, at most four hints/site.
Insertion is limited to class methods in the seven handwritten feature-extractor
translation units. Generated copy functions and the rest of the full workload
are unchanged. This limited coverage must not be called a whole-program ceiling.
F is the existing lead-four array lookup. G emits 22 RIP-relative hints at
10 sites, including three at runFlatExtractors; F emits four register hints
because of compiler loop unrolling. The combined binary has both sets and no
GOT graph hints. Baseline has no native T1 in the selected control functions;
native hints elsewhere remain untouched. Both standalone builds and matched
controls are prepared. All binaries have debug sections stripped consistently;
allocated section bytes, sizes and virtual addresses are checked against each
unstripped build before measurement.

The separate one-round screen at 40 QPS observed F +5.94%, G +0.70%, and F+G
+6.39% CPU efficiency versus baseline. These are selection observations, not
confirmed results. G exceeded the predeclared +0.5% threshold against both
baseline and its NOP twin. The fresh confirmation therefore freezes seven arms:
baseline, F, F-NOP, G, G-NOP, F+G, and F+G-NOP, five randomized paired rounds.
The two partially disabled combined-layout parents were measured in the screen
only; do not attach a five-pair interaction interval to those observations.

All runs retain the full v2 DLRM/RPC/TLS/ZSTD workload, seed 122, eight server
cores at 2 GHz, 30-second warmup and 65-second measurement. Mock services and
the load generator use separate fixed cores. Perf samples the Leaf process for
25 seconds starting eight seconds into the main run. CPU/request divides this
task-clock by 25 times the whole-run achieved QPS; it estimates steady-state
Leaf CPU efficiency, not whole-stack CPU, per-request traced CPU, or capacity.

## Boundary of generalization

This campaign tests whether a future callee can be read early from an existing
data structure. FeedSim supplies an immutable dispatch table and known cursor;
protobuf supplies live elements and virtual method metadata. Neither prototype
predicts a pointer value that has not yet been computed. The latter would need
an explicitly evaluated predictor and a cost/accuracy model.

Automating A-3 requires a compiler to identify the indirect-target load chain,
prove bounds and object lifetime, and establish that intervening calls cannot
invalidate the speculative loads. The FeedSim source rule and x86-64 protobuf
member-pointer resolver do not establish those properties for arbitrary C++.
Likewise, protobuf G relies on schema structure, and FeedSim G is restricted to
seven manually chosen translation units. Cross-workload success must be measured
before describing either choice of injection scope as generally effective.

## Validation and reproduction

Raw root: `llvm_prefetchit/results/class_a3_20260923/`. `PROTOCOL.md` records the
prospective policy-selection and measurement rules. `analyze.py` regenerates
paired estimates from each trial, without pooling screening into confirmation.

Build drivers:
- `llvm_prefetchit/scripts/static/build_proto_future_targets.py`
- `llvm_prefetchit/scripts/static/build_feedsim_factorial.py`

The protobuf dependency is overridden with a private copy; the benchmark source
and original dependency source are not patched. ASan/UBSan fixture checks cover
short arrays, heterogeneous virtual targets and multiple inheritance. NOP tests
check custom executable sections, exact scope, selective RIP/register removal,
and byte-identical all-NOP results regardless of removal order.

An initial four-line NOP build stopped because a REX+SIB+disp32 hint is nine bytes.
The helper now supports a nine-byte NOP and has a regression test. The failed
control was regenerated and verified before any timing; no such invalid control
was measured. The four focused tests pass, including direct-IR versus unknown-call
discrimination. All 56 FleetBench and 44 FeedSim timing counter files are numeric
and fully scheduled. The two FleetBench platform/HWP contexts and 80 FeedSim
per-core contexts restored exactly. No measured trial was excluded. A final
disassembly audit confirms zero native T1 hints in the protobuf baseline;
FeedSim's native T1 exclusion is checked within the control function list.
FeedSim processes exited and ports 11222/11223 were released.

Published evidence: [protocol](../llvm_prefetchit/migration/evidence/class_a3_20260923/PROTOCOL.md) and
[compact summaries](../llvm_prefetchit/migration/evidence/class_a3_20260923/).
Git contains factorial/negative results and source provenance. Raw timing/counter
trials and the full reproduction archive remain local; see the
[publication inventory](../llvm_prefetchit/migration/evidence/README.md).
