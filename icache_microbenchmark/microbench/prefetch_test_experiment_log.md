# prefetch_test latest experiment log

## 2026-05-05: process-level one-shot prefetch experiment

Goal:

- Avoid in-process `clflush` warming target translations.
- Measure each sample with a fresh `prefetch_test` process that executes the timed region once.
- Alternate `icache_flush_dummy` and `prefetch_test` so the measured process starts after a large executable-code footprint has run on the same CPU.

Implementation:

- Added `icache_flush_dummy`: pins to the requested CPU, generates a large executable NOP region, and executes it.
- Added `perf_once` mode to `prefetch_test`: one process performs exactly one prepared timed-region execution and reads latency/L2/L3/TLB counters from that same timed region.
- Added `run_process_prefetch_experiment.py`: wrapper that repeatedly runs `icache_flush_dummy` followed by one `prefetch_test perf_once` process.

Build:

```sh
make -C microbench/src prefetch_test icache_flush_dummy
```

The Makefile builds both binaries at `-O1`.

Command:

```sh
python3 microbench/src/run_process_prefetch_experiment.py \
  --reps 20 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays none,pause8,pause16,pause32,pause64,pause96,pause128,pause160,pause192,pause256,pause384,pause512 \
  --clear-result
```

Result files currently kept in `microbench/result`:

- `latest_process_raw.csv`
- `latest_process_summary.csv`
- `latest_process_best.csv`
- `latest_process_cycle_comparison.png`
- `latest_process_cache_miss_comparison.png`
- `latest_process_run.log`

Best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 20 | 1180 | 1194 | 1236 | 4 | 4 | 92 | 0 |
| advance execution | pause128 | 20 | 212 | 324 | 344 | 0 | 0 | 9 | 0 |
| data PREFETCHT0 | pause192 | 20 | 1002 | 1178 | 1228 | 4 | 1 | 82 | 0 |
| data PREFETCHT0 multiline | pause160 | 20 | 558 | 622 | 660 | 4 | 1 | 47 | 0 |
| data PREFETCHT1 | pause192 | 20 | 806 | 1152 | 1242 | 4 | 1 | 72 | 0 |
| data PREFETCHT1 multiline | pause384 | 20 | 534 | 610 | 682 | 4 | 1 | 46 | 0 |
| code PREFETCHIT0 | pause256 | 20 | 994 | 1074 | 1126 | 3 | 3 | 68 | 0 |
| code PREFETCHIT0 multiline | pause32 | 20 | 992 | 1062 | 1116 | 3 | 3 | 68 | 0 |
| code PREFETCHIT1 | pause16 | 20 | 966 | 1050 | 1168 | 3 | 3 | 67 | 0 |
| code PREFETCHIT1 multiline | pause32 | 20 | 1004 | 1068 | 1108 | 3 | 3 | 70 | 0 |

Interpretation:

- Process-level measurement fixed the earlier suspicious TLB signal: baseline now has nonzero iTLB/sTLB misses and much larger L2 code miss counts.
- L3 miss is still zero because the dummy is an instruction-cache/frontend pressure program, not an LLC eviction program. The target code appears to remain available below DRAM, likely in LLC or page cache-backed memory.
- Data prefetch multiline helps substantially: it cuts p50 from baseline 1180 cycles to roughly 534-558 cycles and reduces L2 code miss p50 from 92 to about 46-47.
- Code prefetch does not show the same benefit in this process-level setup. IT0/IT1 single and multiline all remain around 966-1004 cycles p50 with L2 code miss p50 around 67-70.
- With only three target pages, data prefetch appears to warm shared translation state enough to reduce page-walk count in the timed region (`sTLB miss p50` 1), while code prefetch still leaves about three code page walks in the timed region.

Next question:

If we need to see L3 miss behavior or stronger ITLB capacity effects, the next step is to expand the target footprint beyond three pages and/or add a separate LLC-eviction dummy before measurement.

## 2026-05-05: PREFETCHIT0 issuing-condition search

Goal:

- Add iTLB/sTLB miss visibility to the latest plots because L3 miss stays at zero in the process-level dummy setup.
- Try more ways to make `PREFETCHIT0` execute under frontend disruption: branch mispredict, indirect-call target mispredict, cold far calls without explicit `clflush`, path+target prefetch, and complex control flow.
- Separate two effects: whether the `PREFETCHIT0` hint can fetch code lines, and whether translation/page-walk state is already warm enough for the hint to be useful.

New strategy families:

- Pure code prefetch: `fair_code_prefetchit0_lines`, `fair_code_prefetchit0_branch_misp_lines`, `fair_code_prefetchit0_path_lines`, `fair_code_prefetchit0_path_indirect_call_lines`.
- Translation-primed code prefetch: `fair_code_prefetchit0_dtlb_prime_*`, which first uses one data prefetch per page to prime translation, then issues `PREFETCHIT0` line hints.
- Diagnostic combined case: `fair_code_prefetchit0_data_lines_then_it0_lines`, which uses full data-line prefetch followed by `PREFETCHIT0`; this is not a pure code-prefetch result, but shows whether IT0 can still add instruction-side benefit once translation/data-side cache state is warm.

