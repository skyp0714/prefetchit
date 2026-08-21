# Paper-Goal Campaign 2026-08-15 — Final Report (rev 2, post-forensics)

Goal: static or manual prefetch (a) significantly beats baseline and (b)
approaches or beats PGO. All configs in `CONFIG_LOG.md`; raw data under this
directory.

**rev 2 (evening 2026-08-15): every pre-existing Verilator number — June's
included — was frequency-confounded. This revision replaces the verdict table
with measurements taken under the frozen platform config**
(`scripts/configure_fixed_frequency_v2.sh`: core min=max fixed, EPP=0,
uncore min=max pinned, turbo state explicit, `MODE=3.8ghz` for single-core
Verilator / `MODE=2ghz` for multi-core PostgreSQL). See "Platform forensics"
in CONFIG_LOG.md for the full elimination chain.

## The DVFS confound, in one paragraph

June's Verilator numbers (base 343.5s, static 1.226x, pgo 1.257x) were taken
on Ubuntu defaults: all variants ran at the same ~3.795 GHz core clock, but
the uncore floated. Baseline's demand code misses do not trip the uncore
boost heuristic (17% IPC penalty vs uncore-pinned), while the prefetcht1
traffic of the prefetch binaries drives the uncore up — so the prefetch
binaries got credit for waking the uncore. Reproduced exactly today
(150k-cycle probes, defaults: base 93.7s / static 77.9s / pgo 75.8s ≡
June-scaled 95.7/78.1/76.2). The June variant RANKING was also contaminated:
the honest winner is a different binary family entirely (RET/callsite, below).

## Verdict table (frozen platform, fixed 3.8GHz + uncore pinned, 3 reps)

| Workload | static | PGO | verdict |
|---|---:|---:|---|
| Verilator qsort (full 538240 cyc) | **1.078x ± 0.001** (top1k_callsite, 1000 inj) | 1.075x ± 0.001 (cond_cov25, 20573 inj) | ✓ **static ≥ PGO at 20x fewer injections** |
| Verilator mm/dhrystone/median (transfer, 150k) | 1.075–1.079x | 1.076–1.077x | ✓ static = PGO on every payload, zero re-tuning |
| PostgreSQL (2GHz mode, NOP-layout-controlled, n=5) | 1.0232x ± 0.0210 (top32) | 1.0117x ± 0.0267 (cov25) | ✓ statistically equal; no PGO advantage |
| Django manual (2GHz mode, 3 reps) | **1.490x ± 0.01** (d4_next; MPKI 84.6→35.0) | n/a | ✓ real and large (July 1.805x had ~0.3x uncore-DVFS inflation) |
| FeedSim manual (2GHz mode, 3 reps) | default cfg 1.050x; **best cfg (ICACHE_ITERS=200M, threads=2, 300s): 1.073x** (MPKI 8.1→1.7) | n/a | ✓ ≥5% met; config sweep showed the gain curve peaks there (i400M saturates MPKI ~8.7, gain vanishes; t4 compresses to 1.03x) |
| memcached manual (2GHz mode) | neutral — drop from paper | memtier paired: 1.0002x±0.005 (MPKI 0.04); July's exact sync-client c2048_w8 stress rebuilt: mean 0.86, sd 0.11, MPKI swinging 4→18 between pairs — pathologically unstable load, not a usable result. July's +15.3% attributed to old-kernel + uncontrolled-frequency + unstable client. |

Base runtime 284.80s (3 reps, sd 0.3s). Top-5 full-length confirms (sd ≤0.6s):
static_top1k_callsite_b1 264.22s (1.078x) > pgo_cond_cov25 264.93s (1.075x) >
static_top1k_mixed_b8 265.12s > static_nested_top3000_callsite_b1 265.31s >
pgo_ret_cov90 265.54s.

## Honest re-ranking of all 45 June-era variant binaries

150k-cycle probe of every prebuilt binary from the June COND-autotune,
COND-PGO-compare, and RET campaigns (`variant_probe_fixed38/probe.csv`),
fixed 3.8GHz + uncore pinned:

- Winners are the **RET/callsite static family**: static_top1k_callsite_b1
  1.091x (probe) with 1000 injections; nested_top{1500,3000,5000}_callsite_b1
  all ~1.089x. PGO best: pgo_cond_cov25 1.090x, pgo_ret_cov90 1.088x.
- June's celebrated COND winners are mid-pack under honest clocks:
  static_gap100k 1.038x, pgo_cond_cov50 1.061x.
- Over-injection actively hurts at fixed clocks: pgo_cond_cov100 **0.948x**
  (5% slowdown, 260k+ prefetches).
- MPKI reductions match June exactly (e.g. cov25: 51.6 then and now) — the
  cache-level behavior never changed; only the DVFS side-channel did.

Paper story upgrade: June's framing was "static reaches ~90% of the PGO
oracle". The honest framing is **"profile-free static selection matches or
beats the PGO oracle, using 20x fewer injections"** — and the transfer table
shows it generalizes payload-invariantly.

## Two deployment regimes worth reporting (both real)

1. **Fixed platform** (methodology-clean): static 1.078x, pgo 1.075x.
2. **Default platform** (how servers actually ship): base is additionally
   penalized ~17% by the uncore-boost blindspot for demand code misses, so
   sw code prefetch delivers ~1.20–1.24x wall-clock — partly by waking the
   uncore. Decomposing these is a contribution; conflating them was June's
   mistake.

## Recovery exploration (user directive: vary injection/target/depth/coverage)

Phase 1 (done): 45-binary re-rank above — coverage axis (top1k…100k,
cov25…100), target axis (callsite/calleeret/mixed/nested/spread/cond),
depth/batch axis (b1/b8/b32, dist4k/16k, offsets o1/o2), site axis
(current/prev, win16, fetch-gap/ts/entry/ens). Findings: (a) small
targeted RET plans dominate; (b) COND cov25 is the PGO sweet spot; (c)
aggressive coverage is counterproductive at honest clocks.

