# Flattened-codegen class: second showcase plan (arcilator / ESSENT)

Date: 2026-08-16. Goal: add a second member of the flattened-codegen
simulator class beside Verilator, ideally one where our LLVM pass applies
directly.

## Candidate ranking

1. **CIRCT arcilator** (best fit): compiles FIRRTL → LLVM IR → native sim.
   Our `.fir` files for RocketConfig / DualMegaBoomAndSingleRocket already
   exist under chipyard generated-src. Pipeline:
   `arcilator design.fir --emit-llvm | opt -load-pass-plugin PrefetchITPass.so ... | llc | link runtime`
   → the pass integrates at IR level (no binary hacks), giving a
   second engine for the static-vs-PGO comparison.
   - Obtaining arcilator:
     a. official CIRCT release tarball (already at /tmp/firtool.tar.gz,
        contains bin/arcilator) — needs user to extract+approve executing
        the release binary (policy blocked the agent doing it);
     b. source build — BLOCKED practically: ~15-20GB build tree vs 25GB
        free disk.
2. **ESSENT**: FIRRTL→C++, even flatter than Verilator, our clang+pass
   toolchain applies to its output. BLOCKED on frontend version: our
   chipyard emits Chisel-7/FIRRTL-4 `.fir`; ESSENT's scala FIRRTL frontend
   predates it. Would need building an old-Chisel design from scratch.
3. Everything else screened out (25-workload survey: class is EDA-only).

## Arcilator experiment sketch (once binary available)

- M0: `arcilator rocket.fir` → run + validate; screen L2I MPKI of the
  arc-compiled DualMegaBoom vs Verilator's 58.6 (arc model is a different
  flattening — expect qualifying MPKI if code >> L2).
- M1: base vs pass-injected (RET/callsite-style plan generated from the IR
  call graph — static, profile-free) vs PGO-style plan from an LBR profile.
- Deliverable: "engine-independent class property" table — same design,
  two flattened engines (Verilator C++, arcilator LLVM), one interpreter
  control (vvp 0.002 MPKI), plus the Rocket-vs-MegaBoom size cliff.

## User action needed for path 1a

```bash
cd /tmp && tar xzf firtool.tar.gz
mkdir -p ~/prefetchit/benchmarks/tools/circt
cp -r firtool-1.130.0/* ~/prefetchit/benchmarks/tools/circt/
~/prefetchit/benchmarks/tools/circt/bin/arcilator --version
```

## M0 ACHIEVED (2026-08-16): arcilator DualMegaBoom qualifies — MPKI 79

Pipeline that works (scripts/stub_externs.py + EICG seq.clock_gate patch):
`firtool .fir --ir-hw` → patch EICG extern → stub 14 externs (sequential
counter stubs break false comb loops through blackboxes) → `arcilator
--emit-llvm --state-file` → clang -O2 + driver calling
TestHarness_eval + TestHarness_clock{,_0,_1} per cycle (NOTE: eval alone is
glue — the 493k-line TestHarness_clock is the real step; toggling the clock
input byte does nothing).

| engine | text size | inst/sim-cycle | L2I MPKI | IPC |
|---|---:|---:|---:|---:|
| Verilator DMB | 105MB | 1.13M | 58.6 | 0.56 |
| arcilator DMB | 8.7MB | 1.48M | **79.0** | 0.63 |
| arcilator Rocket | 753KB | – | ~1.0 | – |

Insight: arc dedup shrinks code 12x but converts the walk into thousands of
shared-arc CALLS — call/return misses dominate, i.e. exactly the pattern our
winning RET/callsite prefetch family targets. Second flattened-codegen
showcase secured, and it is MORE i-cache-bound than Verilator.

Next (M1): build dmb.ll with -g, generate static callsite plan with the
existing static_return_prefetch planner (symbol+offset matching — no source
lines needed), inject via PrefetchITPass EXTERNAL_PLAN path, A/B at frozen
3.8GHz. Caveat to note in writeup: zero-workload state walk (stubbed
memory); code-footprint screen valid, functional benchmark needs HTIF wiring.

## M1 results (2026-08-16): injection negative — saturation regime identified

