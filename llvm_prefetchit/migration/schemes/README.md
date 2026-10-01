# Prefetch scheme source map

Reusable native implementations live in the normal source directories. Small dated
snapshots retain the completed JVM, AsmDB and Class B experiments that previously
lived only in ignored result directories. These snapshots document host-specific
prerequisites; they are not packaged benchmark distributions.

| Class / method | Source | Results |
|---|---|---|
| A-1 sequential lookahead / callee burst | [LLVM pass](../../lib/PrefetchITPass.cpp), [Verilator driver](../../scripts/static/build_verilator_variant.sh) | [Class A summary](../../../docs/results_summary_20260924.md) |
| A-2 static call graph / schema | [call graph planner](../../tools/callgraph_prefetch_plan.py), [schema planner](../../tools/proto_schema_prefetch_plan.py), [padding insertion](../../tools/prefetch_in_padding.py) | [generalization](../../../docs/class_a_generalization_20260922.md), [A-2](../../../docs/class_a2_campaign_20260923.md) |
| A-3 future targets / dispatch prediction | [FeedSim policy](../../scripts/static/feedsim_future_policy.py), [RPC](../../scripts/static/build_rpc_future_targets.py), [Scylla](../../scripts/static/build_scylla_future_targets.py) | [factorial](../../../docs/class_a3_campaign_20260923.md), [dispatch](../../../docs/class_a3_dispatch_20260924.md), [staged follow-up](../../../docs/class_a_overnight_20260924.md) |
| JVM C2 G/F/GF | [JDK patches and test programs](jvm_fg_20260925/README.md) | [latest incomplete confirmation](../../../docs/class_a_jvm_status_20260926.md) |
| Trace-guided AsmDB-style placement | [instruction-window planner and rewriter](asmdb_trace_20260926/README.md) | [negative result and takeaway](../../../docs/class_a_asmdb_trace_20260926.md) |
| B shared-core cold misses | [per-service PT/wake-stream drivers](class_b_extension_20260926/README.md) | [Media/SocialNetwork extension](../../../docs/class_b_coldmiss_summary_20260926.md) |
| B five-service coverage and selected-next-task spacing/split | [full-set drivers](../../scripts/class_b/README.md), [kernel emission module](../../kernel/wake_prefetch/README.md) | [five-service confirmation and cold/timeliness diagnostics](../../../docs/class_b_fullset_20260926.md) |
| B temporal trace and call-graph placement, shared GOT anchors | [campaign](../../scripts/class_b/temporal_path_confirm.py), [residual analysis](../../scripts/class_b/temporal_path_residual.py), [residual repair](../../scripts/class_b/temporal_path_repair.py) | [nine-app/library/Mongo confirmation and miss-age analysis](../../../docs/class_b_temporal_20261001.md) |

Exact-layout controls are implemented in [make_nop_control_binary.py](../../tools/make_nop_control_binary.py)
and [make_tagged_prefetch_control.py](../../tools/make_tagged_prefetch_control.py).
Static, profile-guided placement and source-specific future-target prototypes are
separate methods; the source snapshots do not establish arbitrary-C++ generalization.
Generated per-binary plans, indices, decoded traces, compiled code and retry controllers
are not part of this publication. Negative results and incomplete confirmations remain
visible in the linked reports and [compact evidence inventory](../evidence/README.md).