Command:

```sh
python3 microbench/src/run_process_prefetch_experiment.py \
  --case-set it0search \
  --case-filter 'baseline,advance,data,forced lines,branch miss,path lines,path indirect,dtlb' \
  --reps 15 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays pause32,pause64,pause96,pause128,pause192,pause256,pause512,pause768,pause1024,pause1536,pause2048 \
  --clear-result
```

Latest plots:

- `microbench/result/latest_process_cycle_comparison.png`
- `microbench/result/latest_process_cache_miss_comparison.png` now plots L2 code miss, iTLB miss, and sTLB miss instead of an uninformative L3-only view.
- `microbench/result/latest_process_delay_latency.png`

Best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 15 | 1136 | 1154 | 1182 | 4 | 4 | 93 | 0 |
| advance execution | pause768 | 15 | 204 | 252 | 260 | 1 | 1 | 10 | 0 |
| data PREFETCHT0 | pause96 | 15 | 760 | 1118 | 1192 | 4 | 1 | 78 | 0 |
| data PREFETCHT0 multiline | pause1536 | 15 | 462 | 468 | 528 | 4 | 1 | 42 | 0 |
| data PREFETCHT1 | pause192 | 15 | 778 | 1104 | 1148 | 4 | 1 | 79 | 0 |
| data PREFETCHT1 multiline | pause96 | 15 | 504 | 528 | 582 | 4 | 1 | 50 | 0 |
| code PREFETCHIT0 forced lines | pause1024 | 15 | 1018 | 1046 | 1106 | 3 | 3 | 79 | 0 |
| code PREFETCHIT0 branch miss | pause1536 | 15 | 1010 | 1068 | 1100 | 3 | 3 | 73 | 0 |
| code PREFETCHIT0 path lines | pause64 | 15 | 998 | 1058 | 1164 | 3 | 3 | 75 | 0 |
| code PREFETCHIT0 path indirect | pause1024 | 15 | 1016 | 1054 | 1112 | 3 | 3 | 73 | 0 |
| code PREFETCHIT0 dtlb prime | pause2048 | 15 | 978 | 1044 | 1092 | 3 | 0 | 69 | 0 |
| code PREFETCHIT0 dtlb repeat | pause768 | 15 | 662 | 1022 | 1090 | 3 | 0 | 60 | 0 |
| code PREFETCHIT0 dtlb path repeat | pause192 | 15 | 674 | 996 | 1028 | 3 | 0 | 54 | 0 |
| code PREFETCHIT0 dtlb branch | pause1536 | 15 | 672 | 994 | 1036 | 3 | 0 | 52 | 0 |
| code PREFETCHIT0 dtlb indirect | pause192 | 15 | 668 | 994 | 1050 | 3 | 0 | 52 | 0 |
| data lines then IT0 | pause256 | 15 | 364 | 416 | 424 | 3 | 0 | 24 | 0 |

Interpretation:

- Pure `PREFETCHIT0` issuing-condition tricks only give a modest improvement over baseline. They reduce L2 code misses somewhat, but they still leave about three sTLB/page-walk misses in the timed region.
- Branch miss and indirect-call disruption do not by themselves unlock a data-prefetch-sized benefit. The best pure IT0 path in this confirmation run is around 998-1018 cycles p50 versus baseline 1136.
- When translation is primed first, sTLB walk p50 falls to zero. Repeated/path/branch IT0 variants then drop into the 662-674 cycle p50 range, but the tail remains high because L2 code misses are still around 52-60.
- Full data-line prefetch followed by IT0 reaches 364 cycles p50 and L2 code miss p50 24. This suggests IT0 can add instruction-side benefit once the data-side/translation state is already warm, but pure IT0 is not acting like a strong page-walk/TLB prefetcher in this setup.

## 2026-05-05: forcing PREFETCHIT issue attempts

Goal:

- Keep searching for a condition that makes `PREFETCHIT0/1` execute rather than be dropped.
- Specifically test `PREFETCHIT` immediately before a far function call, plus branch-mispredict and wrong-path forms that create a frontend window before the measured target code runs.

New forcing strategies tried:

- `PREFETCHIT -> cold far call`: `fair_code_prefetchit0_before_far_*`, `fair_code_prefetchit1_before_far_big`.
- `PREFETCHIT -> cpuid`: `fair_code_prefetchit0_cpuid_after_lines`.
- Repeated hints: `repeat16`, `repeat64`.
- Spaced hints: line-by-line `PREFETCHIT` separated by `pause`.
- Slow wrong-path branch: branch condition depends on flushed data, while the predicted fall-through path contains `PREFETCHIT`.
- Per-page wrong-path branches: separate slow branch windows for `bar`, `foo`, and `baz`.

Latest command:

