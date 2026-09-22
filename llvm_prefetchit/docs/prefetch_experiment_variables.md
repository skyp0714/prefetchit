# Prefetch Sweep Variable Reference

This document defines the variables used in the Verilator prefetch experiments. The goal is to make each experiment name and result row interpretable without having to inspect the scripts.

## High-Level Experiment Goal

| Concept | Meaning |
|---|---|
| Baseline binary | Original Verilator simulator binary built with debug symbols and without the prefetch LLVM pass. |
| Optimized binary | Verilator simulator binary rebuilt with the LLVM prefetch pass enabled. |
| Miss target | The sampled instruction-side miss address from PEBS/LBR profiling, normalized mainly as a symbol+offset/cacheline target. |
| Injection site | A branch-history location from LBR used as the program point where the LLVM pass inserts a prefetch instruction. |
| Main objective | Minimize execution time while also tracking L1I MPKI, L2I MPKI, dynamic instruction count, and validation correctness. |
| Current workload | `verilator-qsort` with `MAX_CYCLES=538240`, unless stated otherwise. |

## Instruction Kind

| Variable | Example values | Meaning | Why it matters |
|---|---|---|---|
| `prefetch_mnemonic` | `prefetcht1`, `prefetchit1` | The actual instruction mnemonic emitted by the LLVM pass. | This is the primary comparison between data-prefetching an instruction address and using the x86 instruction-prefetch hint. |
| `PREFETCH_LABEL` | `prefetcht1`, `prefetchit1` | The label used for output directories, binary names, profiles, and summaries. | Keeps same-site experiments separate even when the target/site plan structure is otherwise identical. |
| `prefetcht1` | N/A | Data prefetch hint with temporal locality level 1. In this experiment it is pointed at instruction addresses. | Empirically strongest so far. It can fetch the target cacheline through the data-prefetch machinery, which may still help the unified lower-level cache path. |
| `prefetchit1` | N/A | Instruction prefetch hint. | The architecturally more direct code-prefetch instruction, but current measured benefit is smaller. The new sweep tests whether it only needs fewer/more carefully chosen insertions. |

## Target Selection Variables

| Variable | Example values | Meaning | Selection effect |
|---|---|---|---|
| `target_coverage_pct` | `5`, `10`, `25`, `50`, `75`, `100` | Select hot miss targets until their cumulative sample count reaches this percentage of all aggregated samples. | Higher values cover more sampled misses but select more target cachelines and usually produce more prefetches. |
| `top_k` | `2000`, `5000`, `999999` | Hard cap on the number of selected targets. | In current coverage-based sweeps this is usually `999999`, so `target_coverage_pct` is the actual limiter. |
| `allow_unresolved_targets` | `0`, `1` | Keep targets even if source line is unresolved, as long as symbol/offset/cacheline can be resolved. | Important for generated Verilator code because many hot addresses map to `??:0` even though symbol+offset is valid. |
| Trace aggregation count | `1`, `3` traces | Number of independent PEBS/LBR trace captures merged before target selection. | Reduces single-trace sampling bias. Current better plans use aggregated traces. |
| Target key | symbol+offset/cacheline | The stable identity used for target matching. | More reliable than `function:line` for generated Verilator C++ because debug line metadata is often incomplete. |

## Injection Site Selection Variables

| Variable | Example values | Meaning | When it is useful |
|---|---|---|---|
| `selection_mode=top-sites` | `top-sites` | For each selected target, rank candidate LBR branch sites by sample count and keep the hottest sites up to `site_budget`. | Best stable default so far. It avoids inserting at every rare path. |
| `selection_mode=all-paths` | `all-paths` | Keep every observed candidate branch site for each selected target within the selected depth window. | Maximum path coverage, but high over-injection risk. Useful for stress testing. |
| `selection_mode=per-depth` | `per-depth` | Select candidate sites independently for each LBR depth. `sites_per_depth` controls how many per depth. | Tests whether preserving depth diversity helps timing. Can quickly multiply the number of inserted prefetches. |
| `selection_mode=greedy` | `greedy` | Treat each site as covering a set of samples and greedily pick sites that cover the most remaining samples under the budget. | Intended to maximize coverage per inserted instruction. Still experimental because one greedy run had weaker srcline/function validation despite exact address/cacheline validation. |
| `site_budget` | `1`, `2`, `4`, `8`, `16`, `0` | Maximum selected injection sites per target for modes such as `top-sites` and `greedy`. `0` means unbounded for `all-paths`. | Higher budget covers more paths but increases static and dynamic prefetch instruction count. |
| `sites_per_depth` | `1`, `3` | Number of selected sites per LBR depth in `per-depth` mode. | A direct knob for depth diversity in the selected sites. |
| `candidate_pool` | `10000` | Candidate pool size considered by greedy selection. | Limits greedy search cost and candidate breadth. |

