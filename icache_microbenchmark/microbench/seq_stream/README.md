# seq_stream — stage-1 microbenchmark for software sequential instruction prefetch

Question: in a straight-line code stream that streams through L2 (the Verilator/arcilator
regime: MPKI 57–79, IPC 0.4–0.6), does `prefetcht1 D(%rip)` issued every S bytes turn the
L2I misses into hits, and what D and S work on the Xeon 6787P core?

`gen_seq_stream.py` emits one huge straight-line function (byte loads/stores/ALU on a small
state buffer) with a prefetch — or a same-length NOP for the control — every S bytes; options
add Verilator-like control flow (taken forward jumps, calls into 2,500 straight-line helper
functions of 800 B laid out in call order) and a streaming data buffer that thrashes L2.
`run_sweep.sh` (pure stream, 16 MB) and `run_vlike.sh` (12 MB + jumps + calls + 16 MB data)
measure sec/rep, L2I MPKI and IPC with `perf stat` on one pinned core (3.8 GHz frozen,
uncore pinned; 2026-09-16, other cores were compiling).

## Pure sequential stream (16 MB, code only)

| variant | speedup vs base | L2I MPKI | IPC |
|---|---:|---:|---:|
| base | 1.00x | 70.925 | 0.414 |
| nop_s64 | 1.00x | 72.823 | 0.428 |
| pf_d256_s64 | 1.49x | 17.939 | 0.596 |
| pf_d512_s64 | 2.11x | 2.301 | 0.823 |
| pf_d1024_s64 | 2.48x | 0.959 | 0.942 |
| pf_d2048_s64 | 2.99x | 0.333 | 1.108 |
| pf_d4096_s64 | 3.22x | 0.599 | 1.247 |
| pf_d8192_s64 | 3.56x | 1.091 | 1.385 |
| nop_s128 | 1.00x | 71.784 | 0.424 |
| pf_d256_s128 | 1.16x | 35.122 | 0.468 |
| pf_d512_s128 | 1.22x | 15.046 | 0.523 |
| pf_d1024_s128 | 1.61x | 5.428 | 0.674 |
| pf_d2048_s128 | 2.42x | 3.187 | 0.960 |
| pf_d4096_s128 | 3.17x | 6.102 | 1.261 |
| pf_d8192_s128 | 3.08x | 8.133 | 1.129 |
| nop_s256 | 1.00x | 71.475 | 0.411 |
| pf_d256_s256 | 1.00x | 68.257 | 0.415 |
| pf_d512_s256 | 1.18x | 29.889 | 0.491 |
| pf_d1024_s256 | 1.29x | 19.036 | 0.546 |
| pf_d2048_s256 | 1.88x | 15.712 | 0.770 |
| pf_d4096_s256 | 2.28x | 23.234 | 0.856 |
| pf_d8192_s256 | 2.28x | 24.342 | 0.827 |

- The hardware prefetchers do not hide a sequential *code* stream: base MPKI 71, IPC 0.41 —
  the same regime as Verilator (57 / 0.62). The NOP twin is identical to base.
- `prefetcht1 D(%rip)` every 64 B removes essentially all L2I misses; the gain grows with D
  up to 4–8 KB (3.3x). S=128 B is as good as 64 B at D=4 KB (adjacent-line/streamer help);
  S=256 B keeps ~2.2x.

## Verilator-like stream (12 MB main + jumps every 160 B + calls every 300 B into 800 B helpers + 16 MB data)

| variant | speedup vs base | L2I MPKI | IPC |
|---|---:|---:|---:|
| base | 1.00x | 60.651 | 0.507 |
| nop_s64_b4 | 0.98x | 64.246 | 0.486 |
| seq_d1024_s64 | 2.53x | 10.163 | 1.027 |
| seq_d1024_s128 | 2.23x | 17.531 | 0.936 |
| seq_d2048_s64 | 2.53x | 0.477 | 1.047 |
| seq_d2048_s128 | 2.38x | 2.836 | 0.985 |
| seq_d4096_s64 | 2.56x | 0.403 | 1.052 |
| seq_d4096_s128 | 2.35x | 3.491 | 0.997 |
| seq_d8192_s64 | 2.56x | 0.625 | 1.054 |
| seq_d8192_s128 | 2.33x | 3.662 | 0.992 |
| seqburst_d4096_s128_b4_l0 | 2.33x | 3.145 | 0.980 |
| seqburst_d4096_s128_b4_l256 | 2.31x | 4.404 | 0.948 |
| seqburst_d4096_s128_b4_l1024 | 2.35x | 2.961 | 0.988 |
| seqburst_d4096_s128_b8_l0 | 2.33x | 2.801 | 0.980 |
| seqburst_d4096_s128_b8_l256 | 2.34x | 2.434 | 0.980 |
| seqburst_d4096_s128_b8_l1024 | 2.34x | 2.441 | 0.985 |
| seqburst_d4096_s128_b13_l0 | 2.22x | 3.671 | 0.939 |
| seqburst_d4096_s128_b13_l256 | 2.27x | 4.024 | 0.929 |
| seqburst_d4096_s128_b13_l1024 | 2.28x | 2.611 | 0.956 |
| burst_only_b8_l256 | 1.76x | 20.579 | 0.791 |

- Base MPKI 61 / IPC 0.51 ≈ Verilator DualMegaBoom. Sequential lookahead alone gives 2.6x at
  D ≥ 1 KB; the helpers are covered because they are laid out in call order, so the
  callee's own `rip+D` prefetches reach the next callee (Verilator: 61% of consecutive
  nba_sequent callees are adjacent, 89% within 4 KB).
- A callee-entry burst (`prefetcht1 callee+64*l` before the call) adds nothing on top of
  seq here; alone it gives 1.75x (MPKI 20).

Consequence for stage 2: the static pass gets a plan-free "sequential lookahead" mode
(`-prefetchit-seq-distance`, `-prefetchit-seq-stride-insns`, plus `-prefetchit-callee-burst-lines`),
evaluated on Verilator in `llvm_prefetchit/results/static_overhaul_20260916/`.