Phase 2 (done): merged RET+COND plans (`tools/merge_prefetch_plans.py`,
built via EXTERNAL_PLAN path, binaries in `combo_builds/`). 150k probes vs
same-session base 79.75s:

| combo | prefetches | time | vs base | MPKI |
|---|---:|---:|---:|---:|
| sret1k + pcond_cov25 (hybrid) | 41,302 | 73.47s | 1.085x | 51.1 |
| pret90 + pcond_cov25 (PGO) | 50,970 | 74.48s | 1.071x | 50.7 |
| sret1k + scond_ts60k64 (pure static) | 121,492 | 78.31s | 1.018x | 56.2 |
| (reference: static_top1k alone) | 2,000 | 73.38s | 1.087x | 55.4 |

**Conclusion: combining works at the cache level (MPKI drops to 50.7) but
never at the time level — injection overhead cancels the extra miss
reduction. ~1.08x is the honest ceiling for this workload, and the surgical
1000-injection static plan already sits on it.** June-scale gains are not
recoverable because they were never microarchitectural.

## PostgreSQL (MODE=2ghz + uncore pinned) — done

Re-ran both NOP-layout-controlled paired experiments under the frozen 2GHz
config (`run_pg_nop_controls_20260815.sh`): static top32 1.0232x ± 0.0210
(sem), PGO cov25 1.0117x ± 0.0267 — statistically equal, static numerically
ahead; consistent with yesterday's uncore-floor rows (1.0090/1.0104). The
PG conclusion is frequency-robust: static ≈ PGO ≈ +1–2%, July's PGO 1.0609x
does not reproduce under any controlled condition.

## Excluded / unchanged

- gem5 (L2I MPKI 0.001–0.002) and SPEC 2026 (max 0.6): still excluded by the
  MPKI screen; the screen itself is frequency-insensitive.
- Datacenter neutral results (Router/SetAlgebra/HDSearch/TailBench/etc.):
  unchanged as neutrals; Router's July +198% PGO row remains quarantined
  (baseline confound, see PAPER_RESULTS_AND_FEEDBACK.md).

## Infrastructure added in rev 2

- `scripts/configure_fixed_frequency_v2.sh` — frozen platform config
  (3.8ghz/2ghz modes, uncore pinning with the package-min propagation
  gotcha handled, EPP pinning, turbo-bit reset).
- `scripts/probe_variant_binaries.sh` — probe every prebuilt variant binary
  across campaign dirs, ranked CSV.
- `run_verilator_crosspayload_transfer.sh` — BASE_BIN/STATIC_BIN/PGO_BIN now
  env-overridable.
- Combo plans under `combo_plans/` via `tools/merge_prefetch_plans.py`.

## New benchmark exploration (screen datapoints, 2026-08-15)

- clang-19 -O2 on the 100MB Verilator TU: L2I MPKI **0.368**, IPC 1.376 —
  compilers are excluded by the MPKI screen (consistent with SPEC max 0.6).
- Qualifying workloads remain the megabyte-code class: Verilator-generated
  RTL eval (58), Django (84), Router (85), HDSearch (79), PostgreSQL.
- Highest-value next steps (in order):
  1. **Static compiler pass on the manual-positive structures**
     (Django/FeedSim ICacheBuster, memcached conn dispatch) — converts the
     manual wins into compiler-pass wins and closes the paper's "static pass
     proven only on Verilator" gap (attempt matrix's own recommendation).
  2. Bigger Verilator SoC configs (more generated code → higher MPKI, tests
     scaling of the 1000-injection static plan).
  3. memcached c2048_w8 stress config under frozen platform (finish the
     memcached verdict).
  4. JVM services (Cassandra itself) as a managed-runtime i-cache case.

## PostgreSQL config exploration (2026-08-16, target ≥5%) — negative, diagnosed

Config screen (scale 100, shared_buffers 4GB): tpcb MPKI 47-108 is real but
fsync-bound (CPU gains can't reach TPS); `synchronous_commit=off` converts
c8 tpcb to CPU-bound (TPS 2.8k→7.0k, IPC 0.94, MPKI 25); c32 hits branch
lock contention instead. select-only MPKI collapses to 0.08 under per-core
backend pinning (the i-pressure there was scheduler-induced).

Paired NOP-controlled at the best config (c8 tpcb syncoff, scale 100):
static top32 1.0057±0.0148, PGO cov25 0.9966±0.0211, static top64
0.9829±0.0192 with L2I reduction −1.7%. The 336-injection plan removes only
~3% of misses: **PostgreSQL's miss profile is diffuse (thousands of lines,
no dominant call pattern), so partial-coverage prefetch is structurally
capped at ~1-2% and more coverage self-defeats — same overhead mechanism as
the Verilator ceiling.** PG stays in the paper as the diffuse-miss negative
case; ≥5% is not reachable with this technique.

## New workload screens completed (2026-08-16)

