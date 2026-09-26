# A-3 dispatch expansion protocol, 2026-09-24

A-3 labels a method (runtime future target / conditional prediction), independently
of the alone versus interleaved miss regime. Preserve the original regime in every
row. Prior candidates: DSB Thrift Media/social RPC, Scylla/Seastar, VPP/CSIT,
Envoy; extend to previously qualified dispatch-heavy Django/MySQL where feasible.
Previously confirmed FeedSim and negative protobuf are references, not new wins.

Prefer normal validated operating points with utilization >=15% and user L2 code
MPKI >=1; prioritize larger MPKI. Do not inflate working sets, disable real request
work, manufacture co-runners, or substitute a synthetic callback microbenchmark
for an application. Scylla's high MPKI was interleaved, not alone. Low-MPKI Envoy
and alone Scylla cannot be called qualified A-capacity workloads.

Stage 1: actual future target, no learned predictor. Compare baseline, late hint,
early hint and exact NOP twins. Keep task semantics and address-computation cost.
Stage 2: only after evidence of short lead or insufficient reachable depth, test an
explicit aggressive prediction mode. Record the gate evidence, prediction source,
accuracy/coverage, and extra pointer/branch/instruction cost. Never execute a future
handler or dereference an unproven future object to make a prediction. Kernel code
and system mitigations remain unchanged. Source prototypes are not a general pass.

Separate diagnostics from timing; instrumented lead/accuracy runs are not speedup
results. Fixed cores at2GHz/HWP20, fixed uncore, turbo/C6 off, all state restored.
One workload at a time; no builds or heavy analysis during timing. Use normal stack
logging and fresh application state where required. Retain all trials and exclusions.
Screens select policies, never supply confirmed claims. Confirm any candidate >0.5%
against both original and matched NOP on fresh randomized five-pair trials. Retain
negative comparisons and unadjusted paired log-t95% intervals; no winner pooling.
Keep compact raw evidence and scripts in Git, not binaries/dependencies/full traces.

Before Scylla diagnostics: permit the queued-task depth gate when next-queued
coverage is <80% over >1,000 observed dispatches, with zero owner-slot collisions,
and requalified user L2 code MPKI >=1. A hybrid predictor may then act only when
no live next task is queued. Learn observed task-callee transitions, require two
matching transitions, and report emitted prediction accuracy/coverage separately.

Diagnostic harness correction (before performance screening): MySQL uses random
arrivals; a valid 400TPS run can have a 454TPS single second. The initial per-second
350..450 assertion was incorrect and fired after the successful Scylla diagnostic.
Keep that failed harness log. Validate the co-tenant's matched ~25second mean
within5%, all intervals progressing and zero ignored errors, not every random1s
sample. Record matched MySQL report boundaries in subsequent trials. The original
queue/miss diagnostic is usable (zero application errors); it is never a speedup.

Exploratory cost extension, motivated after online prediction's high accuracy but
initial negative timing: test freezing the successor table after1,000,000dispatches
per reactor. Warmup must complete training before timed-window entry; verify in a
separate diagnostic. The frozen policy keeps exact queue lookahead and conditional
prediction but stops hot-path transition updates. This is online-trained/frozen
prediction, not pure static compiler analysis. Keep new screen separate; use fresh
baseline and NOP controls and the same promotion threshold.

Fairness check before final selection: write-heavy Scylla's growing private LSM
state changes instructions/operation across sequential screens. Do not pool their
baselines. Add a fresh-data screen of baseline, queue1/fourlines and frozen/fourlines
plus both NOP controls, cloning the unchanged original1Mrecord dataset read-only
before EACH arm. Preserve the normal50/50 workload and30second warmup. Any promoted
confirmation also uses these per-arm fresh clones. Historical screens remain
exploratory; this reset is not a workload reduction or a selected-trial exclusion.