## LBR Depth and Timing Variables

| Variable | Example values | Meaning | Important clarification |
|---|---|---|---|
| `depth_min` | `1`, `2`, `4`, `8`, `16` | Closest allowed LBR depth used as an injection-site candidate. Lower depth is closer to the miss. | `depth_min=4` starts from LBR[4], not LBR[0]. |
| `depth` | `8`, `16`, `24`, `32` | Farthest allowed LBR depth used as an injection-site candidate. | `depth_min=4, depth=24` means candidates may come from LBR[4] through LBR[24]. |
| Depth window | `d4_16`, `d4_24`, `d1_32` | Shorthand for inclusive LBR depth range. | The planner does not blindly insert at every depth. It first forms candidates from this range, then `selection_mode` and budget choose final sites. |
| `branch_depth_policy` | `CALL:2-8,COND:4-16,RET:8-24` | Optional branch-type-specific depth window. | Allows different timing for calls, returns, conditional branches, indirect branches, etc. |
| Single-depth experiment | `d4_4`, `d8_8` | Candidate sites restricted to exactly one LBR depth. | Not yet run as a complete controlled sweep. Existing evidence does not prove that a wide window is always better. |

## Branch Type Semantics

| Branch type | Meaning | Expected prefetch timing implication |
|---|---|---|
| `CALL` | Direct function call. | Often a good prefetch point if the target miss is in or after the callee path. Usually needs shorter lead distance. |
| `IND_CALL` | Indirect function call. | Similar to `CALL`, but target/path may be less stable. |
| `RET` | Function return. | Can represent path transitions back to caller code. Often needs a farther depth window because the miss may happen after returning through several frames/paths. |
| `COND` | Conditional branch. | Captures path-dependent control flow. Good for hot path-specific prefetches if the same branch outcome tends to lead to the target. |
| `UNCOND` | Direct unconditional branch/jump. | Captures layout/control transfer points with deterministic direction. |
| `IND` | Indirect branch/jump. | Potentially useful but less predictable; often benefits from careful filtering. |

## Prefetch Target Address Variables

| Variable | Example values | Meaning | Why it matters |
|---|---|---|---|
| `prefetch_byte_offsets` | `0`, `0,64`, `0,64,128`, `0,64,128,192` | Extra byte offsets added to the target address. Each offset emits a separate prefetch instruction. | Instruction fetch often continues into the next cacheline. `0,64` means prefetch the target cacheline and the next 64-byte cacheline. |
| `o1` | `0` | One prefetch per selected site/target: exact target cacheline. | Lower overhead, useful for `prefetchit1` sparse sweep. |
| `o2` | `0,64` | Two prefetches: target cacheline and next cacheline. | Best `prefetcht1` tradeoff so far. |
| `o3` | `0,64,128` | Three adjacent cachelines. | More coverage but higher instruction overhead. |
| `o4` | `0,64,128,192` | Four adjacent cachelines. | Aggressive; often risks over-injection. |
| Cacheline size assumption | `64B` | Offsets are expressed in bytes and assume 64-byte instruction/cache lines. | Validation checks target exact address and 64B cacheline match. |
| `operand_mode` | `pc-relative-symbol-offset` | LLVM pass emits an inline asm operand based on `symbol + offset`; final assembly resolves the address PC-relatively. | Fixes the earlier manual-insertion issue where relative PC math could point at the wrong address. |

## Measurement and Build Controls

