# Which branch brings execution onto an L2I-missing line? (indirect-target share, 2026-09-21)

Question: do any of our workloads have a large share of misses whose target is only known in a register (vtable / function-pointer
calls, jump tables, tail calls, PLT/GOT), i.e. where a register-based `prefetcht1 (%reg)` could be used, beyond the cross-DSO case?

Method: L2I code-miss samples (`cpu/event=0x24,umask=0x24/upp`) with LBR (`-b`), `perf script -F ip,dso,brstack`; the type of the most
recent taken branch (LBR[0]) is perf's own branch-type field; "PLT" = from-address inside a `.plt*` section of the host copy of the
executable/DSO (file offsets via the process maps); "miss-on-its-target-line" = the missed IP is on the same 64 B line as LBR[0].to.
Tool: `lbr_type_share.py samples_lbr.txt maps.txt <host binaries...>`. Traces: Verilator = `static_overhaul_20260916/truth_new`
(sample_type_overview.csv, perf's IND/IND_CALL types, no PLT split); proto = fresh 6 s sample on core 36 (this dir); Django = 
`capacity_django_20260919/traces/lbr_base` (uwsgi + libpython 3.14, clang 19, computed-goto dispatch); thrift services = gs builds
(static libs, dynamic libc) `trace_gs_pin_lbr` / `trace_cps_gs_lbr` / `capacity_media_20260920/traces/lbr_gs`.

| workload (L2I MPKI) | same-DSO indirect: vtable/fptr call | same-DSO indirect: jump table / tail jmp | cross-DSO (PLT stub, `call/jmp *GOT`) | RET | COND / CALL / UNCOND (direct) |
|---|---:|---:|---:|---:|---|
| Verilator DualMegaBoom (57) | 0.02% | 0.5% | (memset/memcpy PLT counted in CALL) | 7.5% | 68.6 / 14.8 / 8.6 |
| FleetBench proto_benchmark (16.9) | **13.3%** | 2.6% | 0.6% | 6.3% | 32.6 / 37.6 / 7.0 |
| DCPerf v2 Django, uwsgi + libpython (2.4) | 5.4% | **13.2%** (CPython `jmp *(%r14,%rcx,8)` opcode dispatch 3.5% at one site, rest other DISPATCH copies + Cython switch tables) | 9.7% | 14.5% | 34.4 / 14.4 / 8.3 |
| socialNetwork UserTimeline gs (1.1 alone / 9–13 pool) | 3.4% | 2.7% | **13.6%** (PLT 11.5) | 14.0% | 36.4 / 21.1 / 8.8 |
| socialNetwork ComposePost gs (1.0 / 42–44 pool) | 8.8% | 2.4% | **13.9%** (PLT 13.2) | 12.3% | 30.0 / 24.8 / 7.8 |
| media MovieId gs (4.9 / 55 pool) | 8.2% | 2.5% | **10.4%** (PLT 9.0) | 16.0% | 31.9 / 21.3 / 9.7 |

Top register-indirect sites: proto — `RepeatedPtrFieldBase::ClearNonEmpty<...>` `call *0x10(%rax)` (virtual Clear per repeated element) 7.9%
of all misses at one site, `MergeIntoClearedMessages` `call *0x20(%rax)` 3.5%, `WireFormatLite::InternalWriteMessage` tail `jmp *%rax` 2.1%,
`Message::SpaceUsedLong` 1.0%, `MergeFromConcreteMessage` `call *%r15` 0.5%, `TcParser::MiniParse` `jmp *(%r11,%rax,8)` 0.15%.
Django — `_PyEval_EvalFrameDefault` `jmp *(%r14,%rcx,8)` (opcode_targets) 3.5% + more DISPATCH copies, `_Py_Dealloc` `call *` (tp_dealloc) 1.1%,
`type_call` 0.5%; Cython modules (cassandra-driver cluster/protocol/connection) switch tables 0.7–1.0% each.
Thrift services — PLT stubs into libc/libmemcached (9–13%), thrift `TVirtualProtocol`/handler vtables (3–9%), TType switch tables (2–3%).

Reading: outside cross-DSO, register-only targets are 6–19% of misses (proto 16%, Django 19%, thrift 6–11%), concentrated in a handful of
generic-runtime sites (protobuf runtime → generated message methods; the interpreter dispatch; thrift protocol vtables). At 0.7%/MPKI the
upper bound of a register-based target prefetch is ~1.9% on proto and <0.5% elsewhere, *if* lead time can be created (hoisting the
vtable/table load above the call/dispatch) — the branch itself gives none.