```sh
python3 microbench/src/run_process_prefetch_experiment.py \
  --case-set it0search \
  --case-filter 'baseline,data T0 multiline,data T1 multiline,wrongpath data cpuid,wrongpath deep,wrongpath per page,forced lines,dtlb prime,data lines then IT0' \
  --reps 12 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays none,pause32,pause64,pause96,pause128,pause256,pause512,pause768,pause1024,pause1536,pause2048 \
  --cold-mode perf_once \
  --clear-result
```

Best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 12 | 1128 | 1184 | 1206 | 4 | 4 | 92 | 0 |
| data PREFETCHT0 multiline | pause2048 | 12 | 514 | 574 | 590 | 4 | 1 | 44 | 0 |
| data PREFETCHT1 multiline | none | 12 | 524 | 532 | 570 | 4 | 1 | 50 | 0 |
| code PREFETCHIT0 forced far-function lines | pause32 | 12 | 1016 | 1046 | 1054 | 3 | 3 | 69 | 0 |
| code PREFETCHIT0 dtlb-prime first | pause1536 | 12 | 724 | 1008 | 1018 | 3 | 0 | 58 | 0 |
| data lines then IT0 | pause768 | 12 | 402 | 434 | 440 | 3 | 0 | 25 | 0 |
| code PREFETCHIT0 slow wrong-path branch | pause1024 | 12 | 840 | 902 | 928 | 2 | 2 | 54 | 0 |
| code PREFETCHIT0 deep wrong-path repeat4 | pause768 | 12 | 842 | 870 | 908 | 2 | 2 | 59 | 0 |
| code PREFETCHIT0 per-page wrong-path branch | pause1024 | 12 | 842 | 890 | 920 | 2 | 2 | 55 | 0 |

Interpretation:

- `PREFETCHIT -> cold far call`, `PREFETCHIT -> cpuid`, repeated hints, and spaced hints do not make pure IT0/IT1 behave like data prefetch. They still leave about three sTLB page walks in the timed region.
- The slow wrong-path branch is the strongest pure-code-prefetch forcing condition so far. It reduces p50 from 1128 to about 840 cycles and reduces the TLB miss estimate from 4/4 to 2/2, with L2 code misses down to about 54.
- Splitting wrong-path prefetch by page did not improve beyond 2/2 TLB misses. That suggests the remaining misses are not just caused by one branch window being too short.
- `PREFETCHIT` clearly can reduce L2 code misses under some issue conditions, but these experiments still do not show it fully warming iTLB/sTLB the way data prefetch warms translation state.

## 2026-05-05: stable same-page PREFETCHIT issue condition

Goal:

- Remove the `data lines then IT0` diagnostic from active comparisons and keep searching for a real code-prefetch issuing condition.
- Avoid target-line warming from the code-page probe itself by moving the same-page probe/helper code from `target+0x240` to about `target+0x800`.
- Test whether executing `PREFETCHIT` from code located on the same 4KB target page, with per-line spacing, prevents the hint from being dropped.

New strategies:

- `fair_code_page_shape_spaced32_lines`: same target-page helper calls and pause spacing, but NOP shape instead of `PREFETCHIT`.
- `fair_code_page_prefetchit0_spaced128_lines`: target-page helper emits IT0 hints for `target+0..+0x200`, with 128 `pause` instructions between each line hint.
- `fair_code_page_prefetchit1_spaced32_lines`: target-page helper emits IT1 hints for the same lines, with 32 `pause` instructions between hints.

Command:

```sh
python3 microbench/src/run_process_prefetch_experiment.py \
  --case-set it0search \
  --case-filter 'baseline,advance execution,data T0 multiline,data T1 multiline,code page shape spaced32,code page IT0 spaced128,code page IT1 spaced32' \
  --reps 40 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays none,pause64,pause256,pause512,pause1024,pause2048 \
  --cold-mode perf_once \
  --clear-result
```

Latest best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 40 | 1082 | 1124 | 1240 | 4 | 4 | 88 | 0 |
| advance execution | pause64 | 40 | 260 | 262 | 266 | 0 | 0 | 10 | 0 |
| data PREFETCHT0 multiline | pause1024 | 40 | 554 | 588 | 606 | 4 | 1 | 48 | 0 |
| data PREFETCHT1 multiline | pause1024 | 40 | 550 | 596 | 674 | 4 | 1 | 49 | 0 |
| same-page NOP shape spaced32 | pause2048 | 40 | 860 | 894 | 972 | 0 | 0 | 62 | 0 |
| same-page PREFETCHIT0 spaced128 | pause64 | 40 | 422 | 472 | 484 | 0 | 0 | 33 | 0 |
| same-page PREFETCHIT1 spaced32 | pause64 | 40 | 424 | 462 | 476 | 0 | 0 | 29 | 0 |

Assembly check:

