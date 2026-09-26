# HotSpot C2 graph/future-target prefetch

Final G2 source patches for the JDK 17u and 21 trees, plus small policy/callback,
encoding and dead-call test programs. The patches include both graph (G) and future
receiver (F) modes and NOP controls; they replace the earlier `jvm_fg.patch` prototype.
See the [scheme and experiment report](../../../../docs/class_a_jvm_fg_20260925.md)
and the [latest, incomplete recheck status](../../../../docs/class_a_jvm_status_20260926.md).

The 17u experiment used the development tree at `5ef54a04aa15` (17.0.21-internal);
the 21 experiment used 21.0.8+9. Exact runtime/source records accompany the compact
JVM evidence. These are diffs against those experiment trees; inspect context and
use `git apply --check` on a matching checkout before applying. They are not patches
to stack on the earlier prototype. No JDK source checkout, generated build, code-cache
dump or binary is included. `sources.json` records the exact source-file hashes.

The 100-block service recheck was incomplete at the published snapshot. Do not infer
100 repetitions or confirmed cross-workload gains from the planned count.
