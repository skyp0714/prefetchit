# Class A expansion: FleetBench proto (2026-09-22)

Follow-up: the [expanded search](class_a_proto_search_20260922.md) subsequently
found a small, independently confirmed gain. The results below preserve the
initial five-policy experiment, not the latest conclusion for this workload.

This experiment extends the existing compiler pass to the upstream FleetBench
protobuf workload. It does not change the benchmark's messages, operation mix,
working set, optimization level, or allocator. The current screening rule is:
among operationally valid service loads with utilization >=15%, select the
highest baseline L2 code MPKI and disclose the full load sweep. Batch benchmarks
retain their normal saturated execution. This is candidate selection, not a
claim that the selected load represents a deployment's average load.

## Result

Five policies were measured against both a fresh baseline in the same campaign
and their NOP twins: 39 timing runs total, 100 operations/run, three rounds/arm.
None improved baseline CPU time. Speedup is the ratio of median CPU times
(greater than one is better); counters are medians of per-run measurements.

| Policy | CPU ms/op | vs base | vs NOP | L2 code MPKI | Instructions vs base |
|---|---:|---:|---:|---:|---:|
| Sequential 4 KB / stride 80 | 140.468 | 0.9912x | 0.9960x | 16.52 → 15.85 | +0.25% |
| Callee two-line / lead 32 | 139.722 | 0.9965x | 0.9980x | 16.52 → 16.42 | +0.68% |
| Static cost plan | 140.668 | 0.9905x | 0.9994x | 16.52 → 16.30 | +1.88% |
| Retired-miss trace entry plan | 140.409 | 0.9923x | 0.9978x | 16.52 → 15.79 | +3.66% |
| Trace plan with measured cost pruning | 139.826 | 0.9963x | 0.9998x | 16.53 → 16.55 | +0.012% |

Baseline medians in the three campaigns were 139.238, 139.331 and 139.311 ms/op.
Every paired baseline/prefetch CPU-time ratio was below 1.0. Three rounds do not
establish precise sub-percent effects or generalization to other seeds; no arm
earned promotion to a larger confirmation/holdout experiment.

MPKI alone overstates the trace plan's benefit: absolute L2 code misses per fixed
work fell only 0.91%, while instructions rose 3.66%. Sequential mode reduced
absolute misses by 3.82% but still lost time against its NOP twin. Cost pruning
removed almost all instruction overhead, but also reduced selected miss weight
to 2.3%; it did not improve baseline or NOP time. These results reject these
specific configurations as wins, not the workload or software prefetch in general.

## Next experiment

1. Establish broader retired-miss coverage using stable internal basic-block/run
   anchors across recompilation; the entry-only trace plan is not an ideal upper
   bound. Audit emitted target addresses before timing.
2. Select earlier sites that predict the particular target path, and use measured
   execution cost first. Unconditional allocator/memcpy entry bursts pay on many
   executions unrelated to a selected miss. Sweep lead and budget on a training
   input, then translate successful rules into static CFG/call-graph analysis.
3. Require improvements against both baseline and twin, and a reduction in
   retired miss/stall counts per fixed work, before confirming on seed 1 and more
   rounds. Keep default workload semantics and disclose the full sweep.
4. Use ARM frontend's upstream default and larger footprint as separate synthetic
   mechanism checks, not as representative application speedups. MySQL/Rails
   remain subsequent real-application expansion candidates.

All measurement contexts restored the saved sysfs values; final HWP restoration
was also read back and verified. No workload source or LLVM pass was changed.
The NOP regression test passes, Python syntax checks and `git diff --check` pass.
The repository migration verifier reports only its clean-worktree requirement:
this experiment's changes are intentionally uncommitted; its other checks pass.

## Workload and controls

- FleetBench commit `703e5e5566a629d1849bc0e3f3e262d88d5977f4`.
- Upstream default `BM_PROTO_Arena`, seed 0, 100 benchmark iterations/run.
  Each iteration creates an arena and executes the unchanged generated lifecycle;
  the lifecycle's workset parameter remains 10. Seed 0 is also upstream's default.
- Same clang 19, Bazel `-c opt` plus `-gline-tables-only` for every build.
  No layout PGO, no static-linking change between arms.
- Xeon 6787P, kernel 6.8.0-139, CPU 36, alone, C6/C6P disabled on that core.
  Core 2 GHz, turbo off, HWP min/max/desired 20; uncore min=max at each domain's
  existing maximum. This 2 GHz experiment is separate from the older 3.8 GHz
  simulator experiments. Sysfs limits alone did not constrain HWP on this boot.
