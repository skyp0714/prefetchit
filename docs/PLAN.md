# Plan (written 2026-09-15, after the restore and re-verification)

Goal restated in the project's four stages:

1. **Microbenchmark** (`icache_microbenchmark/`): shows when instruction
   prefetches are dropped/ineffective and that `prefetchit0/1` is a no-op on
   Granite Rapids, so code prefetch has to use the data-prefetch `prefetcht1`.
2. **Static compiler pass** (`llvm_prefetchit/` + `static_prefetch/`):
   profile-free target/site selection through the LLVM pass must match the
   profile-guided (LBR/PEBS) placement. Proven only on Verilator (static
   1.078x vs PGO 1.075x) and arcilator (1.051x). Wanted: a datacenter member.
3. **Indirect-call / dispatch prefetch**: 1–2 source lines that prefetch the
   *future* target held in a control-flow data structure. Django 1.49x,
   FeedSim 1.073x (DCPerf). Wanted: more real workloads.
4. **JVM JIT prefetch** (`jit_prefetch/`): HotSpot C2 emits the prefetches.
   JCodeStream 1.285x, WideApi 1.11x (both self-authored). Wanted: a
   recognised workload.

Goals as restated on 2026-09-15: **advance stage 2 (static), stage 3 (manual)
and their combination, find more workloads for them, and make stage 4 succeed
on a public workload (tomcat-class)**. The 2 GHz re-verification of Django,
FeedSim, JCodeStream and WideApi passed; Verilator is being re-run after the
intel_pstate reboot.

## How a new workload is admitted

1. **Screen**: L2I MPKI under load must be high — single digits at least
   (`scripts/platform/screen_l2i_mpki.sh`; JVM: also L1I/L2I ratio).
2. **PGO ceiling first** (static path): collect 3 PEBS+LBR traces, build the
   profile-guided plan through the pass, measure vs a NOP twin. If the
   profile-guided plan does not give a clear speedup, the static pass cannot
   either — stop there and record the workload as a boundary case.
3. Only then try the profile-free plan (`static_prefetch/tools/static_plan.py
   --kinds ret,cond,...`) and report static/PGO.
4. **Manual path** is direct: find the control-flow data structure, add the
   1–2 line prefetch, NOP-twin A/B. When the miss profile is split between a
   dispatch structure and function-shaped code, combine: manual prefetch for
   the dispatch targets + static/PGO plan for the rest (same binary, one
   `merge_prefetch_plans.py` plan for the compiler part).

## Constraints learned so far (do not re-discover)

- A workload qualifies only if all axes hold: L2I MPKI ≳ 10 under load,
  targets determined before the branch (lead time ≫ 1 branch), FE-bound, and
  misses streaming past L2 (L1I≈L2I). Every negative result maps to a violated
  axis (`PAPER_RESULTS_AND_FEEDBACK.md`, `jit_prefetch/docs/PLAN.md`).
- What matters is *dynamic* prefetch issue rate, not static site count
  (PostgreSQL density sweep); blanket injection loses.
- Same-binary NOP controls are mandatory: layout luck at datacenter scale
  (±1.6%) exceeds most claimed wins in this class.
- Real JVM suites are L2-resident (L1I/L2I ≈ 10): `prefetcht1` cannot help
  them; only an L1I-filling prefetch would, and `prefetchit0` is a no-op here.
- OLTP misses are re-evicted by data traffic (5th axis); prefetch-only ceiling
  ~0.3%.

## Stage 3 → more workloads (dispatch prefetch)

The two wins are DCPerf's synthetic `ICacheBuster` dispatch, so the credible
next members must be *real* dispatch structures. Search order, each gated by
a 30 s L2I/L1I screen (`scripts/platform/screen_l2i_mpki.sh`) before any code:

1. **Bytecode interpreters with computed-goto dispatch** — the handler of the
   *next* opcode is known one instruction early (`opcode_targets[next_op]`).
   Targets: CPython 3.12 `ceval` (already inside the Django stack: uWSGI
   workers), Lua/LuaJIT interpreter, QuickJS, wasm3 (all sources are in
   `benchmarks/datacenter_sources/`). Screen with a large-code app first;
   July screens showed interpreters compact (<1 MPKI) on small apps, so use
   a wide-API Python service (thousands of view functions) analogous to
   WideApi.
2. **Event-loop callback queues** — next callback's function pointer sits in
   the queue: libevent/libuv (nginx, node, memcached), HAProxy tasks (tried:
   neutral at low MPKI). Re-screen only under a code-heavy config (many
   modules/filters) where MPKI clears the bar.
3. **RPC method dispatch with early method id** — Thrift/gRPC handlers where
   the method id is decoded well before the handler call (DSB was neutral
   because misses are diffuse across DSOs; the fat-static build recovered
   57% of the PGO ceiling). Candidates: MicroSuite HDSearch/Router rebuilt
   fat-static, SPECjbb-like Java goes to stage 4.
4. **Plugin/filter chains** (Envoy, Kafka Connect-style, Django middleware
   chains): the chain array is the control-flow data structure.