- Same-page helpers are placed inside the target pages. For example `bar=0x41d000`, `bar_page_prefetchit0_spaced128_lines=0x41dac0`, and `bar_page_prefetchit1_spaced32_lines=0x41dd40`.
- GNU objdump still decodes the new PREFETCHI opcode as `nop`, but the bytes are correct:
  - IT0 uses `0f 18 /7`, e.g. `0f 18 3d ... # 41d000 <bar>`.
  - IT1 uses `0f 18 /6`, e.g. `0f 18 35 ... # 41d000 <bar>`.
  - The target operands cover `bar/foo/baz + 0, 64, ..., 512`.

Interpretation:

- This is the first stable condition found where code prefetch beats data prefetch in this setup: IT0/IT1 same-page spaced helpers reach about 422-424 cycles p50 versus data multiline around 550 cycles.
- The same-page NOP shape still warms iTLB/sTLB by executing code on the target pages, but it remains much slower at 860 cycles p50. The additional drop to about 422 cycles is therefore attributable to the `PREFETCHIT` line hints rather than page execution alone.
- The required condition appears to be: execute the hint from an already fetched/executing code stream on the same target page, and give each line hint enough spacing for the frontend prefetch machinery to accept it. External far-call, branch-miss, and wrong-path approaches remained intermittent or weak by comparison.

## 2026-05-05: non-helper PREFETCHIT condition with fixed direct target calls

Goal:

- Stop treating same-page helper results as proof of `PREFETCHIT`, because executing helper code on the target page can warm target-page iTLB/STLB state by itself.
- Keep all three targets in the timed region, but remove indirect-call/order noise by adding `perf_once_fixed_targets_flush_targets`.
- Search non-helper issue conditions: repeated IT0 bursts, far cold-call windows, branch/far pressure, and different delay types.

Important code changes:

- Added `call_targets_fixed(seed)`, which times `bar -> foo -> baz` directly.
- Added `fixed_targets` cold mode; `perf_once_fixed_targets_flush_targets` runs one process per sample, flushes target code before prefetch, and times all three target functions once.
- Added non-helper IT0 variants:
  - `fair_code_prefetchit0_burst8_spaced32`
  - `fair_code_prefetchit0_before_far_cpuid_after`
  - `fair_code_prefetchit0_before_branch_misp_far`
  - `fair_code_prefetchit0_tlb_offset_call_window_burst4_post10`
- Added exact `--case-filter =strategy_name` matching in `run_process_prefetch_experiment.py` to avoid accidentally sweeping every IT0 case.

Final command:

```sh
sudo -E python3 microbench/src/run_process_prefetch_experiment.py \
  --case-set it0search \
  --case-filter '=baseline,=fair_advance_execution,=fair_data_prefetcht0_lines,=fair_data_prefetcht1_lines,=fair_code_prefetchit0_lines,=fair_code_prefetchit0_before_far_cpuid_after,=fair_code_prefetchit0_before_branch_misp_far,=fair_code_prefetchit0_burst8_spaced32,=fair_code_prefetchit0_tlb_offset_call_window_burst4_post10' \
  --reps 100 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays none,pause8192,complex_heavy,branch1024 \
  --cold-mode perf_once_fixed_targets_flush_targets \
  --clear-result
```

Latest best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 100 | 1780 | 2126 | 2324 | 5 | 1 | 74 | 44 |
| advance execution | complex_heavy | 100 | 156 | 158 | 208 | 0 | 0 | 0 | 0 |
| data PREFETCHT0 multiline | complex_heavy | 100 | 234 | 236 | 240 | 4 | 1 | 22 | 4 |
| data PREFETCHT1 multiline | none | 100 | 236 | 364 | 446 | 5 | 1 | 32 | 6 |
| code PREFETCHIT0 far forced lines | none | 100 | 1226 | 1512 | 1896 | 3 | 0 | 72 | 34 |
| code PREFETCHIT0 before far call | complex_heavy | 100 | 1208 | 1416 | 1810 | 3 | 0 | 63 | 32 |
| code PREFETCHIT0 before branch/far pressure | branch1024 | 100 | 1196 | 1424 | 1876 | 3 | 0 | 71 | 30 |
| code PREFETCHIT0 burst8 | pause8192 | 100 | 1252 | 1424 | 1788 | 5 | 0 | 72 | 33 |
| code PREFETCHIT0 TLB-offset call-window burst | none | 100 | 1230 | 1476 | 1810 | 6 | 0 | 70 | 33 |

Interpretation:

- This is the first non-helper condition with a stable few-hundred-cycle `PREFETCHIT` benefit. The best IT0 case improves p50 from 1780 to 1196 cycles, about 584 cycles.
- Unlike the same-page helper result, these strategies do not execute code on the target pages before the timed region. The timed region still executes all three targets.
- The strongest condition is not just "more burst." It combines a frontend-disrupting setup with enough post-prefetch window:
  - `fair_code_prefetchit0_before_branch_misp_far` + `branch1024` delay: best p50.
  - `fair_code_prefetchit0_before_far_cpuid_after` + `complex_heavy` delay: best L2-code-miss reduction among IT0 cases.
