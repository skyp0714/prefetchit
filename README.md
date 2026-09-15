# PrefetchIT — software instruction prefetch with `prefetcht1`

Research project (paper in preparation): on Intel Granite Rapids (Xeon 6787P)
the ISA's `prefetchit0/1` instruction-prefetch hints do nothing measurable, so
we inject the *data* prefetch `prefetcht1` at code addresses instead, and ask
where that actually speeds up datacenter workloads. Every stage below has its
own repository; this umbrella repository holds only the documentation and the
manifest that pins them together.

Read in this order: this file → [`docs/RESULTS.md`](docs/RESULTS.md) (what is
proven, with numbers) → [`docs/SETUP.md`](docs/SETUP.md) (host restore) →
[`docs/PLAN.md`](docs/PLAN.md) (what to do next).

## The flow

```
 1. microbenchmark      icache_microbenchmark/        when are prefetches dropped? prefetchit == no-op → use prefetcht1
        │
 2. static pass         profiling/  (PEBS+LBR oracle) ─┐
                        static_prefetch/ (ret,cond)   ├─► llvm_prefetchit/ (LLVM 19 pass + plan tools + measurement harness)
                                                       │      profile-free plan must match the profile-guided (PGO) plan
                        flat_codegen/  (arcilator)  ───┘      2026-09-15 re-run: PGO 1.021x (MPKI −6.6%), static neutral → open item (docs/RESULTS.md)
        │
 3. dispatch prefetch   llvm_prefetchit/scripts/dispatch/  1–2 source lines prefetching the *future* indirect-call target
                        (DCPerf Django 1.49x, FeedSim 1.073x; memcached neutral; DSB/MicroSuite/PostgreSQL negative)
        │
 4. JIT prefetch        jit_prefetch/                  HotSpot C2 emits the prefetches (V4 entry burst)
                        (JCodeStream 1.285x, WideApi 1.11x; recognised JVM suites are L2-resident → neutral)
```

| directory | repository | stage | what it is |
|---|---|---|---|
| `icache_microbenchmark/` | [icache_microbenchmark](https://github.com/skyp0714/icache_microbenchmark) (branch `prefetch_benefit`) | 1 | `prefetcht0/t1` vs `prefetchit0/1` under TLB warmth / branch-window placement |
| `profiling/` | [frontend_profiling](https://github.com/skyp0714/frontend_profiling) | 2 | PEBS/LBR trace collection + symbolisation (the "PGO" oracle) |
| `static_prefetch/` | [static_return_prefetch](https://github.com/skyp0714/static_return_prefetch) (merged with static_cond_prefetch) | 2 | profile-free RET-callsite / COND planner: `tools/static_plan.py --kinds ret,cond` |
| `flat_codegen/` | [flat_codegen](https://github.com/skyp0714/flat_codegen) | 2 (+3) | arcilator second workload; DeathStarBench build/A-B tooling (negative) |
| `llvm_prefetchit/` | [llvm_prefetchit_injection](https://github.com/skyp0714/llvm_prefetchit_injection) | 2, 3 | the pass (`lib/PrefetchITPass.cpp`), plan tools, `scripts/{platform,static,dispatch}`, migration manifest |
| `jit_prefetch/` | [jit_prefetch](https://github.com/skyp0714/jit_prefetch) | 4 | HotSpot patches, JCodeStream/WideApi, `scripts/ab_*.sh` |
| `benchmarks/`, `worktrees/`, `.tmp/` | third-party, ignored | – | pinned by `llvm_prefetchit/migration/benchmarks.lock.tsv` |

Each component keeps an `archive/` with the retired one-off campaign scripts
(history of the negative results); the live entry points are the ones listed
in the READMEs.

## Quick start on a restored host

```bash
llvm_prefetchit/migration/verify.sh --root "$PWD"              # sources, patches, tool hashes
sudo MODE=2ghz llvm_prefetchit/scripts/platform/freeze_platform.sh   # before every measurement
# stage 1
make -C icache_microbenchmark/microbench/src all prefetch_test
# stage 2 (needs the Chipyard Verilator simulator, see docs/SETUP.md): traces → PGO + static plans → pass → NOP twins → A/B
source benchmarks/chipyard/env.sh && llvm_prefetchit/scripts/static/run_verilator_repro.sh
# stage 3 (DCPerf installed per docs/SETUP.md)
llvm_prefetchit/scripts/dispatch/build_feedsim_manual_variants.sh && llvm_prefetchit/scripts/dispatch/run_feedsim_closedloop.sh
llvm_prefetchit/scripts/dispatch/build_django_icache_variants.sh  && llvm_prefetchit/scripts/dispatch/run_django_manual.sh
# stage 4 (patched JDK built per jit_prefetch/README.md)
jit_prefetch/scripts/ab_jcs.sh; jit_prefetch/wideapi/ab_wideapi.sh
```

## Measurement rules (non-negotiable)

1. Frozen platform: core min=max, turbo state explicit, uncore min=max
   (`freeze_platform.sh`); default DVFS gave prefetch arms a ~17% uncore
   credit that is not a prefetch effect.
2. One workload at a time, no builds during measurements, every thread pinned
   to its own physical core (`platform/campaign_common.sh`).
3. Compare against a layout-identical NOP-patched binary
   (`tools/make_nop_control_binary.py`) and verify the injection count with
   `objdump` — never trust a silent build.
4. ≥3 interleaved reps (5 for services); report medians/CI, not best cells.
5. Prefetch-only deltas count; PGO/layout gains are reported separately.

## Conventions

- Third-party checkouts stay at `benchmarks.lock.tsv`; results live outside
  git (`results/`, `work/`), conclusions go to `docs/` as dated notes.
- Result directories are `<topic>_<yyyymmdd>/`.
- Raw perf events use `cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/`.
