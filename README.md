# PrefetchIT — `prefetcht1`로 하는 소프트웨어 명령어 프리페치

> 이 문서가 저장소 전체 설명서입니다. 해야 할 일은 [`docs/TODO.md`](docs/TODO.md),
> 호스트 복구 절차는 [`docs/SETUP.md`](docs/SETUP.md). 나머지 문서는 각 컴포넌트의
> 설계 노트뿐입니다(아래 "문서 지도").

## 1. 무엇을 하는 프로젝트인가

Intel Granite Rapids(Xeon 6787P)에서 ISA의 명령어 프리페치 `prefetchit0/1`은 측정상
아무 효과가 없다(iTLB/STLB도 안 데우고 L1I/L2I miss도 안 줄어듦, 1단계 마이크로벤치와
tomcat/cassandra 실측). 대신 **데이터 프리페치 `prefetcht1`을 코드 주소에 발행**하면
곧 실행될 코드 라인을 L2까지 미리 끌어올 수 있다. 이 저장소는 그 명령을 *어디에*
넣어야 datacenter 워크로드가 빨라지는지를 다룬다.

### 용어 — 반드시 이 뜻으로만 쓴다

| 용어 | 뜻 | 금지 |
|---|---|---|
| **PGO / trace-guided (profile-guided *placement*)** | PEBS+LBR trace(`L2I_CODE_RD_MISS`)로 *어느 캐시라인이 miss나고 어느 분기가 그 앞에 오는지*를 보고 **prefetch 주입 위치/대상만** 정하는 것. 코드 자체·레이아웃은 그대로. | — |
| **static** | trace 없이 바이너리 구조만 보고(호출 그래프, 함수 크기, 분기 밀도…) 같은 plan을 만드는 것. 목표: PGO plan과 같은 효과. | — |
| **manual** | 제어흐름을 담고 있는 자료구조(함수 포인터 배열, 디스패치 필드)를 소스 1–2줄로 미리 읽어 *다음* 타깃을 prefetch. | — |
| ~~layout PGO~~ | AutoFDO(`-fprofile-sample-use`), `-fprofile-use`, BOLT, Propeller 등 **코드 배치를 바꾸는 최적화** | **사용 금지.** 비교 기준으로도 쓰지 않는다. 과거 DSB/TPC-C/MariaDB의 "AutoFDO ceiling" 수치는 모두 폐기했다. |

효과는 항상 **prefetch만의 순효과**로 보고한다: 같은 바이너리에서 prefetch 명령을 같은 길이의
NOP으로 치환한 *NOP twin* 대비, 코어·언코어 클럭 고정, 인터리브 ≥3회.

## 2. 네 단계 흐름과 현재 상태

```
1. microbench   icache_microbenchmark/   prefetchit == no-op, prefetcht1 == 유효, 리드타임 부족하면 버려짐
2. static pass  profiling/ (trace) → llvm_prefetchit/tools/prefetchit_trace_to_plan.py  ┐ plan (prefetchit.plan.v1)
                static_prefetch/tools/static_plan.py --kinds ret,cond               ┘  → LLVM pass 주입 → NOP twin A/B
3. manual       llvm_prefetchit/scripts/dispatch/  (DCPerf Django/FeedSim 소스 패치 변형 빌드 + 측정)
4. JVM          jit_prefetch/  (HotSpot C2가 prefetcht1을 직접 emit; V4 entry burst)
```

| 단계 | 워크로드 | 기준값(2026-08/09) | 2026-09-15 재검증 (동일 호스트, 재빌드) | 상태 |
|---|---|---|---|---|
| 3 | Django (DCPerf **v1**, ICacheBuster) | 1.490x, MPKI 84.6→35.0 | 1.463x (2 GHz) | **폐기** — DCPerf v2가 ICacheBuster를 제거(2026-09-19); v2 Django는 2.4 MPKI |
| 3 | FeedSim (DCPerf **v1**) | 1.073x, MPKI 8.1→1.7 | MPKI 7.8→1.4 | **폐기** — v2(feedsim_dlrm)는 2.1–2.3 MPKI, 코드가 다름 |
| 4 | JCodeStream | 1.285x @3.8 GHz | **1.101x @2 GHz**, MPKI 72→22 | 방향 재현 |
| 4 | WideApi | 1.110x | **1.109x**, p99 −19% | 재현 |
| 2 | Verilator qsort — PGO(trace) RET cov90 | 1.076x | **1.021x vs NOP twin**, MPKI 57.1→53.3 (−6.6%); 09-16 재측정 1.011x/1.021x | miss 감소는 재현, 시간 이득은 2% |
| 2 | Verilator qsort — static top1k callsite | 1.078x | **1.003x** (top5k/nested/mixed도 ≤1.003x); call 단위 RET v3(7,562 call, 4라인) 1.001x/1.014x | **재현 안 됨** — continuation만 노리는 방식의 한계(아래 §2-1) |
| 2 | **Verilator qsort — static sequential lookahead (2026-09-16 신규)** | — | **1.149x vs base / 1.236x vs NOP twin**, MPKI 56.9→13.7 (D=4 KB, 70 B마다 + callee burst 4라인, 함수 집합 자동 선택); 명령 +4%인 K=40 계열도 1.145x; dhrystone/median/towers 동일, full run 1.139x | **PGO RET ceiling(1.02x)을 static이 7배 넘음** → §2-1 |
| 2 | arcilator DualMegaBoom — **static sequential lookahead** | (MegaBoom callsite s4la16 1.051x) | **1.543x vs base / 1.683x vs NOP twin**, MPKI 79.1→35.4 (D=4 KB K=10, 20k 사이클, 3회; K=20 1.504x; `flat_codegen/results/arc_seq_20260916.csv`) | 8월에 'saturation 영역'으로 분류했던 워크로드가 seq로 최대 이득 |
| 1 | microbench | prefetchit no-op | 바이너리만 재빌드 | — |