- Data prefetch is still much stronger for full line fill: data T0/T1 reach about 234-236 cycles and L3 miss p50 around 4-6.
- The non-helper IT0 evidence is nevertheless now clear: p50 improves by about 570-580 cycles, sTLB misses disappear, L2 code misses drop, and L3 misses drop from 44 to about 30-32.

Follow-up final validation:

- A broader fixed-direct search found that several non-helper IT0 shapes are similar once noise is reduced.
- The final `latest_*` files were regenerated with `reps=100`, `perf_once_fixed_targets_flush_targets`, and exact-case filtering.

Final latest best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 100 | 1736 | 1920 | 2230 | 5 | 1 | 74 | 44 |
| advance execution | complex_heavy | 100 | 156 | 158 | 162 | 0 | 0 | 0 | 0 |
| data PREFETCHT0 multiline | pause8192 | 100 | 232 | 236 | 242 | 5 | 1 | 28 | 4 |
| data PREFETCHT1 multiline | branch1024 | 100 | 236 | 436 | 464 | 7 | 1 | 32 | 6 |
| code PREFETCHIT0 forced lines | complex_heavy | 100 | 1220 | 1460 | 1706 | 3 | 0 | 66 | 33 |
| code PREFETCHIT0 before far big | branch1024 | 100 | 1220 | 1386 | 1704 | 6 | 0 | 67 | 31 |
| code PREFETCHIT0 before far call + cpuid after | complex_heavy | 100 | 1216 | 1416 | 1764 | 3 | 0 | 64 | 34 |
| code PREFETCHIT0 before branch/far pressure | branch1024 | 100 | 1216 | 1408 | 1898 | 5 | 0 | 71 | 34 |
| code PREFETCHIT0 spaced32 + cpuid after | branch1024 | 100 | 1252 | 1416 | 1864 | 5 | 0 | 69 | 32 |
| code PREFETCHIT0 burst4 | arith2048 | 100 | 1202 | 1390 | 1700 | 5 | 0 | 70 | 32 |
| code PREFETCHIT0 TLB-offset far burst8 | arith2048 | 100 | 1204 | 1414 | 1696 | 3 | 0 | 69 | 32 |

Final interpretation:

- The best stable non-helper condition is now `fair_code_prefetchit0_burst4_spaced32` with `arith2048`: p50 improves from 1736 to 1202 cycles, a 534-cycle gain.
- `fair_code_prefetchit0_tlb_offset_far_burst8_spaced32` is nearly identical at 1204 cycles and has the best p95 among IT0 cases.
- The effect remains well below data prefetch and advance execution, but it is no longer a tiny/intermittent signal: sTLB misses are eliminated, L3 miss p50 drops from 44 to 31-34, and p50 latency drops by about 500 cycles across multiple IT0 shapes.

## 2026-05-06: best-only final plot and generic iTLB accounting

Goal:

- Keep searching for a condition where code prefetch beats data `PREFETCHT0`.
- Also require frontend TLB misses to disappear.
- Regenerate plots with only the best code-prefetch case, not every attempted shape.

Additional attempts:

- Added fixed timed-path IT0 variants that prefetch `call_targets_fixed`, `call_measured_targets`, and the three target pages.
- Added inline pointer-chase wrong-path variants so the branch could be predicted before a long data dependency resolved.
- Re-tested no-internal-`clflush` and no-dummy-flush modes as sanity checks.

Outcome of non-helper attempts:

- Fixed-path and inline-chase variants did not beat data `PREFETCHT0`.
- Best non-helper variants still stayed around 1100-1600 cycles p50 under `perf_once_fixed_targets_flush_targets`.
- The same-page IT0 helper remains the only condition found so far that beats data `PREFETCHT0` in this benchmark shape. This is an upper-bound style case because executing the helper on the target page can itself warm frontend translation/cache state.

Perf accounting change:

- `itlb_miss_p50` now uses generic `iTLB-load-misses`.
- `stlb_miss_p50` uses `itlb_misses.walk_completed`, i.e. completed page walks after an sTLB miss.
- The older raw `ITLB_MISSES.STLB_HIT + WALK_COMPLETED` estimate was too conservative for the user-facing "iTLB/sTLB miss" columns.

Final command:

```sh
sudo -E python3 microbench/src/run_process_prefetch_experiment.py \
  --result-dir microbench/result \
  --case-set it0search \
  --case-filter '=baseline,=fair_advance_execution,=fair_data_prefetcht0_lines,=fair_code_page_prefetchit0_spaced32_lines' \
  --reps 100 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays none,pause64,pause512,pause2048,pause8192,arith2048,branch1024,complex_heavy,chase256 \
  --cold-mode perf_once_fixed_targets_flush_targets \
  --clear-result
```

