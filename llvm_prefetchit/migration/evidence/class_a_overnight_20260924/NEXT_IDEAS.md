# Chronological experiment hypotheses

Status statements below were written during preparation and can be superseded.
Use the final campaign report, selection JSON and phase manifests for current
execution/completion status; these notes are not a results table.

A3 Scylla: prior frozen runtime predictor gave 97.2% next-target accuracy but only
2.45% misses/op reduction and +1.08% instructions/op, neutral CPU. A possible next
method is offline-trained static dispatch rules with a small constant decision
cascade, removing per-reactor owner hashing/model lookup from the hot path. Keep
queue lookahead, and use rules only when no queued task is readable, preserving the
measured depth gate. It is profile-guided A3, not pure static analysis. Compare
baseline, rule hints, exact NOP, and the previous frozen predictor with fresh data.

First acquire the frozen transition tables in a diagnostic-only run. Existing
Scylla gate/build/harness live under class_a3_dispatch_20260924. Each reactor slot
is 16384 bytes, owner at0, training-remaining at176; 256 tagged successor entries
start at256, 32 bytes each (key, successor, confidence, unused). The existing
snapshot helper reads the full state but currently serializes only 256-byte headers.
Require all training remaining=0 before interpreting frozen table rows. Preserve
read-only source dataset cloning and real durable MySQL colocation (A3 method,
B miss regime). Original package and final frozen4/NOP binaries remain available;
its task-owned data volume was removed and must be recreated before reuse.

If feasible, use Scylla .eh_frame function boundaries plus direct-call disassembly
to prefetch actual static callees of predicted task handlers, instead of only the
usually hot virtual entry. Profile-free graph expansion and offline transition
prediction must be separately labelled. A constant cmp/jcc -> RIP T1 cascade avoids
runtime table/object dereferences for predicted addresses. Use measured held-out
accuracy; target correctness is not useful cold-line coverage. Do not claim this
idea is implemented or tested until it is.

A3 FeedSim: prologue4 and batch4 policies are implemented in the source transformer
and sanitizer-tested but not yet built/performance-tested; first rotation only
prologue and staged. Prologue requires the partial new-hints-NOP control (keeps
legacy lead4) in addition to all-NOP. Native T1 in the selected original function
is zero. Tagged control uses SHF_GNU_RETAIN (nonallocated section flag R), required
under production --gc-sections and verified after --strip-debug.

A1 final verification: wave1 22 debugger probes passed exact final-state hashes
(200/2000 cycles). After wave2, run validate_arcilator_state.py --out
state_validation_wave2 only when no timing/build pipeline remains. Original native
prefetch count zero in both simulators, streaming audit complete. New global-stream
variants still need state comparison. Do not promote old assembly gains as a new
algorithm; they were rediscovered in older raw evidence.

A2 MySQL cost reduction: previous live-vtable wrapper hooks were -0.16% vs base,
+0.88% vs NOP in one screen, with roughly1% address/hook cost. Inspect pinned
mysqld virtual tables for the actual fixed InnoDB operating point and existing
in-function NOPs in ha_rnd_next/ha_write_row/ha_update_row/ha_index_read_map.
A static type-informed target (ha_innobase method or a bounded direct descendant)
can be prefetched with one RIP hint in an existing NOP, avoiding repeated vtable
loads and appended jumps. This would be A2, closed-workload type information,
not a generic devirtualizer. Exact control should be byte-identical original.
Must prove eligible NOP is an instruction inside the wrapper and report available
static lead/call path; do not silently patch neighboring function alignment.
If no eligible site, keep a clear negative feasibility result or evaluate the
existing allocated padding planner at a verified caller. Durable400TPS,16x200k
records and original MySQL settings must stay unchanged; fresh paired validation.
This is only an idea, not implemented or tested.

A3 FeedSim further mechanism (conditional on staged results): current prologue
only covers four initial calls, while run.sh defaults to240extractors/story, so
its ceiling is structurally small. Do not waste a large prologue4 confirmation
without evidence. Staged/body coverage or variable-work lead is more promising.
Possible static-size-aware lookahead: derive generated CopyFn sizes/instruction
estimates from baseline symbols; build per-array-index future-target metadata
once after immutable shuffle, choosing a bounded future index by estimated code
work rather than fixed call count. Runtime reads one prepared target pointer.
Call order/count/work must remain unchanged; NOP retains the metadata overhead.
Avoid a huge hot runtime hash table; a coarse relative-address size table or
precomputed array may suffice. Any assumption that relative code offsets remain
stable must be checked against every final binary; generated functions are never
recompiled by the existing FeedSim helper. Additional metadata footprint/loads are
part of measured overhead. This is unimplemented, not a result or guaranteed gain.