3-rep interleaved A/B on idle machine (frozen 3.8GHz), 30k sim-cycles:
| variant | time | speedup | MPKI |
|---|---:|---:|---:|
| base | 29.13s | 1.000x | 79.1 |
| callee-entry blanket t1 (97.4k pf) | 32.01s | 0.911x | 81.1 |
| PREFETCHIT1 variant | 33.64s | 0.867x | 82.0 |
| lookahead-8 / lookahead-32 | 31.99 / 31.96s | 0.911x | 81.0 |

Lookahead distance changes NOTHING → the prefetches are not merely
mistimed, they are inert: at 79 MPKI (1 miss / 12 inst, IPC 0.40) demand
misses saturate the outstanding-miss resources and hardware drops SW
prefetch hints wholesale; what remains is the +6.6% instruction overhead.
PREFETCHIT1 is strictly worse than prefetcht1 (0.867x vs 0.911x) — first
real-workload head-to-head, confirms the microbenchmark-based choice.

Paper synthesis — the technique's operating window: SW code prefetch needs
(a) enough MPKI to matter, (b) concentrated/structured misses, (c) MSHR
headroom. clang/JVM-suite class fails (a); PostgreSQL/tomcat fail (b);
arcilator-at-79-MPKI fails (c); Verilator (58 MPKI, structured, headroom)
and Django sit in the goldilocks zone. arcilator remains valuable as the
saturation-regime datapoint and the second flattened-codegen workload.

## M2 (2026-08-17): density-controlled injection recovers arc — +4.5% pure

User insight validated: the failure was not raw MPKI saturation alone but
PREFETCH ISSUE DENSITY (arc calls every ~15 instr; blanket = hint-queue
overload). Ladder: Rocket 0.75MB→MPKI 1, LargeBoom 3.0MB→71, MegaBoom
4.5MB→74, DMB 8.7MB→79 (cliff at L2 capacity; no natural mid-MPKI design).
On MegaBoom (74): blanket t1 0.926x → stride-4 + lookahead-8 raw +2.4% →
**layout-controlled (same-binary NOP pairs, the mandatory protocol given
±4% layout luck): s4la8 1.0415x, s4la16 1.0449x peak**; la≥20 or lines=2
collapse (0.95-0.98) — sweet spot is narrow. Fifth axis for the paper:
prefetch issue density. Class-1 standing: Verilator 1.078x (≥5% ✓) +
arc density-recovery +4.5%; EDA CI farms as the datacenter deployment
frame.

## PGO-first enforcement + structural findings (2026-08-17)

Per user methodology (trace→PGO ceiling first; static evaluated against it):
- LBR+L2I precise trace pipeline works on arc (57k records, 74% COND).
- **Existing function-granularity planner is structurally inapplicable**:
  LLVM inlines 48,698 IR arc calls down to 113 real calls; misses live
  inside the 493k-line inlined TestHarness_clock body → targets=4,
  injections=0. The earlier +4.5% callsite result works through the 113
  surviving shared-arc calls.
- Block-lookahead via IR blockaddress = dead end: address-taken blocks
  inhibit block merge/layout (injected baseline 9.6s vs 9.3s uninjected)
  and break the NOP patcher. Correct home for intra-function lookahead is
  a backend/Machine pass (cf. C2 V4) — future work.
- C1-arc final: **callsite s4la16 +4.49% layout-controlled** stands;
  PGO ceiling for arc requires the backend-pass route.
- DSB (normal function-shaped services): standard planner applies —
  PGO-first order locked for the rebuild experiment.

## M3 (2026-08-17): C1 crosses 5% — s4la16 confirmed 1.051x

Round-2/3 neighbor grids (la14/18 neg, s3la16 neg, s5la16 +2.2%,
base-offset64 +1.3%, lb cells neutral-neg) confirm s4la16 is a sharp
resonance. Reference cell re-measured in-session: 1.0525 (5 reps), then
locked with 15 interleaved reps: **nop 5.712±0.025 vs pf 5.435±0.034 =
1.0510, distributions non-overlapping (min-gap 0.18s), MPKI 76.7→71.2.**
Class-1 members ≥5%: Verilator qsort 1.078x, arcilator MegaBoom 1.051x.
(dmb_s4la16 driver exits instantly — needs driver_dmb arg fix; bonus
cell only.)
