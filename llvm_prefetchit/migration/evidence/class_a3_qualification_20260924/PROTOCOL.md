# A-3 qualification before insertion, 2026-09-24

Keep miss regime separate from method. Do not promote a workload simply because
it contains an event queue, virtual method, request dispatcher or large executable.

1. Sweep normal configurations, preserve useful work and documented semantics.
   Use >=15% utilization, error-free service windows and reasonable latency; choose
   the maximum baseline user L2 code MPKI among eligible loads. Prefer >=5 MPKI
   (>=10 especially promising); 2-5 is a secondary tier only with strong target
   coverage. Existing FeedSim is a positive reference, not a threshold exception
   silently counted as a new candidate. Single-tenant and co-tenant results differ.
2. Record L2 speculative code MPKI, misses/work, user top-down slots, and retired
   indirect branches (C4/80, includes indirect jumps; NOT indirect-call count).
3. For qualifying settings collect separate precise FRONTEND_RETIRED.L2_MISS
   (C6/03, config1=0x13) with all user LBR branches. Report sampled entry-line /
   first256B / same-function association with actual indirect CALL targets,
   and bounded recent-call-chain association separately. These are sampled
   associations, not a proof the indirect branch caused a miss or a causal bound.
   Count all samples, unresolved DSOs, lost samples and uncertain branch types.
   Also collect separate ITLB walk-active/completed/STLB-hit counters to distinguish
   translation effects from code-cache effects; an increase in STLB hits can
   accompany fewer instruction page walks.
4. Only then examine future-address availability, object lifetime, queue depth,
   target agreement and real independent work between load/hint and use. Predict
   only if readable future depth/lead is demonstrably inadequate. Do not confuse
   branch-mispredict MPKI with code misses or instruction STLB misses.
5. No prefetch speedup claim from qualification. Any later candidate requires
   original/exact-NOP comparisons and fresh paired confirmation.

First native families: gem5 full-system CPU-model/core-count sweep using local
SPEC packaged simulator and its normal RISC-V Linux-boot configurations (not a
SPEC score), plus a realistic Envoy API-gateway filter/configuration sweep.
Existing Media/MySQL/Scylla results are references; old all-mode measurements
are labeled and are not pooled with current user-mode data.

Serialize builds/profiling and restore fixed 2GHz platform settings. Keep runtime
inputs local. Delete new rejected copies/build products after extracting compact
results. No arbitrary core oversubscription, hugepage disabling, code padding,
no-op handlers, repeated filters or logging amplification to manufacture MPKI.
