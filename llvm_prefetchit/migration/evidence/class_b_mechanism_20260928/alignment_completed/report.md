# Native IT0 positional calibration

Eight function offsets, four opcode policies, two repetitions: 64 fully scheduled trials after actual same-CPU blocking handoff. One dependency-delayed demand target from eight flushed candidate lines; same-address NOP control for each offset.

| Function offset | Predicted IT0 target positions | Eight IT0 retired L2/iteration | Only predicted IT0 slots | Predicted IT0 + remaining T1 |
|---|---|---:|---:|---:|
| 0 | 0, 4 | 0.65235 | 0.66178 | 0.03608 |
| 8 | 0, 3, 7 | 0.55218 | 0.56343 | 0.04118 |
| 16 | 0, 1, 6 | 0.53608 | 0.56395 | 0.05242 |
| 24 | 0, 5 | 0.64253 | 0.67738 | 0.04305 |
| 32 | 0, 4 | 0.66155 | 0.67788 | 0.04110 |
| 40 | 0, 3, 7 | 0.53610 | 0.54483 | 0.02725 |
| 48 | 0, 1, 6 | 0.52990 | 0.57427 | 0.03380 |
| 56 | 0, 5 | 0.64530 | 0.65582 | 0.03227 |

Across all 16 all-IT0 runs, the 40 predicted-position per-target means were at most 104.45 TSC ticks; the 88 remaining means were at least 229.96. These are aggregate target means, not individual latency bounds.

The observed pattern follows the first IT0 whose final byte lies in each 32-byte region. Retaining only those IT0 slots preserved broadly similar retired-miss behavior; making the remaining slots T1 removed most residual demand misses. This is a repeatable property of this calibration on this processor. It does not establish the internal queue structure, architectural acceptance rules, or production-code behavior.

No hint, target, or original instruction addresses move between opcode controls at one offset. Across offsets, the hint function moves within alignment padding while main and all demand targets retain their addresses. These synthetic measurements are not application E2E speedup.