| Variable | Example values | Meaning | Notes |
|---|---|---|---|
| `MAX_CYCLES` | `538240` | Verilator workload cycle limit for qsort. | Kept constant for current comparisons. |
| `PROFILE_CORE` | `0` | CPU core used for task-pinned simulator execution during profiling. | Avoids cross-core migration noise. |
| `perf-scope` | `task` | `perf stat` counts the measured simulator process rather than the whole machine/core. | Reduces contamination from unrelated work. |
| `PROFILE_ITERATIONS` | `1`, `3`, `5` | Number of repetitions for detailed profile. | Screening uses fewer iterations; final comparisons use more. |
| `SCREEN_ITERATIONS` | `1` | Fast sweep iteration count. | Used for `prefetchit1` large sweep because we only need approximate minimum runtime first. |
| `CONFIRM_ITERATIONS` | `3`, `5` | Re-run count for the current best variant. | Used to reduce noise before trusting a selected best. |
| `PARALLEL_BUILDS` | `4`, `6` | Number of variants built concurrently. | Build can be parallelized; measurement should remain sequential to avoid LLC contention. |
| `BUILD_JOBS` | `8`, `16`, `32` | `make -j` jobs per variant build. | Higher values build faster but increase memory/disk pressure. |
| `RUN_PROFILE` | `0`, `1` | Whether the eval script profiles after building and validating. | Build-only mode is used for parallel build phases. |
| `RUN_TRACE` | `0`, `1` | Whether to collect residual PEBS/LBR traces after evaluation. | Disabled in fast sweeps. |
| `CLEAN_WORKDIR` | `0`, `1` | Delete copied Verilator work directory after binary generation. | Important for disk space; final binary, plan, logs, validation, and profiles remain. |

## Output and Validation Fields

| Field | Meaning | How to read it |
|---|---|---|
| `planned_injections` | Number of logical plan entries selected before LLVM/codegen. | One plan entry can produce multiple emitted instructions if multiple offsets are used. |
| `pass_injected` | Number of inline asm prefetch insertions reported by the LLVM pass. | Should be positive and generally close to expected plan expansion. |
| `asm_prefetch` | Number of final prefetch instructions found in disassembly. | Can exceed `pass_injected` if compiler/codegen clones code. |
| `target exact addr matches` | Assembly target address exactly matches planned target address. | Strongest correctness check for target addressing. |
| `target 64B cacheline matches` | Assembly target and planned target are in the same 64B cacheline. | Main correctness criterion for cacheline prefetching. |
| `elapsed_delta_pct` | Runtime change vs baseline. Negative is faster. | Primary objective for final ranking. |
| `l2i_mpki_delta_pct` | L2 instruction miss MPKI change vs baseline. Negative is fewer misses per kilo-instruction. | Useful but not sufficient; runtime can worsen if dynamic instruction count grows too much. |
| `instructions_delta_pct` | Dynamic instruction count change vs baseline. | Indicates overhead from inserted prefetches and changed codegen. |

## Variant Name Cheat Sheet

| Name fragment | Meaning |
|---|---|
| `cov50` | Select targets covering 50% of aggregated miss samples. |
| `tops` | `selection_mode=top-sites`. |
| `allpaths` | `selection_mode=all-paths`. |
| `perdepth` | `selection_mode=per-depth`. |
| `greedy` | `selection_mode=greedy`. |
| `bp` | Branch-depth policy enabled. |
| `d4_24` | Candidate LBR depth window is 4 through 24 inclusive. |
| `b8` | `site_budget=8`. |
| `o1` | `prefetch_byte_offsets=0`. |
| `o2` | `prefetch_byte_offsets=0,64`. |
| `o3` | `prefetch_byte_offsets=0,64,128`. |
| `o4` | `prefetch_byte_offsets=0,64,128,192`. |

## Current Interpretation

| Observation | Interpretation |
|---|---|
| Coverage is the strongest variable so far. | Too little coverage misses important targets; too much coverage increases code/dynamic instruction overhead. |
| `prefetcht1` has a clear benefit at the current best sites. | Data prefetch to instruction addresses is effective enough to reduce runtime significantly. |
| `prefetchit1` same-site results were weak. | It may need fewer sites, different timing, or different target/offset choices; hence the low-injection `prefetchit1` sweep. |
| Wider depth windows are not automatically better. | Depth is a timing/path-coverage knob. Wider windows create more candidates, but final value depends on selection and budget. |
| `0,64` helped `prefetcht1`. | Adjacent-line prefetching can help sequential instruction fetch, but it doubles prefetch instructions for each selected site/target. |
