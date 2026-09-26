# AsmDB-inspired instruction-window placement

Source snapshot of the completed, negative FleetBench experiment. This adapts finite
instruction histories to `prefetcht1`/L2 and does not reproduce the paper's proposed
instruction or simulated L1I mechanism. See the [results and limitations](../../../../docs/class_a_asmdb_trace_20260926.md).

`asmdb_prepare.py` identifies safe native instructions and PEBS target heat;
`asmdb_stream.cc` counts actual PT instruction-window pairs; `asmdb_plan.py` chooses
sites with probability, fan-out and dynamic-issue budgets; `asmdb_rewrite.py` emits
in-place NOP replacements or conservative single-instruction detours with exact-layout
NOP twins. `asmdb_execute.py`, `asmdb_full.py`, `asmdb_broad.py` and `asmdb_report.py`
retain the measurement/analysis recipes. The C++ stream is the final denominator-fixed
version; the earlier exposed-history implementation is superseded and omitted.

The experiment drivers expect their original ignored directory
`llvm_prefetchit/results/class_a_expansion_20260925/`, Linux perf/Intel PT, LLVM tools,
LIEF, SciPy, the locally staged FleetBench baseline and PEBS/PT training records.
`ASMDB_RESULT_DIR` overrides the output path. Other input paths are host-specific;
inspect and adjust them before a new run. They are source/provenance snapshots, not
a promise that retired raw captures are available from Git. Async unwind inside new
detour stubs is unsupported.

`sources.json` hashes the exact extracted sources. Generated per-binary plans, decoded
instruction histories, binaries, traces and the containing reproduction archive remain
outside Git. Static schema prefetch remains the better measured reference.