### 2-0. 한 자리수 MPKI 워크로드의 PGO/static 검증 결론 (2026-09-16 저녁)

`llvm_prefetchit/results/pgo_static_20260916/summary.md` (실제 런타임 speedup vs base, 3회, 3.8 GHz, `:u`):

| 워크로드 | base MPKI | 최선 arm | speedup | MPKI |
|---|---:|---|---:|---|
| CXXRTL picorv32×48 (flattened) | 2.95 | static seq D=4 KB K=80 | **1.025x** | 2.95 → 0.94 |
| SPEC2026 723.llvm_r | 1.55 | PGO lean (cov50, 1 site) | 0.999x | 1.55 → 1.54 |
| SPEC2026 721.gcc_r | 1.11 | PGO lean | 0.986x | 1.11 → 1.09 |
| WordPress php-fpm(자체 빌드) | 0.20 | — (arm 무효) | — | — |
| MariaDB durable (user) | 3.2 | — (PGO arm 빌드 불가) | — | — |

결론: 한 자리수 MPKI에서 유의미한 이득은 flattened 코드(CXXRTL)에서만, 그것도 저밀도 seq로 2.5%다. 일반 코드에서는 trace-guided placement가 (a) 넉넉한 plan이면 hot loop 사이트 때문에 동적 명령 수가 ×1.9–2.9로 늘어 크게 느려지고(0.46x/0.25x), (b) 마른 plan이면 MPKI가 안 움직인다. 멀티 타깃 빌드(MariaDB)에서는 IR pass 주입 자체가 링크를 깨뜨린다.

### 2-1. 2026-09-16 static pass 대수술 — miss는 "분기 target"이 아니라 "순차 코드 스트림"이었다

`static_prefetch/tools/ret/{ret_producing_call_truth,miss_stream_characterization}.py`로 PEBS **sample IP**를 LBR[0].to와 비교한 결과
(raw `verilator_repro_20260915b` trace 3개 = 09-16 재수집 trace 3개, 분포 ±0.5 pt 일치):

| 관찰 | 수치 |
|---|---|
| RET miss의 sample IP가 continuation 라인에 있는 비율 | **30%** (15%는 +1라인, 25%는 +16라인 이후) |
| CALL miss가 callee 첫 라인에 있는 비율 | 47% (나머지는 callee 본문을 따라 흐름) |
| 분기 종류 | COND 68% / CALL 15% / UNCOND 9% / RET 7.5% — 마지막 taken branch의 **라벨**일 뿐 |
| 시뮬레이션 1사이클당 L2I miss | ~64.5k ≈ 사이클당 실행되는 ~4 MB 코드의 **거의 모든 라인** |
| RET miss를 만드는 call(정적으로 유일: LBR[0].to 직전 call) | 2,025개, 상위 1,000개가 88%; callee = nba_sequent 73%, memset@plt 20%, memcpy 5% |

1단계 마이크로벤치(`icache_microbenchmark/microbench/seq_stream/`)가 원인을 확정: 16 MB 직선 코드 스트림에서 HW prefetcher만으로는
MPKI 71 / IPC 0.41(Verilator와 같은 영역)이고 NOP twin은 base와 동일한데, **`prefetcht1 D(%rip)`를 64 B마다 넣으면 D=4–8 KB에서 3.3x**,
128 B 간격도 D=4 KB면 동등. 즉 데이터센터 규모의 flattened 코드에서는 *다음에 실행될 코드 스트림*을 소프트웨어가 앞서 끌어와야 한다.

그래서 pass에 plan/profile이 전혀 없는 두 모드를 추가했다(`llvm_prefetchit/docs/design.md` "Plan-Free Modes"):
- **sequential lookahead** `-prefetchit-seq-distance=D -prefetchit-seq-stride-insns=K`: 선택 함수(regex, 또는 `static_prefetch/tools/seq/select_seq_functions.py`가 뽑은 "main 루프에서 도달 가능한 함수" 목록 → `-prefetchit-seq-functions-file`; 둘 다 miss의 97.4% 커버, 결과 동일)의
  K번째 IR 명령마다 `prefetcht1 D(%rip)`. 상수 rip 상대 오프셋이라 **레이아웃 drift·재앵커링 문제가 원천적으로 없음**. K=20 ≈ 70 B, K=40 ≈ 138 B 간격.