Deliverable per member: `dispatch/` build variant + NOP twin + closed-loop
run (`dispatch/run_*_closedloop.sh`), 3 interleaved reps at frozen 2 GHz.

## Stage 4 → a public workload (tomcat-class)

What blocks tomcat today is measured, not guessed: L2I ≈ 12 MPKI but
L1I/L2I ≈ 10 (misses are L2 hits, ~10 cycles), so an L2-filling
`prefetcht1` cannot move time even when it removes 20% of the L2I misses
(V4 on tomcat: MPKI −20%, time +0.7%), and shrinking L2 to Emissary's 1 MB
with resctrl did not change that. Three routes, in order of expected payoff:

1. **Find the public members whose JIT code streams past L2** (the axis
   JCodeStream/WideApi satisfy). Screen with `jit_prefetch/scripts/
   screen_full_suites.sh` (L1I and L2I together): Spring PetClinic /
   Spring Boot reference apps under wrk, Elasticsearch/OpenSearch and Solr
   query paths, Kafka Streams topologies, Keycloak, Jenkins, Trino with
   wide schemas, SPECjbb2015 (the "wide-API" shape: thousands of distinct
   hot methods, uniform traffic). A member needs L2I ≳ 10 and L1I ≈ L2I.
2. **Get an L1I-filling prefetch.** `PREFETCHIT0` is inert on this Xeon
   6787P (microcode 0x1000405); re-test after a microcode update and on a
   newer part before writing tomcat off — with a working `prefetchit0` the
   V4 burst (`-XX:+PrefetchEntryIT0`, already implemented) is the tomcat
   experiment. Until then tomcat is the documented boundary case.
3. **Raise V4's reach inside C2** for members found in (1): MDO-guided
   site selection (only hot nmethods, per-nmethod caps), bursts at
   interpreter→C2 transitions and stubs, and a code-cache-aware policy
   (only prefetch nmethods known to be non-resident). Keep
   `PrefetchEntryMinBytecode=256` as the deployable default.
4. After a public JVM win, port the entry-burst policy to V8 (node) and
   .NET RyuJIT, whose code caches have the same shape.

## Stage 2 → datacenter member (static pass ≈ PGO)

0. **Finish the Verilator re-verification honestly.** The restore exposed two
   defects in the reference pipeline (`docs/RESULTS.md`): symbol+offset
   targets drifted with the injected bytes/codegen (fixed: in-pass
   compensation + post-link re-anchoring on call order), and the
   profile-free RET ranking chooses, per hot continuation line, a call that
   rarely returns into it (15% of RET-miss producers vs 65% reachable with
   the 1,000 hottest calls). Next: (a) rank *calls* rather than
   *continuation lines* — a profile-free hotness proxy for a call is its
   loop depth/backedge count in the caller and the callee's static call
   count, both already computed by `static_return_target_candidates.py`;
   (b) with budget > 1, take *all* calls returning into a selected line
   (`callsite` strategy today keeps one); (c) evaluate against the trace by
   "producing-call coverage", not "site anywhere in the LBR path".

1. **Compile the stage-3 pattern into the pass**: an `IndirectCallTarget
   Prefetch` transformation that recognises `load fptr from array[i+k] /
   field; call fptr` and inserts `prefetcht1` of the lookahead entry's target
   (distance as a pass option). This turns the manual Django/FeedSim/memcached
   edits into a compiler result and is the shortest path to a datacenter
   static-pass number. Validate on FeedSim/Django first (known ceiling), then
   on the stage-3 candidates above.
2. **MachineFunction (post-ISel) pass** for exact site anchoring and
   intra-function lookahead (design.md "known limits"; needed for
   arcilator-style inlined mega-functions).
3. **Generality audit of the static rankers**: train on Verilator qsort,
   evaluate untouched on arcilator MegaBoom and on a second Verilator SoC.
   Report recall/injection-count curves, not just speedup.
4. **DSO-aware plans** (GOT-anchor mode) as the default for dynamically
   linked services; fat-static only as an upper bound.

## Infrastructure to finish first

- GRUB: boot with intel_pstate active (current `/etc/default/grub` already
  does) so `freeze_platform.sh MODE=3.8ghz` works; keep 2 GHz mode for
  services. Coordinate on the shared machine before rebooting.
- Chipyard: initialise only the generators needed for
  `DualMegaBoomAndSingleRocketConfig` via chipyard's `build-setup.sh` and
  rebuild the Verilator simulator (multi-hour) to re-run the stage-2
  reference.
- Push the two unpublished pinned commits (DeathStarBench, MicroSuite) or
  update `benchmarks.lock.tsv` to the upstream commits now in use.

## Order

1. Infrastructure (above) — one day.
2. Stage 2 item 1 on FeedSim/Django — the cheapest new paper result.
3. Stage 3 screens (interpreters, event loops) — half a day each; go/no-go by
   the axis screen.
4. Stage 4 wide-API real service.
5. Stage 2 items 2–4.
