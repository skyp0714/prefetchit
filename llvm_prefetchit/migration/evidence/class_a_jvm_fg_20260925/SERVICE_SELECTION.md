# Service screen selection, fixed before new service qualification results

Select the largest user L2-code MPKI among valid settings with at least 15% CPU utilization over the assigned measurement cores. This deliberately selects instruction-miss-heavy operating points within ordinary workload settings; it is not an unbiased service average.

- Require full PMU scheduling, no request/delivery failures or client drops, and achieved rate within 2% of offered rate for OpenSearch/Pinot (5% for the official Gatling flow parser, where window boundaries span several HTTP requests).
- Keycloak: retain the official Gatling assertions, including mean HTTP response time <=300 ms. Do not weaken the vendor password policy. TLS and normal DB durability stay enabled.
- OpenSearch: preserve standard query caches/refresh/plugins, TLS/auth; p99 scheduled-offer-to-response <=500 ms for this 50k-document interactive fixture.
- Pinot: eight segments, 1M fact/1k dimension rows, MSE count/group/join mix; p99 scheduled-offer-to-response <=1000 ms, every result matches the independent integer aggregate oracle.
- Flink: preserve 30s exactly-once checkpoints and normal RocksDB state. Confirm completed checkpoints and source progress; if input is backpressured below its configured rate, label a capacity workload, not a fixed-throughput comparison. The official blackhole sink has no semantic result oracle. Keep that limitation visible.

Primary A/B: same experimental JVM library SHA, same input/index/flags except G/F/NOP; no PMU. Use process CPU per completed query/flow as the primary fixed-rate efficiency metric and p99 as a guardrail. A fixed offered-rate test does not directly establish higher peak throughput. Recheck promising >=1% results in independent randomized pairs; never infer significance from repeated operations within one JVM.

If no setting meets the gate, report exclusion; do not equate untested prefetch with zero speedup. A2/A3 mechanics can still be checked diagnostically, with no performance conclusion.

Qualification clarification before primary runs: client drops are excluded in the **measurement offer window**; cold-start warmup drops remain recorded separately. Pinot150 had233 dropped offers only during startup, none at230–260s measurement (reconstructed offered-time grid in drop_audit.json). New clients record offered start and every drop timestamp directly. No failed semantic oracle responses are allowed. Original stricter whole-run screening rows remain unchanged; selection uses explicit audited-window status. Primary adaptive-warm maximum600s; no compiler flags changed.