- **callee-entry burst** `-prefetchit-callee-burst-lines=L`: 직접 call 직전에 callee+0..64·(L−1) prefetch(caller 스트림이 못 미치는 callee 첫 라인용).

Verilator DualMegaBoom qsort, 3.8 GHz 고정, 인터리브 3회, 100k 사이클(`results/static_overhaul_20260916/measure/`):

| variant | prefetch 수 | 명령 수 | vs base | vs NOP twin | twin vs base | L2I MPKI |
|---|---:|---:|---:|---:|---:|---:|
| base | 0 | — | 1.000x | — | — | 56.9 |
| PGO(trace) RET cov90 | 14k | +0.9% | 1.011x | 1.021x | 0.991x | 53.2 |
| static RET v3 callsite (call 단위, 4라인) | 28k | +0.8% | 1.001x | 1.014x | 0.988x | 55.9 |
| callee-entry burst만 (8라인) | 21k | +0.9% | 1.034x | 1.048x | 0.987x | 46.7 |
| seq D=1 KB K=20 | 269k | +6.4% | 1.066x | 1.131x | 0.943x | 22.1 |
| seq D=2 KB K=20 | 269k | +6.4% | 1.129x | 1.199x | 0.942x | 15.9 |
| seq D=4 KB K=20 | 269k | +6.4% | 1.142x | 1.211x | 0.944x | 16.6 |
| seq D=8 KB K=20 | 269k | +6.4% | 1.144x | 1.215x | 0.941x | 17.4 |
| **seq D=4 KB K=20 + burst 4라인** | 280k | +6.8% | **1.148x** | **1.230x** | 0.933x | 14.0 |
| **같은 설정, 함수 집합을 `select_seq_functions.py`로 자동 선택(regex 없음)** | 366k(콜드 코드 포함) | +6.7% | **1.149x** | **1.236x** | 0.929x | 13.7 |
| seq D=4 KB K=30 + burst 4라인 | 185k | +4.8% | 1.146x | 1.203x | 0.952x | 15.9 |
| callee-entry burst만 (4라인) | 11k | +0.5% | 1.025x | 1.028x | 0.997x | 50.8 |
| seq D=4 KB K=20 + burst 8라인 | 292k | +7.3% | 1.144x | 1.235x | 0.926x | 12.1 |
| seq D=4 KB K=40 | 132k | +3.3% | 1.131x | 1.170x | 0.967x | 22.3 |
| seq D=4 KB K=40 + burst 4라인 | 143k | +3.8% | 1.141x | 1.187x | 0.962x | 18.7 |
| **seq D=8 KB K=40 + burst 8라인** | 154k | +4.2% | **1.145x** | 1.198x | 0.956x | 16.9 |
| seq D=4 KB K=80 | 60k | +1.4% | 1.095x | 1.115x | 0.982x | 34.1 |

일반화 검증(같은 바이너리 seq D=4 KB K=20, 3회): **dhrystone 1.143x / median 1.144x / towers 1.143x**(qsort 1.142x — payload와 무관, 시뮬레이터 비용은 디자인이 결정);
**full 538,240 사이클 1회: 1.139x vs base / 1.213x vs twin**(226 s vs 258 s). arcilator DualMegaBoom(20k 사이클, 3회): D=4 KB K=20 1.504x/1.587x,
**K=10(≈50 B 간격) 1.543x / 1.683x vs twin, MPKI 79→35**; D를 16 KB로 늘려도 추가 이득 없음.

읽는 법: 순효과(vs twin)는 K=20에서 1.21x로 포화하고, 삽입 명령 자체가 명령 수 증가분만큼 시간을 잡아먹는다(twin 열). 그래서 D는 4 KB 이상,
밀도(K)와 burst가 튜닝 축이다. RET v3는 operand가 정확(0/64/128/192 각 24.5%)한데도 MPKI를 1.7%만 줄였다 — continuation 라인만 노리는
callsite 계열은 원리적으로 스트림을 못 덮는다(TODO 1-A는 이 결론으로 종결).

Verilator 재검증(09-15)에서 드러난 파이프라인 결함(모두 수정·기록):
1. pass가 `sym+off` 절대 오프셋으로 target을 적는데, 주입 자체가 함수 코드 배치를 바꿔 k번째 사이트의
   target이 최대 수 KB 어긋났다(1,968개 중 13개만 제자리) → pass 내 보정 + **링크 후 재앵커링**
   (`tools/reanchor_prefetch_targets.py`: 함수 내 k번째 call 기준, 2000/2000 정확) + `check_prefetch_drift.py` 게이트.
2. 같은 소스 라인에 call이 여러 개면 모든 사이트가 첫 IR 후보로 몰림 → baseline 오프셋 순위로 매핑.
3. **static 사이트 선택 자체가 약함**: 핫한 return 라인은 62% 맞히지만 그 라인으로 실제 return하는
   call은 15%만 고름(가능 최대 65%). 그래서 static plan이 무효. 이것이 2단계의 핵심 미해결 과제.

