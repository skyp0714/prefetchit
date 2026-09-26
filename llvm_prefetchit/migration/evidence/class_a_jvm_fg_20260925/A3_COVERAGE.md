# Coverage constraints of current F2

F2 is a conservative entry-known receiver prefetch, not arbitrary future queue-item prediction. It recognizes unchanged reference parameters and one final reference field in a contiguous bytecode reference-load sequence, and admits only a surviving non-inlined root receiver call. It excludes dead/inlined calls but also misses more complex valid opportunities.

Pinot1.3 OpChainSchedulerService.register submits a TraceRunnable. Its runJob performs accounting before calling operatorChain.getRoot().nextBlock(). OpChain stores its root in a final field, but the path from the Runnable traverses a captured chain and a getter. This is a concrete depth/getter coverage gap for the current bytecode matcher. Inlining of nextBlock may also move the actual surviving indirect call deeper into the graph. This source observation alone does not establish that this path causes most L2 misses.

Sources (exact tested release):
- https://raw.githubusercontent.com/apache/pinot/release-1.3.0/pinot-query-runtime/src/main/java/org/apache/pinot/query/runtime/executor/OpChainSchedulerService.java
- https://raw.githubusercontent.com/apache/pinot/release-1.3.0/pinot-query-runtime/src/main/java/org/apache/pinot/query/runtime/operator/OpChain.java
- https://docs.pinot.apache.org/release-1.3.0/for-users/user-guide-query/multi-stage-query/operator-types

Post-timing codelist/machine-prefix inspection reports emitted hints in stable C2 methods. It is not dynamic hint execution frequency, useful lead time, or causal miss coverage. Low or zero F2 hint counts must not be presented as proof that future-target prefetch in general cannot help.

The first F2 primary run emitted256 hints in128 C2 method bodies (broker85, server43). These include MultiStageOperator.nextBlock, BaseOperator.nextBlock, MailboxSendOperator.getNextBlock, HashJoinOperator methods and QueryDispatcher.execute. This identifies injection roots, NOT the selected callees. javap shows logger() atBCI17/29 and getNextBlock() at61 inside MultiStageOperator.nextBlock. The MinBCI32 pilot is a general threshold experiment, without method-name selection. Post-timing read-only metadata and selected prefixes now bind the vtable to the root nmethod holder in the same JVM; diagnostic names do not alter the prefetch algorithm.

The current bytecode matcher tracks contiguous reference-load sequences, not general operand-stack dataflow. Primitive argument computation, array indexing, and intermediate method-return values can reset its state even if the receiver itself could have been available early. These are conservative coverage exclusions, not evidence that those future targets are unpredictable. Broad negative F2 results must retain this limitation.

Pinot lead-pilot F16 completed: same-JVM declared-class vtable binding via nmethod->Method->holder identifies both emitted server nextBlock hints as logger() (two lines), not getNextBlock(). Broker snapshot has no matching prefetch target in that root. This is a snapshot of compiled code, not runtime execution-frequency evidence. F2 has no minimum dynamic-callee bytecode-size filter; the64-bytecode callee threshold is G-only. Completed BCI32 F/GF server snapshots select getNextBlock(). The single-JVM F32 pilot worsened CPU/query by2.40%; GF32 improved0.31%. Target selection changed, but this does not establish beneficial lead time.

Independent75-run confirmation is complete. No candidate has a positive95% interval against both baseline and its own matched NOP. Future-genetic GF post-timing prefixes contain only0–2 F2 hints per run, reinforcing the narrow coverage limitation. Full details are in docs/class_a_jvm_fg_20260925.md.