Latest best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 100 | 1822 | 2048 | 2302 | 1 | 1 | 77 | 45 |
| advance execution | branch1024 | 100 | 158 | 158 | 162 | 0 | 0 | 8 | 0 |
| data PREFETCHT0 multiline | complex_heavy | 100 | 236 | 240 | 242 | 1 | 1 | 21 | 4 |
| same-page PREFETCHIT0 spaced32 | complex_heavy | 100 | 212 | 218 | 218 | 0 | 0 | 20 | 0 |

Final interpretation:

- The best-only plot now shows only baseline, advance execution, data `PREFETCHT0`, and the best IT0 case.
- Best IT0 p50 is 212 cycles, beating data `PREFETCHT0` p50 236 cycles by 24 cycles.
- Generic iTLB and sTLB misses are both 0 for the best IT0 case.
- Because the winning case is same-page, it should be treated as an upper-bound condition rather than clean proof that a non-helper `PREFETCHIT` independently warmed the iTLB.

## 2026-05-06: helper excluded, non-helper search continued

Correction:

- The same-page helper result is excluded from the current plots and should not be used as proof that non-helper `PREFETCHIT` executed. Executing helper code on the target pages can warm target-page frontend state by itself.
- The current final `microbench/result/latest_*` files contain only baseline, advance execution, data `PREFETCHT0`, and the best non-helper IT0 case.

Additional non-helper attempts:

- Added far-code TLB-miss functions on separate 64KB-aligned pages and tested `PREFETCHIT; PREFETCHIT; far call; far call`.
- Made the far-code TLB miss stronger with `mprotect(PROT_NONE) -> mprotect(PROT_READ|PROT_EXEC)` on the far pages.
- Split far calls into A/B before `PREFETCHIT` and C/D after `PREFETCHIT`.
- Put `PREFETCHIT` in a far prefetch function and executed that function after flushing/shooting down its own code page.
- Re-tested branch wrong-path, slow control-flow, pointer-chase, target-page-offset, adjacent-page, and two-phase `PREFETCHIT` variants.
- Earlier JIT/register-address forms are not used in the current source; later tests keep JIT excluded.

Latest final command:

```sh
sudo -E python3 microbench/src/run_process_prefetch_experiment.py \
  --result-dir microbench/result \
  --case-set it0search \
  --case-filter '=baseline,=fair_advance_execution,=fair_data_prefetcht0_lines,=fair_code_prefetchit0_p2_far_tlb2' \
  --reps 100 \
  --dummy-kib 8192 \
  --dummy-passes 1 \
  --delays none,pause64,pause512,pause2048,pause8192,arith2048,branch1024,complex_heavy,chase256 \
  --cold-mode perf_once_fixed_targets_flush_targets \
  --clear-result
```

Latest helper-free best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline, no prefetch | none | 100 | 1942 | 2208 | 2426 | 1 | 1 | 86 | 46 |
| advance execution | arith2048 | 100 | 158 | 162 | 162 | 0 | 0 | 8 | 0 |
| data PREFETCHT0 multiline | arith2048 | 100 | 236 | 238 | 242 | 1 | 1 | 25 | 5 |
| non-helper code PREFETCHIT0 P/P + far TLB calls | none | 100 | 1320 | 1480 | 1884 | 0 | 0 | 72 | 36 |

Interpretation:

- The best helper-free IT0 case eliminates iTLB/sTLB misses, so `PREFETCHIT` or the surrounding far-call setup is affecting translation state.
- It still does not show data-prefetch-like code-line fill: L2 code miss p50 remains 72 versus data `PREFETCHT0` at 25.
- Under the current `flush, prefetch, delay, timed fixed foo/bar/baz` shape, helper-free IT0 remains much slower than data `PREFETCHT0` despite many issue-window attempts.

## 2026-05-06: strong TLB-cold branch search, helper/JIT excluded

Correction to the older notes:

- JIT variants were removed from the current source and are not part of this round.
- Same-page helper/page-prime cases are excluded from the interpretation because executing helper code on a target page can warm target-page frontend/TLB state by itself.
- The current TLB-cold baseline uses `perf_once_fixed_targets_flush_targets_shootdown_targets_measure_serial`, which flushes target code, performs target-page TLB shootdown with `mprotect`, and serializes before the timed region.

TLB-cold sanity matrix:

| cold mode | p50 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixed targets + serial | 656 | 8 | 6 | 42 | 0 |
| fixed targets + flush targets + serial | 1676 | 2 | 2 | 81 | 27 |
| fixed targets + shootdown targets + serial | 738 | 5 | 4 | 67 | 0 |
| fixed targets + flush + shootdown + serial | 1724 | 6 | 6 | 56 | 25 |

Strong TLB-cold branch tests:

| case | best delay | p50 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | none | 1662-1928 | 3 | 3 | 76-86 | 41-44 |
| data `PREFETCHT0` multiline | best of tested delays | 226-228 | 0 | 0 | 27-31 | 4-6 |
| code IT0 fixed P/P + strong far | best of tested delays | 1438-1460 | 3 | 3 | 63-76 | 36-39 |
| code IT0 nested branch/window | best of tested delays | 1614-1754 | 3 | 3 | 69-82 | 43 |
| code IT0 branch actual path | best of tested delays | 1724-1754 | 3 | 3 | 76-82 | 43 |
| code IT0 far branch actual | best of tested delays | 1346-1420 | 3 | 3 | 64-69 | 35-37 |
| code IT0 branch-to-farpath | best of tested delays | 1710-1776 | 3 | 3 | 78-84 | 43-45 |

TLB-gate diagnostic without target TLB shootdown:

| case | best delay | p50 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | none | 1484 | 0 | 0 | 83 | 39 |
| data `PREFETCHT0` multiline | spin100k | 228 | 0 | 0 | 29 | 6 |
| code IT0 fixed P/P + strong far | pause32768 | 1248 | 0 | 0 | 61 | 30 |
| code IT0 branch actual | branch8192 | 1260 | 0 | 0 | 63 | 30 |
| code IT0 branch farpath | spin100k | 1310 | 0 | 0 | 67 | 29 |

Current interpretation:

- The TLB issue is now reproducible: strong cold baseline shows target translation misses, while `flush_targets` without shootdown does not.
- Branch redirection, nested branches, and far branch targets do not make IT0 warm target translation under strong TLB-cold conditions; iTLB/sTLB miss p50 stays at 3/3.
- IT0 gives a moderate cache-line benefit when target TLB is already warm or not forcibly shot down, but it remains far from data `PREFETCHT0`.
- The clean current hypothesis is that on this CPU, `PREFETCHIT` is still treated as a hint that can be dropped on cold target translation; data `PREFETCHT0` can trigger data-side translation/page-walk state and therefore reaches the target code lines much more reliably.

## 2026-05-06: interleaved round schedule correction

Correction:

- The older process wrapper randomized all jobs within each repetition. Every sample still had a flush dummy before it, but baseline/T0/IT0/actual were not measured in a fixed adjacent sequence.
- The wrapper now defaults to `--schedule round`, which runs each repetition as:
  `flush -> baseline -> flush -> data T0 -> flush -> code IT0 -> flush -> advance execution -> flush`.
- Added `case_set=core` so the case order is exactly baseline, data T0 multiline, non-helper code IT0, advance execution.
- The raw CSV now includes `slot`, making the within-repetition order auditable.

Latest command:

```sh
sudo -E python3 microbench/src/run_process_prefetch_experiment.py \
  --result-dir microbench/result \
  --case-set core \
  --reps 24 \
  --dummy-kib 32768 \
  --dummy-passes 2 \
  --delays pause8192,pause32768,pause65536,arith8192,arith32768,branch8192,spin100k \
  --cold-mode perf_once_fixed_targets_flush_targets_shootdown_targets_measure_serial \
  --schedule round \
  --clear-result
```

Latest best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | spin100k | 24 | 1664 | 1864 | 2026 | 3 | 3 | 77 | 44 |
| data `PREFETCHT0` multiline | pause8192 | 24 | 228 | 234 | 334 | 0 | 0 | 29 | 4 |
| code `PREFETCHIT0` fixed P/P + strong far | branch8192 | 24 | 1506 | 1704 | 2062 | 3 | 3 | 69 | 37 |
| advance execution | spin100k | 24 | 162 | 162 | 162 | 0 | 0 | 9 | 0 |

Same-delay interpretation:

- The round schedule confirms the earlier direction under a cleaner ordering.
- Data `PREFETCHT0` remains close to 228-232 cycles for all tested delays and clears iTLB/sTLB misses.
- Non-helper code `PREFETCHIT0` improves over same-delay baseline in some rows, best at `branch8192` with 1506 cycles versus baseline 1764 cycles, but iTLB/sTLB miss p50 remains 3/3.
- Therefore the interleaved run still supports the translation-drop interpretation for IT0 under strong target TLB coldness.

## 2026-05-06: O0 cpuid/far-function retry and T0 TLB explanation

Changes:

- Added `prefetch_test_o0`, built with `-O0 -march=graniterapids -m64 -no-pie -fno-plt -mprefetchi`.
- Added prepare-region counters:
  - `prep_itlb_walk_p50`: `ITLB_MISSES.WALK_COMPLETED` during `prepare_measurement`.
  - `prep_dtlb_walk_p50`: `DTLB_LOAD_MISSES.WALK_COMPLETED` during `prepare_measurement`.
- Added new IT0 cpuid/far combinations:
  - `fair_code_prefetchit0_cpuid_p2_cpuid_far`
  - `fair_code_prefetchit0_cpuid_p2_far_cpuid`
  - `fair_code_prefetchit0_far_cpuid_p2_far`
  - `fair_code_prefetchit0_cpuid_far_p2_far_cpuid`

Latest command:

