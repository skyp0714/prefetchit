# Native dependent-demand burst calibration

Eight possible target lines flushed per iteration; one target selected from the result of 512 dependent IMUL operations. Same-CPU blocking handoff. Three repeats per condition, 20,000 iterations per repeat; all 48 windows fully scheduled and every target return checked.

| Policy | Retired L2 / iteration | Speculative code-read misses / iteration | Target call TSC | Hint body + target TSC |
|---|---:|---:|---:|---:|
| nop | 0.87317 | 2.17732 | 316.73 | 1208.47 |
| it0_1 | 0.77855 | 2.86463 | 321.08 | 1205.45 |
| it0_2 | 0.76555 | 2.87072 | 316.60 | 1203.78 |
| it0_4 | 0.77590 | 2.86838 | 310.74 | 1196.85 |
| it0_8 | 0.65175 | 3.57237 | 298.13 | 1185.45 |
| t1_8 | 0.01963 | 1.29008 | 62.75 | 945.74 |
| it0_spaced8 | 0.13333 | 7.46603 | 93.03 | 975.86 |
| mixed_1it0_7t1 | 0.02932 | 2.10132 | 67.23 | 959.78 |

The contiguous eight-IT0 burst consistently accelerated target positions 0 and 4; the other positions retained long call times. This is a measured layout-dependent pattern, not proof of fetch-queue capacity or a guarantee of one accepted hint per fetch block. Spaced IT0 and the mixed burst cover more target positions.

The earlier fixed-target probe is retained separately: its NOP already hid almost all demand misses during the long lead. It cannot identify a useful burst width.

These timings exclude CLFLUSH and handoff, include serial timestamp overhead, and are not application E2E speedup. Full iteration CPU cycles can rise because seven prefetched targets are unused in this artificial one-of-eight workload and all eight targets are flushed again. Neither event count nor local target latency alone establishes service benefit.

The hint code is not explicitly flushed; kernel execution can still affect its residency. No direct fetch-queue or DSB occupancy is measured.