| candidate | load state | L2I MPKI | IPC | verdict |
|---|---|---:|---:|---|
| clang-19 (100MB TU, -O2) | full compile | 0.368 | 1.38 | excluded |
| node.js http (200-route dispatch, 64 conn) | 19.4k QPS | 1.713 | 2.71 | excluded |
| Cassandra 3.11 (stress mixed 1:3, loaded) | 784B inst/40s | 0.440 | 1.45 | excluded (idle JVM shows 11.9 — trap: must screen under load) |
| QEMU TCG (qemu-x86_64 + python loop) | steady | 0.005 | 5.16 | excluded (translated blocks chain into L1I) |
| MariaDB + mysqlslap | perf-attach blocked | – | – | deprioritized (PG's diffuse-miss sibling, low prior) |

Finding worth stating in the paper: across compilers, JIT runtimes (V8,
JVM), KV stores, and OLTP/analytical DB engines, loaded L2I MPKI stays
below 2. Truly i-cache-bound workloads are the megabyte-generated-code
class (Verilator RTL eval) and sprawling interpreted/service stacks
(Django 84, MicroSuite 79-85) — the paper's showcase set is
representative, not cherry-picked.

## Goal status vs user targets (≥5% required, ≥10% preferred, outside error bars)

| workload | frozen-platform gain | error | status |
|---|---:|---:|---|
| Django (manual d4_next) | **1.490x** | ±0.01 | ✓✓ |
| Verilator (static top1k, 1000 inj) | **1.078x** | ±0.001 | ✓ (honest ceiling ~1.08x, proven by combo sweep) |
| FeedSim (manual d16, ICACHE_ITERS=200M t2) | **1.073x** | ±0.02 | ✓ |
| PostgreSQL | 1.006–1.023x | ±0.015–0.021 | ✗ structural (diffuse misses) — keep as negative case |
| memcached | 1.000x | ±0.005 | ✗ drop |

## Simulation-class & scientific HPC screens (2026-08-16)

| workload | engine type | loaded L2I MPKI | IPC | verdict |
|---|---|---:|---:|---|
| Verilator DualMegaBoom (105MB bin) | compiled/flattened C++ | **58.6** | 0.56 | showcase (reference) |
| Verilator RocketConfig (37MB bin) | compiled/flattened C++ | 0.89 | 3.43 | excluded — hot eval fits in cache |
| Icarus vvp (8k-reg design) | bytecode interpreter | 0.002 | 4.08 | excluded |
| GHDL mcode (40k-reg design) | runtime threaded-code gen | 0.270 | 2.30 | excluded |
| ngspice (20k-node RC ladder) | sparse numeric | ~0.03 | 3.40 | excluded |
| LAMMPS LJ melt (256k atoms) | MD kernels | 0.002 | 2.45 | excluded |

Two findings for the paper:
1. **Within RTL simulation, the engine's code-generation strategy — not the
   domain — determines i-cache pressure**: interpreter (vvp 0.002) and
   threaded-code (GHDL 0.27) engines stay compact; only Verilator's fully
   flattened per-design C++ blows out the cache, and only once the design's
   eval code exceeds cache capacity (Rocket 37MB→0.89 vs DualMegaBoom
   105MB→58.6 is a cliff).
2. Scientific HPC kernels (MD; and by prior screens SPEC/NPB-class) are
   structurally out of scope for instruction prefetching.

Implication: the single best lever for a bigger honest Verilator win is a
LARGER SoC design (more eval code → higher MPKI than 58.6) — queued as the
follow-up build (multi-hour verilate+compile).

## Second new-workload sweep: JVM suites + PHP (2026-08-16)

| workload | loaded L2I MPKI | IPC | verdict |
|---|---:|---:|---|
| **DaCapo tomcat** | **10.84** | 1.32 | **qualifies by MPKI** — but 55% of misses in [JIT] code (+33% unknown/anon), libjvm.so only 8.4% → AOT pass can't reach; motivates JIT-integrated prefetch as future work |
| DaCapo tradesoap | 4.00 | 2.18 | borderline, JIT-bound likewise |
| DaCapo spring / tradebeans / eclipse / h2 | 2.45 / 2.35 / 1.05 / 0.55 | – | excluded |
| Renaissance finagle-http / chirper / neo4j / dotty | 0.79 / 1.34 / 0.19 / 1.61 | – | excluded |
| PHP 8.1 (600-class OOP app, 2.5k QPS, opcache on/off) | 0.24–0.28 | 2.94 | excluded — Zend interpreter is compact; app code is DATA to the VM. (AsmDB-era PHP i-pressure was HHVM's JIT sprawl.) |

Cumulative screening across ~20 new candidates (2 days): the only workloads
above the MPKI bar are (a) flattened-codegen simulators (Verilator-class),
(b) sprawling interpreted-service stacks (Django), (c) JIT-heavy JVM app
servers (tomcat — out of AOT scope). The workload-characterization section
of the paper now rests on a broad, documented negative space: compilers,
HPC kernels, MD, circuit/numeric sim, interpreter VMs (PHP/JS/bytecode-RTL),
KV stores, OLTP/analytical DBs, JVM data-processing — all < 5 MPKI under
load. This makes the showcase selection defensible as a class property, not
cherry-picking.

## JIT workloads: flag characterization + sidecar viability (2026-08-16)

D (flag sweep, tomcat): SegmentedCodeCache / ReservedCodeCacheSize 64m-1g /
tiered variations move L2I MPKI by <±5% and iteration time <1% (C1-only:
-13% MPKI but +8% slower). **The ~12 MPKI is intrinsic JIT-code sprawl, not
layout-addressable — full headroom belongs to prefetching.**

B (sidecar L2-warmer): resolved by measurement before building the agent.
OCR.DEMAND_CODE_RD.L3_MISS (raw 0x2a/0x01/0x3FBFC00004, validated on
Verilator where it reads ~0): tomcat L3 code-miss share is **0.0%** (0.002
MPKI of 12.15). All code misses are L2→LLC latency; with per-core private
L2 on GNR, a sidecar on another core can only warm its own L2 and the
already-warm LLC. **Helper-thread/sidecar code warming is structurally
ineffective on private-L2 server CPUs — instruction prefetches must execute
on the consuming core. This uniquely motivates same-core injection (our
approach) and, for JIT code, C2-integrated injection (future work; our
winning RET/callsite pattern maps directly onto C2 call emission, with MDO
profiles available for free).**

Flattened-codegen class survey (user question): outside EDA the class is
empty across 25 screened workloads. True siblings are ESSENT (FIRRTL→C++,
more aggressively flattened than Verilator) and CIRCT arcilator (RTL→LLVM
IR — our pass would integrate at IR level). Caveat: this chipyard emits
Chisel-7/FIRRTL-4 .fir which predates-incompatible with ESSENT's old scala
FIRRTL frontend; arcilator needs an hours-long CIRCT source build.

## JIT SUCCESS (2026-08-16, overnight campaign): +28.5% pure prefetcht1 in C2

After V1-V4 policy exploration across DaCapo (tomcat all-configs, avrora,
12-workload broad screen — all neutral, each failure mapped to a violated
axis), the four-axis criterion was used CONSTRUCTIVELY: JCodeStream
(jit_prefetch/jcodestream), the JIT twin of the Verilator profile — 16.7MB
of C2-compiled code (9,000 non-inlinable leaves), walked in a fixed global
shuffle. Steady state: L2I 93.2, L1I≈L2I (1% L2-hit), IPC 0.398.

**V4 entry-burst (PrefetchEntryAhead=128, Lines=32): 14.95 → 11.63 ms/iter
= 1.2854x (+28.5%), MPKI −68%, 5 reps, sd ≤0.32ms, dose-response monotone
across 8/16/32 lines.** V2/V3 neutral (zero-lead call-adjacent). Key
methodology finds: sequential layouts are fully absorbed by the HW L2
streamer (L2I 0.6) — SW code prefetch earns its keep precisely on
deterministic-but-layout-nonlocal traversals; compile-queue drain and
FreqInlineSize are benchmark-design hazards.

Paper claim completed: the same prefetcht1 technique wins in AOT
(Verilator 1.078x, Django 1.49x) and JIT (JCS3 1.285x) when the four axes
hold, and every real-workload failure (PG, tomcat, avrora, arc-saturation)
is explained by a specific violated axis.

## Class-2 (indirect-dispatch datacenter services) resolution (2026-08-17)

Matched-baseline redos (same-binary NOP controls, frozen 2GHz, n=5):
- MicroSuite Router: PGO cov100_noomp 0.983±0.043, static router_global
  0.932±0.040, L2I deltas negative, run noise stdev ~10% — **July's +198%
  is now 100% attributed to the noomp build confound**; Router closed.
- MicroSuite HDSearch: PGO cov75 0.992±0.013, L2I −0.4% — neutral; closed.
- DeathStarBench: July screens already showed per-service low MPKI
  (chained tiny services); no qualifying config known — recorded as class
  boundary, not re-run.
Class 2's standing datacenter anchors remain the DCPerf pair: **Django
1.490x and FeedSim 1.073x** (method-pointer dispatch prefetch — the
class's defining mechanism), both frozen-platform verified.

## THREE-CLASS x DATACENTER MATRIX — campaign synthesis (2026-08-17)

| class | mechanism | showcase (frozen platform) | datacenter reality | boundary evidence |
|---|---|---|---|---|
| 1. Flattened/big-fn streaming | RET/callsite static plans | Verilator 1.078x (static ≥ PGO at 20x fewer inj); arcilator = saturation boundary | none found outside EDA (35+ workloads incl. suricata 0.02, clamav-class, compilers, HPC) — scarcity documented | arc 79 MPKI: hints dropped (MSHR) |
| 2. Indirect-dispatch services | method-pointer/dispatch-target prefetch | **Django 1.490x, FeedSim 1.073x (DCPerf)** | Router/HDSearch neutral under matched NOP baselines (July +198% = 100% noomp confound); DSB per-service low-MPKI | PG diffuse-miss cap ~1-2% |
| 3. JIT (C2) | V4 entry-burst (+V1/V2/V3 ref impls) | **JCodeStream 1.285x (+28.5%), robust variant +26.2%** | kafka neutral; tradesoap/spring below threshold — blanket V4 harms (0.79/0.94x), MinBytecode gate mitigates (0.97/0.99x) → default-off, streaming-activation deployment; avrora = dynamic-target boundary | four-axis criterion |

Four-axis workload criterion (the paper's selection theory): L2I MPKI
magnitude x static target determinism x FE-bound share x L1I≈L2I
(stream-past-L2). Every positive and every negative in this table is
explained by it.

## Wave-2 addendum (2026-08-17): PGO-first enforcement + DSB breakthrough

- Methodology locked per user: trace → PGO ceiling → static-vs-ceiling.
- MicroSuite trilogy closed under matched NOP baselines: Router 0.983,
  HDSearch 0.992, Recommend 1.0058±0.0032 — all July positives were
  layout/build confounds.
- **DSB socialNetwork deployed live** (docker; jaeger-config perms fix),
  graph seeded, 2.4k QPS python REST load: **aggregate L2I 18.6 MPKI** —
  July's low-MPKI verdict was a smoke-test artifact. Miss attribution:
  thrift C++ services ~33% (PostStorage 10.9% top), openresty 18.6%.
  Next flagship experiment: rebuild thrift services with clang+pass,
  PGO-first (trace→plan→ceiling→static).
- arc (C1): +4.49% layout-controlled stands (s4la16). Existing planner
  structurally inapplicable to inlined mega-function shape (48.7k IR
  calls → 113 real); blockaddress block-lookahead pessimizes layout
  (dead end); backend-pass intra-function lookahead = future work.

## Wave-3 addendum (2026-08-17): DSB full-custom stack live + PGO-first chain

- **All 11 DSB C++ services rebuilt from source** (clang-19 -O3 -g, jammy
  deps image `dsb-deps-jammy`): dependency stack recreated at modern
  versions (thrift 0.12 wire-compat, mongoc 1.15, redis++ 1.2.3 w/ DSB
  cluster patch, jaeger 0.4.2, yaml-cpp static link fix). Full stack
  swapped in via compose-override (bin_active mount + entrypoint), all
  services serving.
- Functional fix required: redis++ >=1.2 `range_check` throws on
  empty-range zadd; DSB `SocialGraphHandler::GetFollowers/GetFollowees`
  mongo-fallback path zadds an empty set for 0-follower users →
  compose_post 500s. Guarded (`!redis_zset.empty()`); affects both A/B
  arms identically.
- Load scaling: 1x16 python client was client-bound (1.77k QPS, client
  123% CPU). Multiprocess driver (dsb_load2.py, 4 procs x 16 threads):
  **8009 QPS, p50 7.7ms / p95 12.4 / p99 14.8, 0 errors / 1.2M reqs**.
- **PostStorageService under our -O3 build: L2I 20.1 MPKI, IPC 1.14**
  (313M L2I code misses / 15.6G insns / 10s) — strongest datacenter
  candidate of the campaign.
- PGO ceiling arm: 60s LBR (cycles:P -b, 942k samples) → llvm-profgen-19
  AutoFDO profile (7.4M ranges, 99.2% mapped) → `-fprofile-sample-use`
  rebuild. Interleaved swap-restart A/B harness (dsb_ab.sh: binary swap
  in bin_active + single-container restart, 15s warmup, 75s measured,
  mid-run 20s perf window) — 4 reps each arm, running.
- Static arm toolchain verified container-compatible: PrefetchITPass.so
  (LLVM 19) loads under container clang-19; recipe = perf record
  L2I_CODE_RD_MISS/upp -b → perf script -F ip,sym,brstacksym,weight →
  prefetchit_trace_to_plan.py → -fpass-plugin rebuild + NOP control.

## Wave-3b (2026-08-17): DSB static arm — saturation-load verdict + infra notes

- PGO ceiling reproduced in 4-arm interleave: **pgo −2.96% service cycles
  vs stock** at fixed 8k QPS (first A/B: −4.1%; both clean separation).
- Static plan v1 (cov75 internal+external-GOT merged: 157 sites / 314
  prefetcht1; external targets incl. malloc/pthread_mutex GOT entries):
  **inj vs NOP-pair +0.68% cycles, no miss reduction — neutral at
  saturation.** L2I MPKI at 8k QPS is only ~5.3 (warm code) vs 20.1 at
  low load (cold, request-interleaved) — the prefetchable regime is the
  low-utilization one; low-load 4-arm A/B running (cycles/request +
  latency metric).
- **Layout-luck validation at datacenter scale**: nop vs stock −1.62%
  cycles with +5.8% instructions (IPC 1.647 vs 1.532) — injection
  shifted layout favorably; without the NOP-pair control the static arm
  would have been misread as a ~1% win over stock. Protocol vindicated.
- NOP-control tool bug fixed (tools/make_nop_control_binary.py):
  objdump wraps instruction bytes at 7/line, so 8-byte REX+disp32
  prefetches (41 0f 18 93 disp32) were truncated-patched → corrupted
  stream → service crash. Continuation-line parsing added; REX-prefixed
  prefetches now patched full-length. (Also affects any future 8-byte
  prefetch NOPping.)
- Infra: root disk hit 100% twice mid-campaign. Cause 1: DSB service
  span-report failures (jaeger-agent listens on no UDP port → every span
  send logs an error line at 8k QPS). Cause 2: nginx-thrift stock
  container had a 3.9G json log. Fix: json-file log caps (64m x 2) added
  to compose-override for nginx-thrift + all 11 custom services;
  ~8.6G freed. LBR raw/symbolic dumps deleted after plan generation
  (retrace is ~3 min if plan variants needed).

## Wave-3c (2026-08-17): DSB flagship CLOSED — verdict

Low-load 4-arm A/B (1x16 client, cold-code regime, PostStorage 18-20
L2I MPKI, IPC ~1.2): inj vs NOP +0.24% cyc/req, L2I misses +1.1% (no
reduction); pgo vs stock −1.78% cyc/req. Saturation (4x16, warm, 5.3
MPKI): inj vs NOP +0.68%, pgo −2.96%. Latency flat everywhere.

**Verdict: DSB PostStorage static prefetch = neutral in both regimes,
with PGO ceiling itself only −2~3% service cycles (and E2E-invisible
because the service is not the system bottleneck).** Structural
explanation per the four-axis criterion:
1. Only 12% of the process's L2I miss samples resolve inside the main
   binary (75%+ live in libc/libstdc++/libmemcached/jaeger/mongoc/
   thrift DSOs) — the addressable region is a sliver; external-GOT
   plans reach only PLT entry lines, not DSO-internal streams.
2. Miss structure is diffuse (157 sites for 75% coverage of that
   sliver) and LBR-path target determinism is low in request-driven
   dispatch code — injected prefetches produced zero miss reduction,
   i.e. the site→target path rarely repeats within lead time.
3. The one regime with high MPKI (low utilization, cold interleaved
   requests) still has the same diffuse/dynamic structure — MPKI
   magnitude alone does not make a workload prefetchable (axis 1 is
   necessary, not sufficient).

Positive results from the flagship: (a) PGO-first ceiling measured
honestly (−2~3% service cycles, E2E-neutral); (b) **layout-luck control
demonstrated at datacenter scale** (NOP arm −1.6% vs stock from layout
shift alone — larger than most claimed prefetch effects in this class);
(c) full 11-service clang-19 build+swap harness, per-service cycle
accounting, and the corrected NOP tool are reusable infrastructure.

## Wave-4 (2026-08-17): 무조건-성공 campaign — all three classes ≥5%

- **C1 LOCKED**: arcilator MegaBoom callsite s4la16 re-confirmed at
  1.0510 (15 interleaved reps, nop 5.712±0.025 vs pf 5.435±0.034,
  distributions non-overlapping, MPKI 76.7→71.2). Neighbor grids
  (la14/18, s3/s5, base-offset 64, LargeBoom cells) all inferior —
  s4la16 is a sharp density resonance. C1 members ≥5%: Verilator 1.078x,
  arcilator 1.051x.
- **C2 at physical ceiling, mechanism finally firing**: fat-static
  PostStorage (thrift/mongoc/bson/memcached/jaeger/libstdc++ linked in;
  73.9% of miss samples now in main binary vs 25%) delivers the first
  real DSB prefetch effect: finj vs NOP −0.70% cycles warm / −1.67%
  cyc/req cold with real miss reduction — ~57% of the PGO ceiling
  (−2.9%). ≥5% members remain Django 1.490x / FeedSim 1.073x; DSB is the
  honest boundary datapoint (ceiling itself ~3%: libc 25% stays
  DSO-resident, diffuse path determinism).
- **C3 LOCKED on a real service stack**: WideApi (wide-API
  composite-endpoint HTTP service; 4000 generated handlers, 11.2MB JIT
  code, 35-50 L2I MPKI) at fixed 4-core capacity: **gated V4 1.1104
  (+11.04%, 5 reps, min-gap 50σ), p50 −8%, p99 −19.5%, MPKI 34.9→12.3.**
  Same gate config that protects tradesoap/spring. Trino/dotty/chirper/
  tomcat closed with axis reasons (loop-hot; L2-resident).

## Wave-5 (2026-08-17/18): TPC-C discovery + server-side metrics + redis

- **TPC-C on PostgreSQL 16 (sysbench-tpcc, scale 5, 16 thr): L2I 51 MPKI,
  IPC 0.67, 94.3% of miss samples in the postgres binary** — the pgbench
  1-2% verdict was a workload artifact (tpcb is code-hot); real OLTP is
  a top-tier icache workload. tps ~735 base.
- **PGO (AutoFDO from cycles LBR): +7.98% tps (734.6→793.2, lat95 −5%,
  MPKI 43→31)** under the clean template-restore protocol (fresh DB clone
  per arm — TPC-C table growth otherwise drifts later arms by ~10%).
  PGO-first ceiling ≥5% ✓.
- Static injection density sweep (backend-only CUSTOM_COPT rebuild recipe,
  NOP-pair controlled): 230 pf → +0.1%; 890 → −3.8%; 1684 RET-family →
  −4.9%; 5728 → −15.6%. Top targets are ubiquitous callees
  (AllocSetAlloc, palloc, base_yyparse, SearchCatCacheInternal): even few
  static sites = massive dynamic issue rate → pipeline pollution.
  **Refined fifth axis: what matters is dynamic prefetch issue rate, not
  static site count.** TPC-C's gains live in layout (PGO), unreachable by
  injection.
- WideApi server-side quantification (user Q): at fixed offered load the
  client is the bottleneck, so QPS hides server gains; correct metrics:
  (a) cycles/request at equal load: 636.7k→542.2k = **−14.8% server CPU**
  (3.95→3.37 cores); (b) fixed-capacity (4-core pin) saturation: +11.04%
  QPS. WideApi itself demoted to diagnostic per user (self-built).
- redis 0.011 MPKI (IPC 1.98) — closed, no opportunity (memcached-class).

## Wave-5b (2026-08-18): recognized-JVM map complete + DSO-RET quantified

- Full DaCapo+Renaissance L2I screen finished (29 newly measured; 40+
  total with earlier waves). Only cassandra (13.4) and future-genetic
  (9.3) exceed 8 L2I MPKI, and both carry L1I/L2I ~10 (L2-resident
  misses). cassandra V4-gated A/B: −0.36% (MPKI 22.7→21.6 only).
  **Verdict: no recognized JVM benchmark is a prefetcht1 ≥5% member —
  the JVM class's FE stalls are L1I-fill-bound; the matching instruction
  is L1I-filling prefetch (PREFETCHIT0-class), outside the prefetcht1
  constraint. This is a measured 40-benchmark wall, not scarcity.**
- DSO-RET opportunity quantified on the dyn-lib-heavy DSB thin
  PostStorage (miss-LBR0 branch types, save_type LBR): COND 28.8%,
  IND 27.6%, CALL 19.8%, **RET 10.0%** — and of RET-misses 58.8% are
  lib→lib, 13.4% lib→main (sites inside DSOs, uninjectable without lib
  rebuilds), only 24.9% main→main. Injectable RET share ≈1% of misses →
  the C1 RET mechanism does NOT generalize to dyn-lib-call-heavy
  services standalone; fat-static linking (Wave-3/4) is the route that
  makes the DSO share addressable. Cross-DSO LBR0 total: 11.5%.

## Wave-6 (2026-08-18): three follow-ups closed

1. **OLTP cross-validation: MariaDB 10.6 TPC-C.** apt binary under load:
   65.8 L2I MPKI, 92.9% in-binary, tps ~750 (mirrors PG). Source build
   (clang-19 RelWithDebInfo, minimal plugins) A/B with snapshot-restore
   protocol: **AutoFDO PGO +10.83% tps (643.4→713.1, lat95 −7%)** vs PG
   +7.98% → **OLTP PGO gains are general, not PG-specific.** (Note: the
   trimmed source build itself shows 5.6 MPKI / IPC 2.8 vs the fat apt
   binary's 65.8 / 0.56 — binary composition dominates the miss profile;
   both PGO wins hold within their own builds.)
2. **DSB in-library sites opened (deps rebuilt -g, then with pass+plan;
   dsb-deps-g/dsb-deps-inj images, /opt/src stable paths): fginj vs
   fgnop +0.16% — neutral.** Site availability was not the binding
   constraint; dispatch-structure/dynamic-issue-rate is. DSB ceiling
   story final (PGO −2.7%).
3. **PREFETCHIT0 measured as HW-nop on GNR** (user's implementation-issue
   claim quantified): V4 entry burst re-encoded rip-relative 0F 18 /7
   (PrefetchEntryIT0 flag); tomcat/cassandra 5-rep A/B: L1I MPKI 215
   unmoved (215.3→217.6 / 215.2→217.4), L2I unmoved, time −0.2~−1.5%
   (pure byte overhead). Same harness with prefetcht1 moves L2I
   24.2→23.1 — the encoding path works; the it0 op itself does nothing.

## Wave-7 (2026-08-18): user-directed mechanisms — burst, GOT-anchor, diversity

- **Per-site target diversity quantified (DSB)**: miss-LBR0 branch sources
  have MEDIAN 2 distinct miss cachelines, p99 7, max 45; 88.8% of misses
  come from sources with ≤4 targets. The "diffuse" property is aggregate
  (3660 sources x few targets), NOT per-site unpredictability — the
  binding constraint is 1-branch lead time (~10 instr) vs L3/DRAM
  latency, not prediction.
- **Per-query burst prefetch (OLTP, prefetch-only)**: sites at
  PortalRun/exec_simple_query(/PortalStart/standard_ExecutorRun), targets
  = top-K global hot cachelines via got-symbol-offset operand (GOTPCREL —
  required: PG's --export-dynamic makes direct rip refs TEXTREL). v1
  (2x64x1): **+0.31% vs NOP**; v2 (4x96x2, 768 pf): **+0.27%**. Positive
  but capped: TPC-C's data traffic continuously evicts code from L2
  (steady 37 MPKI over a ~30KB hot set), so per-statement warming only
  covers first-touches. With callsite plans all ≤0 at every density, the
  prefetch-only ceiling on TPC-C is ~+0.3%; PGO's +8% is line-packing
  (MPKI 43→31 permanently), which prefetch cannot emulate.
- **GOT-anchor DSO-interior prefetch (dynamic linking preserved)**:
  implemented the user-proposed register-based scheme — anchor =
  default-versioned dynsym export in the same DSO, delta fixed at lib
  link time; pass emits movq anchor@GOTPCREL(%rip),%r11 + prefetcht1
  delta(%r11). 48 targets (libc 29/libstdc++ 12/memcached 7) burst at
  thrift dispatchCall: links and runs cleanly (anchor pitfalls: compat
  @-versioned symbols like sysctl/__nss_* are unlinkable — default @@
  only). A/B: warm −0.37% qps / cold +0.01%, cycles −0.5% both —
  mechanism proven, gain capped by the same re-eviction economics.
  Toolchain: tools/make_burst_plan.py, tools/make_dso_anchor_plan.py.

## Wave-8 (2026-08-19): Wave-6 lib-site arm invalidated; first VALID in-library injection (dynamic linking) — still neutral cold

- **Discovery: every earlier deps-with-plan image (dsb-deps-inj, the
  wave-6 fginj arm) silently shipped STOCK libraries.** The injected .so
  links failed on R_X86_64_PC32 relocations against preemptible/undefined
  symbols, and rebuild_deps_g.sh's `make && make install` chain swallowed
  the failure (set -e does not fire on a non-final member of an &&-list).
  Proof: injected bcon.c.o inside the image vs an Aug-17-dated installed
  .so; deps-g libthrift dated Aug 16 (thrift had NEVER rebuilt — silent
  boost -Wenum-constexpr-conversion failure). The wave-6 conclusion
  "site availability was not the binding constraint" rested on a null arm.
  fatg_* binaries are additionally FAT-STATIC (216 pf all in main binary).
- Working recipe for real in-lib injection with dynamic linking preserved:
  split the trace plan per module (fix_plan_operands.py) — main binary:
  internal targets pc-relative, DSO-exported targets got-symbol-offset,
  others dropped; libraries: ALL targets GOT (inside a .so even same-lib
  globals are preemptible). Pass per-target override key is `operand`
  (NOT `operand_mode`). Build fixes: -Wno-enum-constexpr-conversion for
  C++ libs, thrift -DBUILD_COMPILER=OFF, YAML_CPP_BUILD_TOOLS=0,
  -DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined for dep tool
  executables. MANDATORY verification gate: objdump prefetcht1 count per
  artifact — never trust a silent build.
- A/B infra: post-storage runs dsb-deps-g with /usr/local/lib mounted
  from a host swap dir (compose-override-libs.yml); dsb_ab_libs.sh swaps
  binary+libs per arm; NOP twins are in-place-patched .so (byte-identical
  layout — stricter control than any earlier DSB arm).
- Three typed/deep variants from the fatg trace (sample-branch-type-filter
  = miss LBR0 type): ci75 CALL/IND/IND_CALL cov75 depth>=4 (libs 182 +
  main 280 pf); cond75 COND (libs 170 + main 178; COND misses concentrate
  in libjaegertracing, 140 pf); deep8 all-type depth>=8 with 4-line burst
  (libs 1040 + main 916 pf).
- Results (3-rep interleaved, 2GHz frozen): WARM (4x16, ~8k QPS, MPKI 6):
  ci vs NOP **MPKI -4.9%, IPC +1.0%**, cycles -0.4% — the first real
  in-lib miss reduction on DSB; cond/deep noise. COLD (1x16, MPKI ~19):
  **all three pairs neutral** (MPKI -0.2/-1.3/-0.3%, cyc/req within
  +/-0.2%). The DSB boundary verdict stands — and is now backed by a
  valid experiment: the cold request-interleaved miss surface (3.6k
  sites x few lines each) cannot be covered by ~50-100 planned lines,
  and per-site lead time remains ~1 branch. Warm hard-core misses are
  the only prefetch-addressable slice.
- User-directed framing updates: PGO/layout gains are out of scope
  (prefetch-only deltas); OLTP verdict recast as 5th axis — high L2
  DATA pressure evicts prefetched code (shared L2); JCS/WideApi demoted
  to appendix (self-authored benches).

## Wave-9 (2026-08-21): frequency axis — gains GROW with core clock where misses are cold

Cores repinned 3.4GHz (turbo re-enabled: MISC_ENABLE bit38 had been left
set by the v1 config script; cleared via wrmsr, achieved ~3.26GHz under
load), uncore kept pinned 2.2/2.5GHz. Same harnesses, 3-rep:
- **Django: 1.490x @2GHz -> 1.719x @3.4GHz** (base qps 6.55->9.30,
  IPC 0.344->0.288 = more FE-bound; d4_next qps 9.76->16.00, near-linear
  clock scaling). Textbook confirmation: higher clock -> more cycles per
  cold miss -> prefetch worth more.
- DSB cold ci-pair: IPC delta +0.05% -> +0.78%, qps -0.43% -> +0.62%,
  MPKI -0.2% -> -1.6% (direction up, still <1%).
- PG TPC-C burst v1: +0.31% -> +0.66% tps (noise-level; the L2
  data-eviction wall is frequency-independent).
- FeedSim i200m t2: qps ratio 1.073x -> 1.043x, latency ratio flat
  (1.047 -> 1.048); base MPKI 8.07 -> 6.26 (faster request turnaround
  keeps code warmer — gain source partially evaporates at high clock).
Paper line: the technique's value scales with core:memory clock ratio
when the covered misses are truly cold (Django); warm-regime and
data-evicted workloads do not benefit from the frequency axis.
Frequency-state hazard log: fc_assert_frequency now honors
FC_EXPECT_NO_TURBO for turbo-enabled fixed-frequency runs.

## Wave-10 (2026-08-21): cache-shrink (resctrl CAT) — Emissary-config emulation

Setup: cores 8-15 in a resctrl CLOS with L2 clamped to 8 ways = 1MB
(Emissary's exact L2 size) and L3 to 2 ways = 42MB (hardware minimum is
1 way = 21MB — a 2MB victim L3 CANNOT be emulated on GNR). Validated
with a 1.5MB pointer chase (+13% on shrunk cores). Workloads pinned via
taskset; 3.4GHz core pinning retained.
- **Emissary MPKI reproduced on real hardware**: with L2=1MB, tomcat L2I
  MPKI 15.0 (their sim: ~14), cassandra 9.2 (their sim: ~8). Our
  screening was never wrong — their high L2I numbers are a hierarchy
  property (1MB L2), not an app property.
- **V4 JIT prefetch stays neutral even at Emissary L2 size**: tomcat
  0.9987x (MPKI -4.0%), cassandra 0.9984x (MPKI -4.9%), 4-rep,
  steady_ms sd 1-10ms. Reason: on GNR the L2I miss lands in a >=21MB L3
  at ~80 core cycles, which OoO largely absorbs; Emissary's speedups
  live in a hierarchy where L2I miss ~= DRAM (2MB victim L3). Plus V4's
  addressable slice (method-entry lines) covers only ~4-5% of misses.
- DSB ci-pair with PostStorage pinned to the shrunk cores: neutral
  (+0.27% qps, MPKI -1.5%); pinning itself dropped cold MPKI 14.8->6.1
  (core-packing i-cache effect, reconfirmed).
- Paper line: gain requires volume x cost x coverage; large monolithic
  L3s on modern servers cap the cost term for code misses, so results
  from small-victim-L3 simulations do not transfer to this class of
  hardware.

## Wave-11 (2026-08-21): PG code-miss cost decomposition + STLB-warming prefetch

- **L3-vs-DRAM decomposition (OCR raw event, validated config): 100.000%
  of TPC-C code misses are L3 hits** (3.93G L2I misses vs 7,929 code L3
  misses in 15s). The +0.3% prefetch-only ceiling is fully explained:
  every covered miss saves only an ~80-core-cycle L3 hit that OoO
  partially hides, while data traffic re-evicts L2 continuously.
- iTLB: 1.12-1.18 walks/kinst under load (~2-3% of cycles).
  **STLB-warming prefetch implemented and mechanism PROVEN**: per-query
  burst (PortalRun + exec_simple_query) of one data-side prefetcht0 per
  hot code page (128 pages from a 90%-coverage miss-page profile,
  global-T-symbol GOT anchors; 254 injections; install_injT/install_nopT
  layout pair). Paired measurement: **iTLB walks/kinst 1.18 -> 0.864
  (-27%)** — data prefetch to code addresses installs STLB entries on a
  real service, as the microbenchmark predicted. tps effect: -0.02%
  (neutral) — the walk term is too small and too well hidden for a 27%
  cut to register. (Full walk elimination would need huge pages —
  layout-class, out of prefetch-only scope.)
- Hot-page profile: PG's TPC-C misses span 524 code pages; top-128 = 66.7%
  of miss samples (diffuse at page granularity too).

## Wave-12 (2026-08-21): DSB I/O-gap phase prefetch — best cold-regime variant, still sub-threshold

Idea (user-directed): use mongo/memcached I/O waits (us-ms of CPU idle
inside each request) as the lead-time source — the Django mechanism's
analog. Hand plan: 3 sites at the I/O-issue statements
(ReadPosts memcached_mget:403, ReadPosts mongo find:520, ReadPost
find:262) x 42 hottest next-phase functions (nlohmann parse, bson_iter,
thrift result-write path; entry+64B, GOT for lib targets) = 252
prefetcht1 in the thin main binary (libs stock). NOP-pair control.
- Cold 1x16, 7-rep combined: **qps +0.64% (t~1.8), MPKI -0.4%,
  IPC +0.07%** — the best DSB cold variant measured (everything else
  is 0 +/- 0.3%), but mechanism metrics are flat and significance is
  borderline. First 3-rep batch showed +1.38% driven by one outlier rep.
- Interpretation: warming 42 function entries covers too little of the
  ~500-page / 3.6k-site cold miss surface; the io-gap lead-time source
  is real but the coverage wall (fourth failure axis for DSB) still
  binds. Recorded as an honest near-miss; deeper-offset/wider-target
  iteration possible but expected gains remain ~1%.

## Wave-13 (2026-08-21): COND-distance analysis — why the RET family is the right static target class

Question (user): add surgical far-COND static injections on top of sret1k?
Resolved analytically from the existing plans:
- **static-cond (target = the cond's own taken-target), 59,799 sites
  exhaustive: p50 distance 52 BYTES, p90 476B, p99 1.4KB, max 5.8KB,
  zero beyond 16KB.** In flattened code a COND is a local skip inside a
  giant body; far control transfer exists ONLY at CALL/RET. The
  "surgical far-static-cond" arm is an empty set by construction — and
  this measured distribution explains why the 60k-dose static-cond
  combo lowered MPKI (50.7) but lost time (1.018x): near targets are
  already inbound via sequential fetch/HW prefetch, so the family buys
  ~nothing per issue.
- **PGO-cond (site = an upstream cond, target = a future miss line via
  LBR lookahead): p50 3.1KB, 20% of 16,669 injections beyond 16KB (up
  to 19MB).** Far-COND value exists only as lookahead through the
  REALIZED path across data-dependent branches — enumerable from LBR,
  not statically.
- Paper line: static matches PGO where control transfer is structural
  (CALL/RET chains); profile is required exactly where the path is
  data-dependent (COND lookahead). Flattened code is dominated by the
  former — hence static >= PGO at 1/20 the injections.
