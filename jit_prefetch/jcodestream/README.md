# JCodeStream (JCS3): the JIT twin of the Verilator flattened-code profile

Synthetic-but-honest JVM benchmark demonstrating the pure prefetcht1 effect
in C2-compiled code. 9,000 static leaf methods (>325 bytecodes each so C2
never inlines them; 4 independent arithmetic chains for wide-ILP fetch
pressure), called in a FIXED GLOBAL SHUFFLE (Mid3) — statically
deterministic targets, layout-nonlocal order. ~16.7MB of C2 code walked
per repetition.

Steady profile (frozen 3.8GHz, core-pinned): L2I 93.2 MPKI, L1I 94.5
(L2-hit share 1% — full streaming), IPC 0.398 — passes all four axes
(MPKI, structure/static-determinism, FE-bound, L1I≈L2I).

Baseline flags (identical in every arm — workload definition, not tuning):
`-XX:-TieredCompilation -XX:CompileThreshold=100 -XX:CICompilerCount=16`
(pure C2, drains the 9,000-method compile queue in seconds).

## Result (5 reps, interleaved, idle machine, sd ≤ 0.32ms)

| config | iter (last-150 mean) | speedup | window L2I |
|---|---:|---:|---:|
| stock | 14.95 ± 0.05 ms | 1.0000x | 14.9 |
| V4 128B x 8 lines | 13.89 | 1.0768x | 10.1 |
| V4 128B x 16 | 11.85 | 1.2616x | 6.1 |
| **V4 128B x 32** | **11.63** | **1.2854x** | **4.7** |
| V4 256B x 16 | 11.84 | 1.2628x | 5.9 |
| V4+V2 | 11.88 | 1.2584x | 6.1 |

Textbook dose-response: lines -> MPKI -> time, monotone. V2/V3 alone are
neutral here (call-adjacent = zero lead); V4's entry-anchored self-burst
carries the entire win. **Pure prefetcht1 effect: +28.5%.**

## Robustness (JCS4)

Mixed method sizes (15-80 rounds) + data-dependent internal branches:
v4_128x16 1.2054x, **v4_128x32 1.2617x** (3 reps, sd<=0.14ms) - the win is
a property of the streaming structure, not of uniform straight-line code.

## Design pitfalls we hit (methodology notes)

1. Sequential call order -> the HW L2 streamer eats all misses (L2I 0.6).
   The shuffle is what defeats it; SW prefetch wins exactly where HW
   streaming fails: deterministic-but-nonlocal traversal.
2. Default tiered thresholds leave 9,000 big methods interpreted (83% of
   time in Interpreter, 129/9000 compiled): compile-queue drain must be
   part of warmup design.
3. Body must exceed FreqInlineSize (325 bc) or C2 inlining collapses the
   call graph.
