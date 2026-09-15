# JIT Task A: C2-integrated instruction prefetch — plan

Date: 2026-08-16. Context: DaCapo tomcat L2I MPKI ~12, all served from LLC
(L3 code miss 0.0%), flags move nothing (<±5%), sidecar warming structurally
impossible on private-L2 GNR → prefetches must be emitted INTO the JIT code
running on the consuming core.

## Can we open up the JIT? — Yes

HotSpot is GPLv2 open source. Everything we need lives in the `jdk` repo:

| what | where |
|---|---|
| C2 optimizer (Ideal graph) | `src/hotspot/share/opto/` |
| C2 code emission | `share/opto/output.cpp` (`Compile::fill_buffer`, scheduling) |
| x86 machine defs incl. call encodings | `cpu/x86/x86_64.ad` (`CallStaticJavaDirect`, `CallDynamicJava…`) |
| macro assembler (emit prefetcht1 = `Assembler::prefetcht1`) | `cpu/x86/{assembler,macroAssembler}_x86.cpp` (prefetch encodings already exist) |
| direct-call patching / inline caches | `cpu/x86/compiledIC_x86.cpp`, `share/code/compiledIC.*` |
| per-method profiles (block/branch counts) | MDO: `share/oops/methodData.*`, C2 reads via `ciMethodData` |
| code cache / nmethod layout | `share/code/{codeCache,nmethod}.*` |

Build: `bash configure --enable-headless-only --disable-warnings-as-errors
&& make images CONF=release JOBS=64` with boot JDK
`benchmarks/tools/jdk17` (~30-60 min on 86 cores). Incremental hotspot
rebuilds (`make hotspot`) are minutes.

## Injection design — three variants, ordered by risk

Winning pattern from the AOT campaign: RET/callsite family
(static_top1k_callsite_b1: prefetcht1 of return/callee lines at call sites,
1000 sites, +64B pair) beat all COND plans and the PGO oracle.

### V1 (lowest risk, no relocation): return-target prefetch at call sites
At C2 emission of a call in a hot block, emit
`prefetcht1 [rip + disp]` targeting the return continuation line +64
(the code AFTER the call, same nmethod, offset known at emission, never
patched). Mirrors the AOT ret-prefetch mechanism: warms the continuation
that gets evicted while a long callee runs.
- Implementation: extend the call MachNodes' `ins_encode`/size functions in
  `x86_64.ad` (or a peephole in `output.cpp` before emitting MachCall) to
  optionally prepend the prefetch. Gate: `-XX:+PrefetchRetTarget` +
  hot-block check (`block->_freq` threshold) + per-nmethod cap.