- Three rounds, randomized arm order within each round, fixed work in every arm.
  No builds overlap measurements. Primary endpoint is Google Benchmark CPU time
  per iteration; wall time and process-wide user perf counters are also retained.
  Perf counts include process startup outside the timed benchmark region.
- One exact-size, same-layout NOP twin per instrumented binary. Only newly added
  `prefetcht1` instructions are patched. Baseline has zero T1 instructions but
  11,355 T0, 77 T2, and 45 NTA instructions; these upstream prefetches remain.
- Before/frozen/restored sysfs and HWP snapshots remain in the ignored raw result
  directory. The review archive retains binary hashes, individual benchmark JSON
  logs and unscaled perf CSVs. Every accepted run's
  main hardware counters ran 100% of its enabled time.

## Baseline diagnosis

The separate 30-iteration profile at 2 GHz reports:

| Metric | Value |
|---|---:|
| Top-down frontend bound | 56.08% of slots |
| Fetch latency | 43.53% of slots |
| Backend bound | 11.37% of slots |
| Bad speculation | 18.43% of slots |
| ICACHE_DATA.STALLS | 17.05% of cycles |
| ITLB_MISSES.WALK_ACTIVE (cmask=1) | 0.94% of cycles |
| L2_RQSTS.CODE_RD_MISS | 16.32 / 1,000 user instructions |
| FRONTEND_RETIRED.L2_MISS | 1.51 / 1,000 user instructions |

These are separate perf invocations. Fetch latency includes more than instruction
cache misses. Speculative L2 requests and retired frontend misses have different
semantics: their difference must not be interpreted as an exact wrong-path share.
High FE-bound and MPKI therefore do not establish a software-prefetch speedup ceiling.

The retired event works on this boot: `cpu/event=0xc6,umask=0x03,config1=0x13/upp`.
Recording it with period 1009 and LBR produced 12,139 samples, 12,105 mapped to the
benchmark executable. Individual functions have at most 86 samples; misses are
distributed across generated Clear/Merge/ByteSize/Serialize code and runtime code.
The trace does not support assuming that a handful of hot functions cover most
retired misses. Historical profiles using speculative request events are a
different diagnostic and should not be substituted for this trace.

## Compared policies

| Arm | Selection and placement | Added static T1 instructions |
|---|---|---:|
| `seq4k80` | Existing sequential mode: distance 4096 B, stride 80 IR instructions, minimum function size 512 IR instructions | 9,664 |
| `burst2lead32` | Existing callee mode: two lines, lead 32 IR instructions, minimum callee size 64 IR instructions | 7,834 |
| `cold_static` | Static call-graph cost plan: estimated lead 60–1000 instructions, two entry lines/callee, max four callees/site, modeled instruction budget 0.5% | 12,267 |
| `cold_trace` | Retired-miss/LBR plan: estimated lead 60–1000 cycles, minimum sample weight 3, max four targets/site, no GOT targets; restricted to function entry regions | 413 |
| `cold_trace_cost` | Same trace plan, with sites pruned using a separate precise retired-instruction profile | 51 |

The static plan has 3,705 requested sites and 14,609 targets after excluding two
references to `tcmalloc::GetMemoryStats` that failed PC-relative relocation in this
link. The failed build log and original plan are retained. Planned targets and
emitted instructions differ because compiler/linker transformations can remove,
merge, or duplicate definitions; the disassembled final binary is the count above.
The model's estimated dynamic cost is not a calibrated runtime prediction.

The trace planner initially retained weight 1,731/12,139. Restricting offsets to
the first 128 bytes and mapping to symbol+0/+64 leaves 354 requested sites,
417 targets and weight 1,606/12,139 (13.2%). This is selected baseline sample
weight, **not measured cache-line coverage after recompilation or an oracle**.
In particular, entry anchoring deliberately avoids claims about exact internal
miss-line offsets after rebuilding. No execution-rate profile was supplied to
the trace planner, so frequently executed sites can still over-prefetch.

The follow-up cost profile uses `instructions:upp`, period 20,003, and the same
30 benchmark iterations as the miss trace. Of 416,581 instruction samples,
397,264 map to the executable and 9,015 land exactly on T1 instructions. Arena
allocation and memcpy dominate these samples. For each site, the cost filter
estimates `max(3, instruction_samples) * 20003 / (selected_miss_weight * 1009)`
and keeps ratios <=10. The three-sample floor avoids treating unobserved sites
as free. This leaves 36 requested sites, 55 targets, weight 275 (2.3% of original
miss samples), and 51 emitted T1s. It estimates cost per **selected** miss, not
per miss actually saved; sampling and profile overhead limit its accuracy.