raw 데이터: `llvm_prefetchit/results/repro_20260915/`(3·4단계), `llvm_prefetchit/results/verilator_repro_20260915b/`(2단계: trace, plan, resolved plan, 바이너리, NOP twin, `measure/runs.csv`).

### 2-4. 2026-09-18~19: 현실적 세팅 스크리닝과 miss 원인 분류 → `docs/prefetch_plan_by_miss_class.md`

코어 고정 + 현실적 부하로 DCPerf v2·DaCapo/Renaissance·CloudSuite 4·DeathStarBench 3종·μSuite·PostgreSQL/MariaDB를 다시 스크린하고, 서버 코어의 C6를 끄고 다시 재서
miss를 cold(C6 wake)·capacity·interleaving으로 분류했다. 결론과 두 부류별 해결 계획은 `docs/prefetch_plan_by_miss_class.md`에 있고, 원자료는
`llvm_prefetchit/results/realistic_screen_20260918/{SUMMARY.md,FINAL_TABLE.md,C6OFF_TABLE.md}`(스크립트 사본 `llvm_prefetchit/scripts/platform/screens/realistic/`)다.

요지: 고정 코어·저활용률의 큰 MPKI(10–110)는 유휴 코어의 C6 진입으로 L2가 비워진 cold miss라 설정으로 사라진다(PG 18.5 → 0.06). C6를 꺼도 남는 것은
(A) capacity — flattened 시뮬레이터(Verilator 57, arcilator 79), DCPerf v2 Django 2.4/FeedSim 2.3, media C++ 서비스 alone 2–5, JVM 1–3(도구 밖) — 와
(B) interleaving — 스택을 8/16코어 pool에 올리면 C++ 서비스가 34–55 MPKI(media), 4–44(socialNetwork), Go 3–16 — 두 부류다.

## 3. 저장소 지도

각 디렉토리는 별도 git 저장소다(umbrella는 문서만 추적). 매니페스트: `llvm_prefetchit/migration/repos.lock.tsv`.

| 디렉토리 | 원격 | 단계 | 내용 / 진입점 |
|---|---|---|---|
| `icache_microbenchmark/` | icache_microbenchmark (`prefetch_benefit` 브랜치) | 1 | `microbench/src/` `make all prefetch_test`; `run_process_prefetch_experiment.py` |
| `profiling/` | frontend_profiling | 2 | `run_pebs_sampling.sh`(PEBS+LBR), `analyze_pebs_trace.sh`(symbolize), `run_detailed_profile.sh`; `runscript/bench/bench_common.sh`(Verilator 환경) |
| `static_prefetch/` | static_return_prefetch (cond 저장소 병합됨) | 2 | **`tools/static_plan.py --kinds ret\|cond\|ret,cond`**; 엔진 `tools/ret/`, `tools/cond/`; 알고리즘 노트 `docs/` |
| `llvm_prefetchit/` | llvm_prefetchit_injection | 2·3·공통 | pass `lib/PrefetchITPass.cpp`; plan 도구 `tools/`; `scripts/platform/`(클럭 고정·pinning·L2I 스크린), `scripts/static/`(**`run_verilator_repro.sh`**), `scripts/dispatch/`(Django/FeedSim/memcached); `migration/`; 과거 캠페인 스크립트 `archive/` |
| `flat_codegen/` | flat_codegen | 2(+3) | arcilator(두 번째 flattened-code 워크로드) 빌드/주입 스크립트; DeathStarBench 빌드·A/B 도구 |
| `jit_prefetch/` | jit_prefetch | 4 | HotSpot 패치 `patches/`(V1–V4), `scripts/ab_jcs.sh`, `ab_jvm_suite.sh`, `wideapi/`; `docs/PLAN.md`(C2 설계 노트+실험 기록) |
| `benchmarks/`, `worktrees/`, `.tmp/`, `.cache/` | 서드파티, 미추적 | — | `benchmarks.lock.tsv`에 고정; DCPerf·chipyard·JDK 등 |

### 2단계 파이프라인(가장 중요)

```
baseline 바이너리(clang-19 -O3 -g)  ──perf record L2I_CODE_RD_MISS:upp -b──►  trace ×3  ──►  analyze_pebs_trace.sh
   │                                                                                            │
   │           trace 사용 (PGO)  prefetchit_trace_to_plan.py --sample-branch-type-filter RET ... ┤
   │           trace 미사용     static_plan.py --kinds ret --ret-top-k 1000 --ret-site-strategy callsite ┘
   ▼                                                                      ▼
   같은 소스 + opt -passes=prefetchit-inject -prefetchit-plan=plan.json  (run_prefetcht1_l2_eval.sh EXTERNAL_PLAN=)
   ▼
   resolve_plan_layout_shift.py → reanchor_prefetch_targets.py(k번째 call 기준) → check_prefetch_drift.py(≥90% 통과)
   ▼
   make_nop_control_binary.py → NOP twin  ──►  freeze_platform.sh MODE=3.8ghz → 인터리브 3회 (run_verilator_repro.sh STEP=measure)
```
`scripts/static/run_verilator_repro.sh STEP=traces|plans|build|nop|measure`가 위 전체를 수행한다
(빌드는 단일 TU clang -O3라 변형당 ~35분).