- Risks: instruction size accounting (MachNode::size must match emitted
  bytes), OopMap/PC-offset bookkeeping (safepoint PC = call end — emitting
  the prefetch BEFORE the call keeps the call's own offsets intact).

### V2 (moderate): callee-entry prefetch at direct call sites
Prefetch the callee nmethod's verified-entry lines before the call. Target
address is only final after IC/direct-call patching → also patch the
prefetch displacement in `CompiledDirectCall::set_to_...`
(`compiledIC_x86.cpp`), or emit the prefetch inside the per-callsite stub.
- Gets the "warm the callee front" effect (our CALL-target static plans).

### V3 (uses free profiles): MDO-guided site selection
Replicate the AOT planner in-VM: rank call sites by MDO counts, inject only
top-N per nmethod (the 1000-injection lesson: small surgical plans win;
pgo_cond_cov100-style blanket injection was 0.948x). C2 already has block
frequencies at emission time, so V1+hot-gate is effectively this.

## Evaluation protocol

- Workload: DaCapo tomcat (`-n 25`, windowed perf attach 25s+30s), plus
  tradesoap (borderline 4.0 MPKI) as second point; spring as low-MPKI
  control (expect no effect / no regression).
- Metrics: iteration ms (last 3), L2I MPKI, L3 code miss (raw OCR event
  0x2a/0x01/config1=0x3FBFC00004), instruction overhead.
- A/B: stock build vs patched build, same flags, frozen 2GHz platform
  (`configure_fixed_frequency_v2.sh MODE=2ghz`), server cores pinned.
- Success bar (user targets): ≥5% iteration-time gain outside error bars;
  MPKI reduction with sub-1% instruction overhead as mechanism check.

## Milestones

1. M0: clone jdk17u, stock build, reproduce tomcat numbers with our build
   (sanity: same MPKI as distro jdk17). [~1 day incl. build debugging]
2. M1: V1 behind a flag, correctness (jtreg tier1 smoke + DaCapo runs
   green), first A/B numbers. [~2-5 days]
3. M2: hot-gating sweep (freq threshold, per-nmethod cap, +64 pair on/off)
   — the injection-count ladder, AOT-campaign style. [~2-3 days]
4. M3 (stretch): V2 callee-entry with patching. [~1-2 weeks]

## Open questions

- Does the DaCapo tomcat driver's request mix keep nmethod set stable
  enough across iterations for stable A/B? (yesterday's sd suggests yes)
- Interaction with `-XX:+UseCodeCacheFlushing` recompiles — prefetch
  targets always intra-nmethod in V1, so safe by construction.

## M1 results & V2 expected-value analysis (2026-08-16)

M1 done same-day: V1 verified at machine-code level (prefetcht1 pair with
correct disps before calls), DaCapo-clean. A/B on tomcat: blanket injection
neutral-to-negative (lines=2 mpki 12.58, lines=1 12.02, stock 11.65) — Java
callees are short; return lines stay warm; bloat costs.

Miss attribution (jcmd Compiler.perfmap + offset histogram, 200k samples):
- Profile is FLAT: top method 1.26%, long 0.5-0.9% tail — PostgreSQL-like
  diffuse, not Verilator-like structured.
- Only 24.1% of JIT misses land in method entry regions (<128B; 32.1%
  <256B) → V2 (callee-entry prefetch) upper bound ≈ 13-17% of total L2I
  misses ≈ 2-4% time. The ~70% interior misses would need intra-method
  injection against a flat profile (the PG lesson: structurally capped).

Two-axis workload classification for the paper: MPKI (is it i-cache-bound?)
× miss structure (concentrated chains vs diffuse). SW prefetch wins need
both; tomcat has the first but not the second.

## V3 + measurement-hygiene postmortem (2026-08-16)

V3 (call-anchored lookahead, PrefetchRetTargetAhead) implemented and swept.
Single-run sweeps showed MPKI 12.9→8.7 and −2.5% time — **later shown to be
a co-location artifact**: concurrent arc builds/runs were stealing cores
from the tomcat run, reproducing the morning's core-packing effect. Clean
interleaved 3-rep confirm on an idle machine: v3_4096 13.19 MPKI (worse
than stock 12.93), lines=1 12.66, time unchanged. **V1, V2, and V3 are all
neutral-to-negative on tomcat** — the diffuse+flat miss structure absorbs
every C2 injection strategy tried. Rule added to the protocol: never
overlap measurements with builds or other runs; interleave configs; ≥3 reps.

Remaining untried levers (documented, not attempted): C1 coverage
(LIR_Assembler call emission), interpreter/stub region prefetch, and
cross-nmethod layout (code-cache compaction — out of prefetch scope).
Working reference implementations of all three variants remain in the tree
behind flags for future workloads that hit the (high-MPKI, structured,
unsaturated) operating window.

## Policy exploration completed (2026-08-16) — mechanistic closure

All prefetcht1 (verified 0F 18 15 throughout). Policies swept clean
(idle machine, interleaved, ≥2 reps): V1 ret / V2 callee+repatch /
V3 lookahead 256-8192 / V4 entry-burst (128-256B × 8-32 lines) ×
{tiered, C2-only}. Results on tomcat:

- V4 is the first policy that actually cuts misses: L2I 12.85 → 10.27
  (−20%, consistent) — but wall-clock +0.7% (burst overhead > savings).
- Topdown: tomcat FE-bound 43.5% (vs Verilator 69.0%) — substantial, so
  why no time? **Hierarchy reachability**: tomcat L1I 35.5 vs L2I 13.2 →
  63% of instruction misses are L2 hits (~10 cyc), which prefetcht1 — an
  L2-filling hint — cannot address BY DESIGN. Verilator: L1I 59.8 ≈ L2I
  58.7 (98% stream past L2) → t1's entire target population.

Four-axis workload criterion (final): (1) L2I MPKI magnitude, (2) miss
structure (concentrated vs diffuse), (3) FE-bound share, (4) **L1I≈L2I
(misses must stream past L2 for a t1-based technique)**. Tomcat passes
1 and 3, fails 2 and 4. Success with prefetcht1 in JIT requires a JVM
workload whose ACTIVE JIT code working set streams past L2 (>2MB walked
per reuse interval); none of the screened DaCapo/Renaissance workloads
has that profile (tomcat is the max at L2I 12).

The V4 (−20% L2I at entry-burst 128x32) result stands as the working
policy for any future workload passing all four axes.

## M-final (2026-08-17): C3 real-service win — WideApi +11.0% QPS

Renaissance screen (first true L2I screen of the suite): finagle-chirper
6.27 MPKI (gated V4 neutral in round-2, round-1 +1.9% was noise),
finagle-http 1.51, akka-uct 3.82, reactors 0.72, dotty 1.55, Trino TPC-H
0.75-1.71 — all fail axis 1 or the L2-residency wall (tomcat: V4 cuts
MPKI 33.8→30.6 but time flat; misses are L2-resident, t1-unreachable).

WideApi: wide-API composite-endpoint HTTP service (JDK httpserver, 4000
generated endpoint handlers ~2KB code each = 11.2MB JIT footprint,
chain=512 fan-out per request ≈52% generated-code share — the
generated-API fleet profile). Under load: 35-50 L2I MPKI, IPC 0.69-0.85,
43% of L2 code reads stream past L2.

A/B ladder (all layout-free JVM-flag A/B, fresh server per run, 15s+15s
warm, 60s measured, interleaved):
- client-bound (4x8, 12.4k qps): V4 128x32 MPKI 50→17, IPC 0.686→0.836,
  QPS flat (server not bottleneck) — cycles/request −18%.
- 16x8 (44k qps): still client-bound, same IPC story.
- fixed-capacity (server pinned 4 cores, 12x8): stock 14391 →
  v4_128x32 +10.2%, **v4_g256 +11.1%**; v4_64x8 −1.8% (too shallow).
- confirmation 5 reps: **stock 14394±30 vs v4_g256 15984±35 = 1.1104
  (+11.04%), min-gap 1520 qps; p50 6.24→5.74ms (−8%), p99 14.13→11.37ms
  (−19.5%), MPKI 34.9→12.3, IPC 0.848→0.993.**
Config: -XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32
-XX:PrefetchEntryMinBytecode=256 (the gated deployment default from the
DaCapo negative analysis — the gate that protects tradesoap/spring also
keeps the win here).

Class-3 final standing: JCodeStream 1.285 (mechanism), WideApi 1.110
(real service stack at fixed capacity + tail latency), avrora MPKI −20%
(time-flat: backend-bound), boundary map: tomcat (L2-resident), chirper
(moderate MPKI + hierarchy), dotty/trino (loop-hot, low MPKI).