## Reproduction and artifacts

Raw artifacts: `llvm_prefetchit/results/class_a_proto_20260922/` (git-ignored).
Small measurement tables and build metadata are archived under
`llvm_prefetchit/migration/evidence/fleetbench_proto_20260922/`.

Build with `llvm_prefetchit/scripts/static/build_fleetbench_class_a.py`:

```bash
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py --out RESULTS base
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py --out RESULTS seq4k80
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py --out RESULTS burst2lead32
sudo python3 llvm_prefetchit/scripts/static/measure_class_a.py \
  --out RESULTS/profile --iterations 30 --profile RESULTS/bin/base --trace
```

`RESULTS` must be a new directory. The build helper refuses to overwrite a saved
arm. After preparing the plans, use `--plan PLAN.json cold_static` or `cold_trace`.
Measurements accept named arms, e.g. `base=RESULTS/bin/base` and
`seq4k80_nop=RESULTS/bin/seq4k80_nop`, with `--iterations 100 --reps 3`.
The harness currently targets this Intel host and requires perf, MSR access and
`x86_energy_perf_policy`; its HWP values are not a portable frequency interface.

Planner parameters (run from the repository root; `R` is the artifact directory):

```bash
R=llvm_prefetchit/results/class_a_proto_20260922
python3 llvm_prefetchit/tools/static_cost_plan.py "$R/bin/base" "$R/plans/static.json" \
  --instrumentable "$R/global_symbols.txt" --min-lead 60 --max-lead 1000 \
  --max-per-site 4 --budget 0.005 --lines 2
python3 flat_codegen/dsb_build/postlink/cold_plan.py "$R/profile_base_fixed" "$R/bin/base" \
  /usr/lib/x86_64-linux-gnu/libc.so.6 "$R/global_symbols.txt" "$R/plans/trace.json" \
  --min-w 3 --max-per-site 4 --max-sites-per-line 1 --min-lead 60 \
  --max-lead 1000 --drop-own-line0 --no-got --exe-suffix /bin/base
```

`global_symbols.txt` contains the defined `T`/`W` names from `nm`; `maps.txt` uses
the executable mappings recorded by `perf script --show-mmap-events`, including
file offsets. The planner handles ELF file-offset/virtual-address deltas.
For `trace_entry.json`, discard GOT and offset>=128 targets, map offset<64 to 0
and the rest to 64, deduplicate per (site,symbol,offset), sum sample weights, and
set each site's padding budget to `ceil(7*target_count/16)*16`. Negative original
line offsets are intentionally reinterpreted as symbol+0, not emitted literally.
For `static_linkable.json`, remove only the two GetMemoryStats references and
recompute that site's padding budget with the same formula.

For the cost-filtered follow-up:

```bash
sudo python3 llvm_prefetchit/scripts/static/measure_class_a.py \
  --out RESULTS/profile_trace_cost --iterations 30 \
  --profile RESULTS/bin/cold_trace --instruction-trace
python3 llvm_prefetchit/tools/prune_sampled_prefetch_cost.py \
  RESULTS/bin/cold_trace RESULTS/profile_trace_cost/instructions.txt \
  RESULTS/plans/trace_entry.json RESULTS/plans/trace_cost.json
python3 llvm_prefetchit/scripts/static/build_fleetbench_class_a.py \
  --out RESULTS --plan RESULTS/plans/trace_cost.json cold_trace_cost
```

## Measurement/tooling exclusions

- `profile_stock`: initial platform diagnostic ran at approximately 3.8 GHz;
  excluded from the accepted 2 GHz profile and speedup comparisons.
- `profile_base`: launch failed because the binary was not yet available;
  excluded. The harness now checks existence before changing platform settings.
- Initial NOP twins missed tcmalloc's custom executable sections. The NOP helper
  now patches every executable PROGBITS section and fails if selected prefetches
  remain. Both twins were regenerated and verified **before** timing began.
  A regression test covers custom sections, read-only binaries, unchanged input,
  equal file size, preserved T0 instructions, and a runnable NOP twin.
- No inference about past experiment validity follows solely from this helper
  fix; past binaries would need separate inspection.