### 3단계 (manual)

**폐기(2026-09-19)**: 아래 스크립트는 DCPerf v1의 ICacheBuster 코드를 대상으로 했고, v2에서 그 코드가 제거되었다. v2는 `benchmarks/dcperf_v2`와 `docs/prefetch_plan_by_miss_class.md` A 부류 절차를 따른다.


`scripts/dispatch/build_{feedsim,django}_*_variants.sh`로 `ICACHE_BUSTER_PREFETCH_DISTANCE/NEXT_LINE`
매크로 변형을 만들고 `run_feedsim_closedloop.sh`, `run_django_manual.sh`로 측정(스레드별 코어 pin,
affinity 감사, `valid` 열). memcached는 중립(대조군으로 유지).

### 4단계 (JVM)

`jit_prefetch/openjdk`(jdk17u-dev + `openjdk-prefetch-combined.patch`) 빌드 후 JVM 플래그로 A/B:
`-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256`(V4 gated).
`ab_jcs.sh`, `ab_jvm_suite.sh SUITE=dacapo BENCH=tomcat`, `wideapi/ab_wideapi.sh`.

## 4. 측정 규칙 (위반 시 결과 무효)

1. `sudo MODE=2ghz|3.8ghz llvm_prefetchit/scripts/platform/freeze_platform.sh` — 코어 min=max, 터보 상태 명시, 언코어 min=max. 기본 DVFS는 prefetch arm에 ~17%의 언코어 크레딧을 준다(과거 1.22x의 정체).
2. 한 번에 한 워크로드, 측정 중 빌드 금지, 스레드마다 물리 코어 하나(`platform/campaign_common.sh`).
3. 반드시 NOP twin과 비교(`make_nop_control_binary.py`), `objdump`로 주입 개수 확인, callsite/RET plan은 `check_prefetch_drift.py` ≥90%.
4. 인터리브 ≥3회(서비스는 5회), 중앙값 보고. 완료 작업량 동일(`+max-cycles`, 요청 수) 확인.
5. 레이아웃을 바꾸는 최적화는 어느 arm에도 넣지 않는다.
6. **세팅(2026-09-19)**: 워크로드를 코어에 고정하고 사용 코어의 C6를 끈다(cold miss는 대상이 아님); 서비스는 alone/interleaved 두 regime을 모두 재고, 부하는 벤치마크 기본 config의 현실 범위로 둔다. 상세 `docs/prefetch_plan_by_miss_class.md` §0.

## 5. 워크로드 카탈로그 (지금까지의 결론과 재시도 출발점)

스크린 기준: 부하 상태 L2I MPKI ≥ 한 자리 수 → trace-guided plan으로 ceiling 확인 → static.