Audit caveat: A1 retuning index groups instructions by objdump symbol headers,
so group ends may include trailing alignment NOPs. Do not describe this as exact
nm-sized function-body bounds. The global-stream comparison deliberately removes
that group restriction. Original recorded bytes and reversal checks remain valid.
If adding strict symbol-size bounds later, use a versioned fresh index and a new
campaign rather than retroactively changing existing timing metadata.

Fresh staged screen after harness repair: +8.273% vs base, +1.826% vs prior
lead-four, +8.318% vs staged all-NOP (two paired rounds only). Five fresh rounds
are now running. If confirmed, queued wave4 diagnoses entry12 versus body4
components at identical code. A further direct control could use entry+64+128
all at lead4 to isolate whether the far-entry distance itself helps; not yet
implemented. Do not assume earlier lead1/2/8/lead4lines2 build manifests prove
those policies were performance-tested: only lead4 has found timing records.

MySQL follow-up preparation: cached static NOP/call index yields four potential
caller sites at 128..2048-byte physical lead. Two follow unconditional JMP/RET
and are excluded as non-fallthrough alignment. The remaining two are in
Sql_cmd_update::update_single_table at d79e89 and d7a1e1; engine target
ha_innobase::update_row is c9a3b0 (size0x6f4). New pinned builder emits fixed
RIP T1 at existing seven-byte NOPs; original is exact control. It is only a
normal-InnoDB-workload prediction, not proof all handler instances use that
engine. Queued wave5 executes only if enough time remains after wave4.

Reporting limits: A1 arcilator is the unchanged 20k-cycle eval/clock driver,
not a loaded processor payload; Verilator is the established 100k-cycle qsort
prefix (roughly79s baseline at2GHz), not completed qsort. Keep these scopes in
any speedup table. Full-payload validation would need a new complete-work
campaign and enough time; do not silently relabel prefix/driver gains as full
application completion. Old assembly-policy gains are reproductions, not new
improvements from tonight's proposed methods.

Static-size adaptive lookahead is non-bijective: choosing the first future
index beyond a code-byte budget can prefetch some entries repeatedly and skip
others. Record this coverage limitation if work4096/work16384 lose; it must not
be interpreted as a pure lead-time-only comparison. Runtime pointer metadata
and its NOP preserve identical expanded-vector layout and address costs.

Prepared exact near-entry control: retain staged pointer computations/hint count,
retarget entry hint register to the near-body register (lead4) at identical
instruction length. If the emitted registers need a different encoding length,
record infeasibility and continue entry/body comparisons. Queued wave4 test
covers low-register retarget/reversal and execution; no performance result yet.

Scylla diagnostic caveat: matched-target TSC differences measure dispatch
observation points, not actual instruction-fetch lead; branch prediction may
fetch the target before the observed next dispatch. Keep rule/queue precision
and per-work miss reduction separate, and do not call dispatch timestamps
measured fetch latency. A successor can be correct while its entry is hot.

LLVM interpretation: 9801/9975 are static patch-site counts, not measured
dynamic hint issue counts. Existing alignment NOPs can be infrequently executed;
entry hints can also miss colder internal blocks. A neutral padding policy is
not an upper bound on useful compiler insertion. If further time exists after
current rotations, software-prefetch request counters or L2-miss/LBR coverage
would distinguish sparse execution from hot-target/short-lead limitations.

### Follow-up inferred after component/static-work screens (not yet timed)

A lean fixed-lead4 three-line source policy is a justified next candidate: the
same-code near3 target substitution was +0.20% vs staged, while retaining staged's
unneeded far-target computation. Static-work4096 with three lines was −0.53% vs
staged. A new source variant could keep entry/+64/+128 at lead4 and remove the
far lookup entirely, with original/lead4/staged/own-NOP controls and fresh
confirmation only after selection. Existing near3 is **not** that optimization;
no speedup is claimed for the unbuilt lean variant. This is deferred while the
remaining interval covers MySQL, graph composition and stall attribution.

Scylla callback3 also expands fallback queue entries; short wrappers may therefore hint neighboring functions. A guarded-only expansion with statically/profile-validated callback footprints would isolate that variable, but was not built or timed in this interval. The measured issuance budget is small relative to demand code misses, so broader useful footprint coverage has priority over further accuracy tuning.