```sh
sudo -E python3 microbench/src/run_process_prefetch_experiment.py \
  --prefetch-bin microbench/src/prefetch_test_o0 \
  --result-dir microbench/result \
  --case-set cpuidfar \
  --reps 24 \
  --dummy-kib 32768 \
  --dummy-passes 2 \
  --delays pause8192,pause32768,branch8192,spin100k \
  --cold-mode prep_perf_once_fixed_targets_flush_targets_shootdown_targets_measure_serial \
  --schedule round \
  --clear-result
```

Latest O0 best-delay summary:

| case | best delay | samples | p50 cycles | p75 cycles | p95 cycles | iTLB miss p50 | sTLB miss p50 | L2 code miss p50 | L3 miss p50 | prep iTLB walk p50 | prep DTLB walk p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | spin100k | 24 | 1892 | 2090 | 2312 | 3 | 3 | 68 | 44 | 5 | 1 |
| data `PREFETCHT0` multiline | branch8192 | 24 | 280 | 280 | 284 | 0 | 0 | 27 | 5 | 6 | 4 |
| code IT0 P/P far cpuid | pause32768 | 24 | 1720 | 1978 | 2108 | 3 | 3 | 66 | 44 | 7 | 1 |
| code IT0 P/P strong far | pause32768 | 24 | 1582 | 1878 | 2276 | 2 | 2 | 61 | 30 | 9 | 1 |
| code IT0 fixed P/P strong far | pause32768 | 24 | 1500 | 1792 | 2024 | 2 | 2 | 47 | 30 | 11 | 1 |
| code IT0 cpuid-P/P-cpuid-far | branch8192 | 24 | 1528 | 1898 | 2230 | 2 | 2 | 57 | 30 | 10 | 1 |
| code IT0 cpuid-P/P-far-cpuid | pause8192 | 24 | 1572 | 1840 | 2160 | 3 | 3 | 58 | 30 | 10 | 1 |
| code IT0 far-cpuid-P/P-far | spin100k | 24 | 1582 | 1930 | 2120 | 2 | 2 | 68 | 30 | 12 | 1 |
| code IT0 cpuid-far-P/P-far-cpuid | pause32768 | 24 | 1552 | 1988 | 2270 | 2 | 2 | 62 | 30 | 12 | 1 |
| advance execution | spin100k | 24 | 194 | 198 | 200 | 0 | 0 | 5 | 0 | 9 | 1 |

Interpretation:

- T0's timed iTLB miss count being 0 is explained by prepare-region data-side page walks: data `PREFETCHT0` has `prep_dtlb_walk_p50=4`, while baseline and IT0 variants stay at `1`.
- Those extra data-side walks happen before the timed region and cover the target code pages, so the timed instruction fetch sees no completed code page walks.
- O0 and the new cpuid/far combinations improve IT0 somewhat versus baseline, but the best clean IT0 still leaves 2/2 timed iTLB/sTLB misses and remains far slower than data T0.

## 2026-05-07: conditional-branch window search

Changes:

- Added prepare-region `branch-misses` counting as `prep_branch_miss_p50`.
- Added conditional branch-window variants around `PREFETCHIT0`:
  - near target/fall-through/wrong-path offsets `o0..o16`
  - slow dependent-load branch windows with offset `o0..o8`
  - far-aligned branch target blocks
  - prefetch-before-far-branch windows
  - multi-branch far-storm windows
  - both-path windows where wrong-path and recovery-path both contain prefetch
- Added same-window `PREFETCHT0` controls and a `bar_only` measurement mode.

Key observations:

| test | p50 cycles | iTLB/sTLB p50 | L2 code miss p50 | L3 miss p50 | prep branch miss p50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3-target baseline | ~1850-2000 | 3/3 | ~68-79 | ~44-46 | ~30 |
| 3-target data T0 in same branch windows | ~278-280 | 0/0 | ~25-29 | 0-7 | ~56-60 |
| 3-target IT0/IT1 branch windows | ~1900-2000 | 3/3 | ~68-81 | ~44-46 | ~39-59 |
| bar-only baseline | 480 | 1/1 | 33 | 14 | 33 |
| bar-only branch-storm no-prefetch control | 468 | 1/1 | 31 | 14 | 62 |
| bar-only IT0 branch-storm | 480 | 1/1 | 32 | 16 | 61 |
| bar-only data T0 branch-storm | 116 | 0/0 | 19 | 0 | 61 |

Interpretation:

- The branch-window machinery is definitely producing branch misses; `prep_branch_miss_p50` rises from about 30 to 56-62 in the storm variants.
- The exact same windows execute data prefetch successfully: latency collapses to ~116 cycles for bar-only and ~280 cycles for three targets, with timed iTLB/sTLB and L3 misses removed.
- IT0/IT1 do not show a corresponding counter movement. The small bar-only improvement seen before adding the no-prefetch control was reproduced by the no-prefetch branch-storm shape, so it is not attributable to `PREFETCHIT`.
- Current evidence says these conditional branch-mispredict windows are not sufficient to make `PREFETCHIT0/1` warm the target code lines or target iTLB entries on this Xeon 6787P setup.