| 워크로드 | L2I MPKI | 결과 | 원인/메모 | 재시도 출발점 |
|---|---:|---|---|---|
| Verilator DualMegaBoom qsort (+dhrystone/median/towers) | 57 | **static seq lookahead + burst 1.149x / 1.236x vs twin, MPKI −76%** (프로파일·regex 없이 함수 자동 선택); payload 무관; PGO(trace) RET 1.02x; callsite 계열 1.00x | 순차 코드 스트림(§2-1) | `scripts/static/build_verilator_variant.sh` (SEQ_DISTANCE=4096 SEQ_STRIDE=20), `measure_verilator_variants.sh` |
| arcilator DualMegaBoom | 79 | **static seq lookahead 1.543x / 1.683x vs twin, MPKI 79→35** (D=4 KB K=10); K=20 1.504x, K=40 1.407x; (Aug MegaBoom callsite s4la16 1.051x) | `.fir`→`firtool --ir-hw`→`stub_externs.py`→`arcilator --emit-llvm`→clang+pass | `flat_codegen/work/{build,measure}_arc_variants.sh` |
| Django (DCPerf v1) | 85 | manual 1.46–1.49x — **v1 코드, 폐기** | v2는 `docs/prefetch_plan_by_miss_class.md` A 부류(2.4 MPKI) | `benchmarks/dcperf_v2` |
| FeedSim (DCPerf v1) | 8 | manual 1.05–1.07x — **v1 코드, 폐기** | v2 feedsim_dlrm 2.1–2.3 MPKI(A 부류) | `benchmarks/dcperf_v2` |
| JCodeStream / WideApi (자작) | 93 / 35–50 | C2 V4 1.29x / 1.11x | 스트리밍 JIT 코드 | `jit_prefetch/scripts/ab_jcs.sh`, `wideapi/` |
| MicroSuite Router / HDSearch / Recommend / SetAlgebra | 85 / 79 / high / 25 | PGO(trace) 0.98 / 0.99 / 1.006 / 미확정 (NOP twin 기준) | 7월의 +198%는 빌드 혼동 | `archive/scripts/build_microsuite_lbr_pgo_variants.sh`, `run_final_microsuite_paired.sh`, `run_router_*`, `run_setalgebra_*` |
| PostgreSQL (pgbench / TPC-C) | 25–108 / 51 | static ≤ +0.3% (모든 밀도) | 데이터 트래픽이 L2 코드를 계속 축출(5번째 축); 정확도 재검 필요 | `archive/scripts/build_postgresql_lbr_pgo_variants.sh`, `run_final_postgresql_paired.sh`, `archive/work/pg_tpcc_variants` |
| memcached 1.6.14 | 0.04–10 | manual 1.000x (고정 클럭) | 7월 +15%는 불안정 부하 | `scripts/dispatch/run_memcached_paired.sh` |
| DeathStarBench socialNetwork PostStorage | 5–20 | static/PGO(trace) ≈ 1.00 | miss가 3.6k 지점에 분산, 75%가 DSO 안, 리드타임 ~1 분기 | `flat_codegen/dsb_build/` |
| TailBench Silo/Xapian/Moses/Masstree/Shore/Sphinx/Img-DNN | 8월: 중간; **2026-09-19 4코어 C6 off**: silo 9.8(활용률 3%), masstree 1.4, moses 0.42, img-dnn 0.33, shore 0.01; sphinx/xapian은 입력이 디스크 풀로 잘려 미측정 | 8월 중립~느림; 새 세팅에서는 경계값 이하 | 짧은 실행, 낮은 결정성; 입력 10 GB 재확보(`benchmarks/tailbench`) | `screens/realistic/tailbench_screen.sh` |
| FleetBench (Google) | **proto_benchmark 16.9** (1코어 C6 off, 2026-09-19); rpc 0.65, swissmap/hashing/compression/libc/stl/tcmalloc ≤0.01 | 8월 proto arena +0.8–1.1%(옛 세팅); proto_benchmark는 A 부류 신규 후보(단일 바이너리) | clang 빌드 필요(gcc는 unroll pragma 거부) | `screens/realistic/chain_fleetbench2.sh`, `docs/prefetch_plan_by_miss_class.md` §1-A |
| DCPerf v2 batch: xsbench / gapbs bc / graph500 / liblinear / syscall / schbench | ≤0.01 (4코어 C6 off, 2026-09-19) | 스크린 탈락 | 데이터·커널 bound | `screens/realistic/dcperf_v2_batch.sh` |
| DCPerf v2 adsim (광고 랭킹 서버 + treadmill 클라이언트, 한 호스트) | server 0.58 (4코어 90% 활용률, IPC 3.6) | 스크린 탈락 | FBGEMM 커널 지배; 설치 우회(clang 심링크·folly io_uring·libaegis·OpenMP·libunwind)는 memory/host quirks 참고 | `screens/realistic/adsim_screen.sh` |
| DCPerf v2 cdn_bench (proxygen 리버스 프록시, 서버·프록시·클라이언트 한 호스트) | proxy 0.4 (4코어, 12–81% 활용률, 40k–300k rps), content 0.15–2.3 | 스크린 탈락 | 프록시 코드가 L2에 들어감 | `screens/realistic/cdn_bench_screen.sh` (포트 9081/9082, gflags/glog 수정은 memory 참고) |
| CloudSuite 4 graph-analytics / in-memory-analytics / data-analytics | 0.04–0.25 / 0.03–0.09 / 미기동(YARN NodeManager 등록 실패) | 스크린 탈락 | Spark/Hadoop JVM | `screens/realistic/cloudsuite_analytics.sh` |
| HAProxy / Redis / nginx / LevelDB / RocksDB / QuickJS / SQLite / WAMR / wasm3 / serverless / Folly | <2 | 미실시(스크린 탈락) | miss 자체가 없음 | `archive/scripts/newbench_screens.sh` |
| clang / node.js / Cassandra(부하) / QEMU TCG / PHP / GHDL / vvp / ngspice / LAMMPS / Verilator Rocket | ≤2 | 스크린 탈락 | 코드가 L2에 들어감 | — |
| DaCapo·Renaissance 40+ (tomcat 12, cassandra 13 포함) | ≤13 | C2 V4 중립 | L1I/L2I≈10: miss가 L2에서 해결 → t1 무력; prefetchit0는 no-op | `jit_prefetch/scripts/ab_jvm_suite.sh` |
| **SPEC CPU2026** (rate 24 + speed 19, clang-19 -O3 -g; Fortran 4종(pot3d/palm/fotonik3d/roms)은 gfortran 부재, cloverleaf_s/nest_s/graph500_s는 컴파일 오류로 제외 — nest_r 포함) | 최대 1.66 (723.llvm_r), llvm_s 1.47, gcc_r 1.22, gcc_s 0.75, 나머지 39개 ≤0.16 | **43개 전부 스크린 탈락** (2026-09-16 ref 입력 150 s) | 코드가 L2에 들어감 | `benchmarks/spec2026` (`config/prefetchit-clang-2026.cfg`), 표 `llvm_prefetchit/results/spec2026_20260916/summary.md`, 파이프라인 `scripts/static/spec2026_variant.sh` |
| **SPEC2026 723.llvm_r / 721.gcc_r — 한 자리수 PGO 검증** (ref, 3.8 GHz, 3회, `:u`) | base 1.55 / 1.11 | trace-guided cov90 plan(38k/78k injections → 73k/126k prefetch): **0.46x / 0.25x**, NOP twin조차 0.77x / 0.60x — 사이트가 hot loop 안에 들어가 동적 명령 수가 ×1.87 / ×2.87 | lean plan(cov50·budget 1·depth 2–8·1라인, 1.3k/0.9k prefetch)은 명령 +0.4%/+1.5%로 **0.999x / 0.986x, MPKI 변화 없음(1.55→1.54, 1.11→1.09)** → trace-guided ceiling 없음 = static 시도 안 함. 일반 코드에서는 planner의 사이트 선택에 실행 빈도 상한이 필요(TODO 1-A''') | `scripts/static/spec2026_pgo_static.sh`, `results/pgo_static_20260916/summarize.py` |
| gem5 v25 X86 O3 SE (직접 실행) | 0.008 | 스크린 탈락 | 시뮬레이션 루프가 L2 상주 | `benchmarks/gem5/build/X86/gem5.opt` + stdlib SE config |
| 과학 시뮬레이터: LAMMPS / GROMACS / OpenFOAM / Quantum ESPRESSO / NWChem / ABINIT / NEURON / gmsh / ngspice | 0.04 / 0.03 / 0.03 / 2.1 / 0.34 / 0.10 / 0.07 / 0.04 / 0.02 | 스크린 탈락 (2026-09-16) | 수치 커널이 작음 | `llvm_prefetchit/results/broad_screen_20260916/summary_table.md` |
| 인터프리터·JIT·도구: CPython+sympy / PyPy / LuaJIT / Ruby / PHP / Erlang / SWI-Prolog / mypy / clang -O3 / g++ -O2 / yosys / KLayout | 0.31 / 0.28 / 0.01 / 0.01 / 0.01 / 0.34 / 0.01 / 0.45 / 1.6 / 0.4 / 0.04 / 0.02 | 스크린 탈락 | — | 같은 표 |
| PostgreSQL 17-dev pgbench TPC-B (8 클라이언트, fsync off, 서버 코어 측정) | **0.13** (select-only 1.2) — 첫 측정 40.7은 같은 코어에서 돌던 SPEC2026 빌드가 섞인 오측정 | 스크린 탈락 (재측정 27k tps, IPC 1.23) | 데이터가 캐시에 상주하는 pgbench는 코드가 L2에 들어감 (과거 TPC-C 51은 다른 부하) | `benchmarks/pg/{pg_screen,pg_trace}.sh`, baseline `benchmarks/pg/install_base` |
| 데이터베이스/분석: ClickHouse server (MergeTree 1.2억 행, 4 동시 쿼리) / DuckDB TPC-H sf2 / MongoDB 7 mixed / RocksDB db_bench readrandom | 0.25 / 0.22 / 0.48 / 0.08 | 스크린 탈락 (2026-09-16) | 엔진 코드가 L2 상주 | `llvm_prefetchit/scripts/platform/screens/` |
| 서비스: Envoy 1.31 리버스 프록시 (wrk 55k rps) | 0.24 | 스크린 탈락 | — | `screens/envoy_screen.sh` |
| ML 추론: PyTorch 2 ResNet-50 CPU batch 1 | 0.63 | 스크린 탈락 | oneDNN 커널 | `screens/run_torch.sh` |
| 다른 flattened 시뮬레이터: CXXRTL (yosys, picorv32×48 배열, 15.8 MB C++) / GHDL mcode NEORV32 / QEMU user-mode TCG | **3.3** / 2.8 / 0.001 — CXXRTL PGO/static 검증(3회): seq D=4 KB **K=80 1.025x, MPKI 2.95→0.94**; K=20은 0.968x(코드 팽창 비용), PGO plan은 call 없는 거대 함수라 재앵커링 불가→0.47x(무효) | 탈락(기준 미달)이지만 CXXRTL은 디자인 크기에 비례 — Chipyard SV는 yosys 0.33이 파싱 못함; picorv32×128(42 MB C++)은 clang -O2가 5.7시간 내 안 끝나 중단 | 생성 코드 크기가 Verilator DMB의 1/7 | `screens/run_cxxrtl.sh`, `screens/ghdl_chain.sh` |
| WordPress 6.4 on php-fpm 8.3 + nginx + MariaDB (front 페이지 렌더, 16 workers, wrk) | 1.15 (post 페이지 1.31) | 스크린 탈락 (2026-09-16); 한 자리수 검증으로 자체 빌드 php-fpm(clang -O3 -g, opcache)까지 만들었더니 base가 **0.20 MPKI**라 대상 아님. PGO arm(47k prefetch)은 NOP twin까지 10–50배 느려 변형 빌드 자체가 깨진 것으로 무효 | PHP 인터프리터·WP 코드가 L2 상주 | `screens/wp_chain5.sh`, `benchmarks/php/{build_php,wp_pipeline}.sh` |
| **DeathStarBench socialNetwork / hotel / media** | alone 1–5, interleaved 4–55 (C6 off) | B 부류(interleaving); 공유·C6 세팅의 옛 결과는 `docs/archive/campaign_20260917_shared_regime.md` | `docs/prefetch_plan_by_miss_class.md` §3 | `llvm_prefetchit/scripts/platform/screens/realistic/` |
| MariaDB 10.11 sysbench oltp_read_write (16 tables×200k, 8 threads, 서버 코어) | 패키지 서버 9.3(user+kernel) → 자체 빌드(clang -O3 -g)로 분리: fsync/binlog 켠 durable 설정 **user 3.2 / kernel 7.5**(커널 명령 21%), 우리 파이프라인 설정(flush=0, no binlog) user 0.65 | user 3.2로 한 자리수 검증 대상에 포함 → durable 설정 trace(3회) + PGO plan(20.4k injections)까지 만들었으나 **PGO arm 빌드 불가**: IR pass가 서버 심볼을 가리키는 prefetch를 mysys/strings/sql 헤더 등 여러 링크 타깃이 공유하는 오브젝트에 주입해 클라이언트 라이브러리·도구 링크가 깨짐(6회 시도: 시스템 헤더 사이트 제거, sql/·storage/ 한정, `-prefetchit-skip-pic-modules`, `--unresolved-symbols=ignore-all`까지). 링크 타깃별 주입이 필요 | DB 스크린은 반드시 `:u`로 | `benchmarks/mariadb/{build_base,mariadb_pipeline,mariadb_split}.sh`, `llvm_prefetchit/scripts/platform/screens/mariadb_pgo2.sh` |

## 6. 호스트 / 환경 (2026-09-16)

- Xeon 6787P 86코어, Ubuntu 24.04, **kernel 6.8.0-139, cmdline `quiet splash efi=nosoftreserve`** (`intel_pstate` 활성 → `MODE=3.8ghz` 가능). 이전의 `intel_pstate=disable`은 제거됨. isolcpus/hugepage 없음(스크립트가 직접 pin).
- `perf_event_paranoid`/`kptr_restrict`는 부팅마다 초기화 → `freeze_platform.sh`가 설정.
- LLVM 19.1.7(/opt), Verilator 5.046, chipyard conda 환경(`benchmarks/chipyard/.conda-env`), DCPerf(FeedSim/Django) 설치 완료, JDK 17u 패치 빌드 완료. 상세와 함정: `docs/SETUP.md`.
- 공유 서버: GRUB·부팅 변경 전 다른 사용자와 조율.

## 7. 알려진 함정

- **DSB socialNetwork의 redis 컨테이너는 기본 RDB 스냅샷(`save 60 10000`)을 켜고 있다.** 쓰기 부하가 섞이면 home-timeline-redis가 수십 GB로 자라 분당 fork+전체 덤프를 컨테이너 레이어에 쓴다(4시간에 951 GB). 루트 디스크가 차고 p99가 200~400 ms로 튄다. 스택을 올린 뒤 `docker exec <redis> redis-cli CONFIG SET save ""`와 `appendonly no`를 걸고 `/data/dump.rdb`를 지울 것. mongo 데이터는 익명 볼륨(5~9 GB)에 쌓이니 캠페인 사이에 `docker compose down -v`.


- `source benchmarks/chipyard/env.sh`는 `set -u`와 충돌. chipyard 서브모듈은 `--recursive` 금지.
- pass 로그의 `injected=N`만 믿지 말 것: `objdump` 개수 + drift 게이트 + NOP twin까지가 검증.
- FeedSim 변형 빌드는 설치 환경 변수(vendored glog 등)를 그대로 써야 링크된다(스크립트가 처리).
- `cpufrequtils` 설치 금지(거버너를 ondemand로 바꿈).
- 백그라운드 작업을 `pkill -f`로 죽일 때 패턴이 자기 셸 명령줄과 매칭되지 않게 `[x]` 트릭 사용.

## 8. 문서 지도

- `README.md`(이 문서) · **`docs/prefetch_plan_by_miss_class.md`(현재 설계 문서: 두 부류 분류와 해결 계획)** · `docs/TODO.md`(해야 할 일) · `docs/SETUP.md`(호스트 복구/설치 로그)
- `docs/archive/campaign_20260917_shared_regime.md`: 공유 코어·C6 켜진 세팅의 2026-09-17 캠페인(참고용, 유효하지 않은 세팅) · `docs/archive/shared_library_report_results_20260917.md`: 같은 세팅의 실측 절
- 설계 노트: `llvm_prefetchit/docs/design.md`(pass, plan 스키마, 레이아웃 보정·재앵커링), `llvm_prefetchit/docs/prefetch_experiment_variables.md`, `static_prefetch/docs/static_return_algorithm_v2.md`, `static_cond_algorithm_v1.md`, `static_cond_sampleip_update.md`, `jit_prefetch/docs/PLAN.md`(C2 V1–V4), `flat_codegen/docs/PLAN.md`(arcilator)
- 매니페스트/증거: `llvm_prefetchit/migration/{README,REPRODUCIBILITY,HOST_REFERENCE}.md`, `core_results.tsv`, `evidence/`
- 과거 캠페인 로그(2026-07/08)는 git 이력에만 남겼다: `git show 5be05f7:docs/archive/PAPER_RESULTS_AND_FEEDBACK.md` 등.
