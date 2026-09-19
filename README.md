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
| 3 | Django (DCPerf) | 1.490x, MPKI 84.6→35.0 | **1.463x**, MPKI 85.4→35.3 (2 GHz) | 재현 |
| 3 | FeedSim (DCPerf) | 1.073x, MPKI 8.1→1.7 | MPKI 7.8→1.4, QPS 1.24x(120 s라 거침) | 메커니즘 재현 |
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

### 2-3. 2026-09-17 오후: cold start 스크리닝과 프리페치 전용 해법의 한계

사용자 요청: 커널 격리 없이(기본 Linux 스케줄러, co-tenant 부하) "post-wake cold start"가 지배적인 워크로드를 넓게 스크린하고, 가장 유망한 것에 프리페치 해법을 구현·측정. 코어 0–42만 사용(43–85는 다른 에이전트 몫). 상세 `flat_codegen/dsb_build/postlink/RESULTS.md`, 하니스 `postlink/coldscreen/`.

**스크린 프로토콜**: 스택의 모든 컨테이너를 코어 0–35에 가두고(서로 섞여 도는 바쁜 노드), 컨테이너 하나씩 36–39 전용 코어로 옮겨 재측정. ΔMPKI = cold start(오염) 몫. 네이티브 프로세스는 DSB 부하를 노이즈로 두고 0–42 부동 vs 36–39 고정.

| 워크로드 | MPKI 공유 → 격리 | cycles 격리/공유 | 판정 |
|---|---:|---:|---|
| socialNetwork compose-post | 22.9 → 4.4 | 1.77x | cold start 지배, 후보 |
| socialNetwork user-timeline | 21.9 → 1.9 | 1.64x | cold start 지배, 후보(도구 완비) |
| **PostgreSQL 16** (pgbench 16 clients) | 6.0 → 0.1 | **1.88x** | cold start 지배, 후보 |
| **MariaDB durable** (sysbench oltp_rw) | 12.0 → 3.8 | 1.33x | cold start 지배, 후보 |
| socialNetwork home-timeline | 6.4 → 5.3 | 1.28x | C6 flush형: C6 끄면 0.1 MPKI, 1.23x |
| post-storage memcached | 7.3 → 0.3 | 1.30x | C 바이너리, post-link만 가능 |
| hotelReservation frontend (Go) | 17.7 → 9.0 | 1.30x | Go: AOT 주입 불가 |
| TailBench masstree | 9.5 → 9.5 | 1.00x | 고유 miss, 해당 없음 |
| 저활동 서비스(unique-id·user·media·social-graph·url-shorten) | 10–130(불안정) | — | 명령 수 극소, 후보 아님 |

**프리페치 해법(커널 수정 없음, 재작성기/LD_PRELOAD/재빌드) 결과** — user-timeline, 기본 스케줄링, 3회, NOP twin 대조:

| 방식 | speedup vs base | MPKI |
|---|---:|---|
| wake 직후 64라인 burst (LD_PRELOAD) | **1.019x** (twin 1.001x) | 21.8 → 21.3 |
| paced 1,024라인 | 0.982x (miss −16%) | 22.6 → 19.0 |
| inline "timeline" plan (재빌드, 사이트 85/410 매칭) | 1.005x (twin 0.999x) | 19.8 → 20.0 |
| post-link "timeline" plan (정확한 call 사이트 32개, 1.3k prefetch) | 0.995x (twin 0.994x) | 19.8 → 20.0 |
| MariaDB wake burst 64라인 | 트랜잭션당 cycles ±3% 동일 | 12.6 → 13.6 |
| PostgreSQL wake burst 64라인 | 1.012x tps (twin 1.004x), 트랜잭션당 cycles −3.7% (노이즈 ±2~5%) | 5.85 → 6.00 |

결론: cold start가 지배적인 워크로드는 많지만(DB·RPC 서비스에서 1.3~1.9x 손실), 그 miss는 wake 후 65 µs 실행 구간에 흩어진 분기 목적지들이라 소프트웨어 프리페치가 잡는 몫은 ≤2%다. 손실 분해(user-timeline, 명령 1k당): 코드 miss +12.6, 분기 예측 실패 +4.9, 데이터 miss +2.7, TLB 워크 +1.2 → 코드 miss가 약 절반, 예측 실패 20~25%, 데이터 25~30%; 프리페치가 회수 못 한 건 miss가 싸서가 아니라 fill이 늦어서다. 하드웨어 next-line 프리페처는 이미 순차 부분을 처리하고 있고(miss의 84%가 taken 분기 목적지), 남는 건 fill queue(32~48)와 리드 타임에 묶인다.

#### 2-3-1. 2026-09-17 밤: 짧은 디스패치 서비스용 cold-path static pass + GOT 우회(fat-static)

사용자 요청: "cost 함수 없이, next-line prefetch가 못 잡는 점프 목적지(호출 대상)를 전부 프리페치하되 루프 안은 피하고 injection site를 똑똑하게" + "DSO 프리페치는 컴파일러 flag로 GOT를 우회해 명령어 오버헤드를 줄여라". 구현(`llvm_prefetchit/lib/PrefetchITPass.cpp` `runColdPath`, 환경변수 `PREFETCHIT_COLD_*`):

- **삽입 위치**: IR 명령 24개 이상인 함수의 진입점 한 곳(루프 밖). 함수 자신의 다음 라인(크기 추정, 최대 16개)과 루프 밖에서 도달하는 callee들의 첫 라인(블록 순서 = 실행 순서, 최대 8+8개)을 `prefetcht1`로.
- **참조 형태**: 같은 링크 단위의 심볼은 `prefetcht1 sym(%rip)` 한 명령. 다른 DSO의 심볼만 `mov sym@GOTPCREL(%rip),%r11; prefetcht1 (%r11)`.
- **GOT 우회**: thrift·mongoc·bson·jaeger·opentracing·yaml-cpp·hiredis·redis++·libstdc++를 실행 파일에 정적으로 링크(`FATSTATIC=1 build_utl_variant.sh`, `-static-libstdc++ -static-libgcc`)하고, 그 아카이브의 전역 심볼 목록(`plans/cold_direct_syms.txt`, 13,456개)을 `PREFETCHIT_COLD_DIRECT_SYMS`로 주면 선언만 보이는 callee도 한 명령으로 참조한다. 의존 라이브러리도 정적 전용으로 다시 빌드(`rebuild_deps_static.sh`, `PREFETCHIT_COLD_DIRECT_IN_PIC=1`)하면 라이브러리 내부 사이트까지 직접 참조가 된다(mongoc/bson은 공유 라이브러리 빌드를 끌 수 없어 GOT 형태 유지). 남는 GOT 형태는 libc 호출뿐.

결과(user-timeline, 기본 스케줄링, 3회, `postlink/RESULTS.md` round 17–19):

| 구성 | speedup vs 원래 빌드(공유 라이브러리) | MPKI | 명령 수 |
|---|---:|---|---:|
| cold-path pass, 공유 라이브러리(GOT 형태) | 1.007x (twin 0.998x) | 19.5 → 18.3 | +2.2% |
| fat-static만(pass 없음) | **1.039x** | 19.9 → 18.1 | +0.6% |
| fat-static + cold-path pass(직접 참조) | **1.045x** (fat-static 대비 1.006x, twin 대비 1.018x) | 19.9 → 16.7 | +2.4% |

정적 링크가 왜 빨라지나(카운터, 명령 1k당, g → gs): 코드 miss 19.6 → 17.9, 데이터 miss 5.8 → 5.4(GOT 로드 소멸), ITLB walk 0.78 → 0.66(DSO 6개 → 텍스트 1개), 간접 분기 예측 실패 1.75 → 1.65(PLT의 `jmp *GOT` 소멸). 같은 링크끼리 비교한 pass의 몫: 공유 빌드 1.007x, 정적 빌드 1.003–1.019x(round 19–20; miss가 나는 함수만 삽입하면 twin 비용 0). 정적 타깃 대 trace 비교(`cold_target_analysis.py`): miss의 43%는 libc, exe miss 중 57%만 정적 타깃 위에 있고, 정적 사이트의 84%는 한 번도 miss 안 나는 라인을 겨냥 → trace-guided plan 모드(`PREFETCHIT_COLD_PLAN`, round 21).

**밤 라운드(정적끼리 비교, 3회, `postlink/RESULTS.md` round 19–25):**

| 구성 (fat-static 베이스 gs 대비) | speedup | MPKI | twin 대비 | 명령 수 |
|---|---:|---|---:|---:|
| cold-path 휴리스틱, 라이브러리까지 직접 참조 (cold3) | 1.003x | 18.2 → 16.2 | 1.011x | +2.2% |
| 휴리스틱을 miss 나는 함수 240개로 제한 (cold4) | 1.019x | 18.3 → 16.8 | 1.018x | +1.7% |
| trace-guided plan v1: LBR로 miss 라인을 가장 이른 함수 진입에 귀속 (cold5) | 0.87x | 18.1 → 12.9 | — | **+21%** (hot 함수가 사이트) |
| plan v4: 진입 빈도가 가장 낮은 사이트 선택 + 비용 필터 (cold8) | **1.029x** | 18.3 → 15.6 | 1.035x | +4.0% |
| plan v4에서 libc(GOT) 타깃 제외 (cold8n) | 1.007x | 18.3 → 16.0 | — | +4.5% |
| plan v5: epoch 게이팅(요청당 1회) (cold9) | 1.014x | 18.1 → 15.5 | 1.039x (가드 자체 −2.5%) | +4.2% |
| plan v6: twin의 자체 trace로 재생성 (cold10) | 1.011x | 18.2 → 14.4 | 1.033x (사이트 과다 실행 +10.6%) | +10.6% |
| seq 모드를 miss 함수 240개에만 (seqa) | 1.010x | 18.2 → 17.8 | 0.99x = 노이즈 | 0% |
| plan v7: 사이트당 64라인·가중치≥2·라인당 3사이트 (cold11) | 1.022x | 18.2 → 15.1 | 1.035x | +4.8% |
| plan v4 + 최소 lead 200 cycles (cold12) / 라인당 사이트 1개 (cold13) | 0.995x / 1.009x | 15.3 / 15.9 | — | +4.9% / +3.8% |
| **plan v10: 실측 실행 빈도로 사이트 가지치기** (cold14; 명령 샘플링으로 사이트별 prefetch 실행 수 측정, 절약 miss의 10배 넘게 실행되는 사이트 제거) | **1.026x** | 18.3 → 15.9 | 1.030x | **+2.2%** |
| v4 + wake burst 32/64라인 (LD_PRELOAD, fat-static용 리스트) | 1.013x / 1.025x (v4 단독 1.035x) | 15.7 | — | +4% |
| v4 + orphan burst(귀속 불가 상위 64/128라인을 요청당 1회) | 1.013x / 1.011x (v4 단독 1.014x) | 15.5 | — | +4.5% |
| **v4 5회 확인(round 36, redis 스냅샷 끈 뒤)** | **1.011x** (평균 1.012x, twin 대비 1.019x) | 18.1 → 15.7 | 0.995x | +4.1% |
| v14: hot 사이트 21개를 귀속 후보에서 제외해 재귀속 (cold18) | 1.025x (같은 라운드 v10 1.033x) | 15.5 | 1.004x | +5.0% |
| **v10 5회 확인(round 38)** | **1.022x** (평균 1.032x, twin 대비 1.032x) | 18.1 → 15.8 | 0.998x | +2.6% |
| 원래 공유 라이브러리 빌드(g) 기준: gs / v10 (round 39) | 1.042x / **1.070x** | 19.7 → 18.3 / **15.9** | — | +0.5% / +3.6% |

**코어 고정 위에서는 효과가 없다(2026-09-18 08:56, round 40–41).** 서비스를 메인 1코어 + 풀 4코어(또는 4코어 cpuset)에 고정하면 코드 MPKI가 18 → 1.4~1.8로 떨어지고(L2가 요청 사이에 식지 않음), plan v10은 그 몇 개의 miss를 4~6% 더 줄이지만 명령 증가가 상쇄해 twin과 같다(1.002x / 0.986x). 고정 상태에서 다시 trace해 만든 가벼운 plan(사이트 206개, 명령 +0.6%)도 0.999x. 즉 이 전략은 공유/과다구독 스케줄링에서 wake마다 L2가 차가운 경우에만 유효하며, 그 손실 자체는 코어 고정이 prefetch보다 훨씬 크게(55 → 31 G cycles) 없앤다.

**현실적인 베이스라인(2026-09-18 09:20, 사용자 요청: 코어 고정 + CPU 활용 최대).** 서비스에 코어를 고정하고 그 코어들이 바쁘도록 부하를 올린 상태를 베이스로 삼는다(`postlink/utl_load_sweep.sh`, read-only 부하 `utl_read.lua`). 측정: user-timeline은 요청당 CPU 0.19 ms만 쓰고 nginx-thrift 2.2 ms + post-storage 1 ms가 공유 코어 36개를 9.7k req/s에서 포화시키므로, 4코어 고정은 25% 이상 채울 수 없다. 1코어 고정에서 6,000 req/s = 74% 활용, 살아 있는 스레드 232개(runnable 2~6), MPKI 0.97, p99 10.7 ms → 이 점에서의 결과(round 43–44, 3회): plan v10(공유 환경 trace) 0.982x = twin(0.983x, 명령 +3.2%); 같은 조건에서 다시 trace한 plan(사이트 67개, 명령 +0.1%) 1.001x = twin. **현실적인 베이스라인에서는 prefetch 전략의 효과가 없다**: 한 코어에서 같은 바이너리의 스레드 232개가 돌면 이전 요청이 같은 코드를 방금 실행했으므로 L2가 식지 않는다(MPKI 0.9). 공유/과다구독 환경의 18 MPKI는 과다구독 자체였고, 코어를 전용으로 주는 것이 prefetch보다 훨씬 크게(요청당 cycles −45%) 그 손실을 없앤다. 7,000 req/s(≈86%) 확인은 round 45.

결론(2026-09-18 04:55): user-timeline에서 trace-guided cold plan의 최선은 v10(실측 가지치기)으로 **fat-static 베이스 대비 +2.2%(중앙값)/+3.2%(평균), twin 대비 +3.2%, 코드 miss −12.6%, 명령 +2.6%**(5회 확인). 코드 miss를 13~15% 줄이지만 순이익은 2~3%에서 포화한다. 남은 miss는 libc 내부에서만 도는 구간과 wake 직후 경로로, 정적 사이트가 앞에 없다. 5% 목표는 prefetch만으로는 미달; 정적 링크(gs) 자체의 4~6%가 밤새 가장 큰 단일 이득이었다. 부수 발견: DSB redis 컨테이너의 기본 RDB 스냅샷(분당 수십 GB 쓰기)이 p99 스파이크와 디스크 고갈의 원인이었다(README §7 참조).


정적 타깃 대 trace 비교에서 나온 교훈: miss의 43%는 libc(GOT 앵커+변위로만 도달), exe miss의 57%만 휴리스틱 타깃 위, 휴리스틱 사이트의 84%는 miss 안 나는 라인. plan은 miss 나는 라인만 겨냥하지만 사이트가 뜨거우면 명령 폭증 → 사이트 실행 빈도(cycles+LBR rate trace)를 비용 모델에 넣어야 한다. 이어지는 round 26–28: epoch 게이팅(요청당 1회만 burst), twin의 자체 trace로 plan 재생성(오프셋 드리프트 제거), seq 모드 혼합.

읽는 법: GOT/PLT를 없애는 정적 링크 자체가 3.9%, 그 위에서 pass가 miss를 추가로 7% 줄여 twin 대비 1.8%를 벌지만 추가 명령 1.8%가 1.2%를 도로 먹어 순이익은 0.6%. 명령어 오버헤드를 더 줄이는 두 방향(라이브러리 내부까지 직접 참조 + own-lines 8, trace로 실제 miss 나는 함수만 선택)은 round 19–20.

### 2-2. 2026-09-17 공유 라이브러리/데이터센터: post-link 재작성기와 DeathStarBench 결론

`llvm_prefetchit/tools/postlink/` — 재빌드 없이 링크된 바이너리·.so에 프리페치를 넣는 세 가지 방식을 구현·검증했다(`docs/shared_library_prefetch_report.md`에 하이레벨 설명).

| 방식 | 도구/모드 | 비용 | 결과 (DSB user-timeline, service cycles vs base / MPKI) |
|---|---|---|---|
| call 사이트 → stub(callee-entry burst, caller-stream) | `postlink_call_stubs.py --direct/--plt --burst/--seq` | taken jmp 1개 + stub footprint | twin과 동일, MPKI 21.9→22.6–23.8 (footprint만 증가) |
| PLT 엔트리 16 B in-place(GOT→r11, +64 B 1라인) | `--plt-inplace` (LD_BIND_NOW=1) | 0 | 22.1→21.3–21.9 = 노이즈 |
| per-request hot-set burst(요청당 550–1,050 라인, PLT 엔트리 재지정) | `postlink_hotset_burst.py` | 요청당 ~1k 명령 | 효과 0 (연결당 새 스레드·cold core, 대량 prefetch는 drop) |
| **trace-guided plan**(LBR: ≥60 cycle 리드의 직접 call 사이트 → miss 라인 ≤4개, cross-DSO는 import 심볼의 GOT를 anchor로 사용) | `postlink_trace_plan.py` + `--plan` | 사이트당 stub, 명령 +4–6% | **pgo75 1.010x, MPKI 22.3→19.8** (twin 0.974x); 핀 고정 시 6.96→6.33 (1.003x) |
| 코어 고정(대조군) | `docker update --cpuset-cpus` | — | **pin4: MPKI 6.4, cycles 1.51x; pin8: 9.7, 1.35x** |
| **inline trace-guided plan(전면 재빌드)**: 재빌드 base에서 trace → 바이너리별 plan(서비스 90 + hiredis 97 + libs 360) → IR pass로 stub 없이 주입 | `prefetchit_trace_to_plan.py` + `inline_fix_operands.py` + `chain_inline.sh` | 명령 +1.1% | 비고정 **1.012x**(MPKI 21.9→21.2, twin 0.998x); 메인@40+풀@41-44 고정 **1.003x**(5.74→5.48) |
| 코어 고정 v2(메인 스레드 전용 코어 + 워커 풀 4코어, `pin_threads.sh`) | `docker update` + per-thread `taskset` | — | **1.483x, MPKI 21.9→5.7** |
| **wake-up warm-up**(커널 switch-in 데우기의 유저 공간 대역: `LD_PRELOAD`로 recv/read/poll/epoll 리턴 직후, 잠들었던 호출이면 trace에서 뽑은 "wake 이후 사용 순서" 라인을 prefetcht1) | `warmup/warmup.c`, `wake_lines.py`(sched_switch+sys_exit trace로 wake별 라인 순서), `dsb_warm_ab*.sh` | wake당 64라인: 명령 +0.2%; 1,024라인 paced: +6% | 64라인 **1.019x**(MPKI 21.8→21.3, twin 1.001x); 128+128 1.006x; **paced 1,024라인 MPKI 22.6→19.0(−16%)이지만 0.982x**(pacing 정지 비용); 고정 상태에선 0. 프리페치의 43%가 실제 fill(코드 내 plan은 1%) → 훅은 맞지만 wake당 ~2,400라인을 fill queue(32~48)로 못 채움 |
| **격리 baseline 위의 warm-up**(round 13) | `dsb_iso_ab.sh` | — | gI MPKI 1.89 / 32.5 G cycles; w64I **1.002x**(twin 1.001x), paced 512 0.953x(정지 비용) → 격리하면 프리페치 여지 0 |
| 완전 격리(다른 26개 컨테이너를 코어 40–44 밖으로) + v2 고정 | `docker update --cpuset-cpus` 전 컨테이너 | — | **1.64x, MPKI 1.99, IPC 0.99** — 오염을 없애면 남는 miss가 ~2 MPKI |
| **진단**: inline plan의 prefetcht1 4.3억 개/30 s 중 L2에서 miss(실제 fill)한 건 0.24%(고정)/1.0%(비고정). miss는 요청 시작 직후 transport/parse 코드(libthrift·libstdc++·libc)의 cold-start 버스트라 우리 코드의 사이트가 돌 때는 이미 데워져 있음 | `L2_RQSTS.SWPF_HIT/MISS`(0x24/0xc8, 0x28) | — | 프리페치가 헛돎 |

결론: DSB의 L2I miss는 프리페치로 잡을 "스트림"이 아니라 86코어를 공유하는 26개 컨테이너에 의한 L2 오염 문제다(스레드는 연결당 1개·71개가 오래 살고 동시에 1~4개만 실행; 각 스레드가 요청 사이 ~30 ms 쉬는 동안 같은 코어에서 다른 컨테이너가 L2를 비운다). hot 라인은 2,956개(90%가 66 KB)뿐이라 코어를 고정하면 miss가 1/3.5로 준다. 소프트웨어 프리페치는 trace-guided 배치로 miss를 11% 줄이지만 stub 오버헤드(명령 +5.7%)에 상쇄되어 +1%에 그친다. Verilator에서 같은 stub 방식은 사이트 밀도가 높아 3–5% 손해(IR pass가 낫다). 전면 재빌드(clang-19로 서비스+thrift/mongoc/bson/jaeger를 IR pass로 재컴파일; libc/libstdc++는 배포판) arm도 **callee-burst 1.001x(MPKI 22.6→22.2), seq D4K K40+burst 0.992x(22.1)** = 효과 없음(round 4, `RESULTS.md`). trace-guided plan을 재빌드로 inline 주입한 arm(round 10)은 비고정 1.012x, 메인/풀 고정 1.003x — stub 비용을 없애도 남는 이득은 1% 수준이다. 스레드는 연결당 1개(71개 상주, 동시 실행 1~4개)로 오래 살며, 요청 사이 idle 동안의 L2 오염이 miss의 원인.

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

### 2-4. 2026-09-18~19: 현실적 세팅 스크리닝 (코어 고정 + 부하 sweep) 과 miss 원인 분류

사용자 요청: 코어를 고정한 현실적 세팅으로 다시 스크린(DCPerf 기본 job, DaCapo/Renaissance, CloudSuite 4, 마이크로서비스, DB), 워크로드 안에서 여러 config를 시도, L2 code MPKI ≥ 1이면 후보. 이어서 "util은 유리한 쪽으로 잡아도 된다 → MPKI 높은 쪽" 규칙(util ≥ 15% 중 MPKI 최대 지점, 포화점은 참고). 스크립트·CSV·요약: `llvm_prefetchit/results/realistic_screen_20260918/` (`SUMMARY.md`, `FINAL_TABLE.md`, `compile_final.py`; 사본 `llvm_prefetchit/scripts/platform/screens/realistic/`).

핵심 발견: **고정 코어 + 낮은 활용률의 높은 MPKI는 대부분 유휴 코어의 C6 진입으로 L2가 비워진 뒤 깨어나는 cold miss다.** 서버 코어의 C6를 끄면 PostgreSQL 18.5 → 0.06, MariaDB 11.7 → 0.9, μSuite Router 55/110 → 0.06/0.11, hotel(Go) 서비스 4~9 → 0.1~0.4, socialNetwork 스토어/서비스 11~48 → 0.1~2.3. 부하가 올라 코어가 쉬지 않으면 같은 값이 나온다(PG 16 clients 0.13). 반면 C6를 꺼도 남는 capacity miss는 JVM 서버(tomcat 4.9→3.0, spring 2.9, cassandra 3.2, dotty 1.9)와 C++ media 서비스(movie-id 4.8, compose-review 3.8, nginx 3.6, rating 2.2), CloudSuite web-search 2.5·web-serving 5.0, media mongodb 1.4 뿐이다. 요약 표(원인 포함)는 `FINAL_TABLE.md`; DCPerf는 v2(ICacheBuster 제거, DjangoBench v2/feedsim_dlrm)로 다시 설치·측정 중.

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

## 5. 워크로드 카탈로그 (지금까지의 결론과 재시도 출발점)

스크린 기준: 부하 상태 L2I MPKI ≥ 한 자리 수 → trace-guided plan으로 ceiling 확인 → static.

| 워크로드 | L2I MPKI | 결과 | 원인/메모 | 재시도 출발점 |
|---|---:|---|---|---|
| Verilator DualMegaBoom qsort (+dhrystone/median/towers) | 57 | **static seq lookahead + burst 1.149x / 1.236x vs twin, MPKI −76%** (프로파일·regex 없이 함수 자동 선택); payload 무관; PGO(trace) RET 1.02x; callsite 계열 1.00x | 순차 코드 스트림(§2-1) | `scripts/static/build_verilator_variant.sh` (SEQ_DISTANCE=4096 SEQ_STRIDE=20), `measure_verilator_variants.sh` |
| arcilator DualMegaBoom | 79 | **static seq lookahead 1.543x / 1.683x vs twin, MPKI 79→35** (D=4 KB K=10); K=20 1.504x, K=40 1.407x; (Aug MegaBoom callsite s4la16 1.051x) | `.fir`→`firtool --ir-hw`→`stub_externs.py`→`arcilator --emit-llvm`→clang+pass | `flat_codegen/work/{build,measure}_arc_variants.sh` |
| Django (DCPerf) | 85 | manual 1.46–1.49x | ICacheBuster 메서드 포인터 배열 | `scripts/dispatch/run_django_manual.sh` |
| FeedSim (DCPerf) | 8 | manual 1.05–1.07x | 동일 구조 | `scripts/dispatch/run_feedsim_closedloop.sh` |
| JCodeStream / WideApi (자작) | 93 / 35–50 | C2 V4 1.29x / 1.11x | 스트리밍 JIT 코드 | `jit_prefetch/scripts/ab_jcs.sh`, `wideapi/` |
| MicroSuite Router / HDSearch / Recommend / SetAlgebra | 85 / 79 / high / 25 | PGO(trace) 0.98 / 0.99 / 1.006 / 미확정 (NOP twin 기준) | 7월의 +198%는 빌드 혼동 | `archive/scripts/build_microsuite_lbr_pgo_variants.sh`, `run_final_microsuite_paired.sh`, `run_router_*`, `run_setalgebra_*` |
| PostgreSQL (pgbench / TPC-C) | 25–108 / 51 | static ≤ +0.3% (모든 밀도) | 데이터 트래픽이 L2 코드를 계속 축출(5번째 축); 정확도 재검 필요 | `archive/scripts/build_postgresql_lbr_pgo_variants.sh`, `run_final_postgresql_paired.sh`, `archive/work/pg_tpcc_variants` |
| memcached 1.6.14 | 0.04–10 | manual 1.000x (고정 클럭) | 7월 +15%는 불안정 부하 | `scripts/dispatch/run_memcached_paired.sh` |
| DeathStarBench socialNetwork PostStorage | 5–20 | static/PGO(trace) ≈ 1.00 | miss가 3.6k 지점에 분산, 75%가 DSO 안, 리드타임 ~1 분기 | `flat_codegen/dsb_build/` |
| TailBench Silo/Xapian/Moses/Masstree/Shore/Sphinx/Img-DNN | 중간 | 중립~느림 | 짧은 실행, 낮은 결정성 | `archive/scripts/run_tailbench_highmpki_pgo.sh`, `run_final_tailbench_variant.sh` |
| FleetBench proto arena | high | +0.8–1.1% | 미미 | `archive/scripts/build_proto_arena_*` |
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
| **DeathStarBench socialNetwork** (stock 이미지, mixed-workload 3,000 rps, 컨테이너별 cgroup 측정 30 s) | 서비스별: user-timeline **54.6**(IPC 0.43), compose-post 69, home-timeline 29.5, text 20, url-shorten 71, social-graph 45, unique-id/user/media 84–92; post-storage 5.9(명령 34%), nginx-thrift 5.1(LuaJIT 26%·nginx 23%·libc 12%·jaeger 8%); redis/memcached/mongodb 20–78 | **스크린 통과** (2026-09-16; 이전 5–20 수치와 일치) — DSO 진단: 서비스 바이너리 자체는 miss의 21–33%뿐, libc 21–26% + libstdc++ 10–24% + jaeger 8–12% + libpthread/libthrift/libmongoc 나머지 → **miss가 5–6개 DSO에 분산**(top symbol ≤1.2%), 과거 PostStorage 결론(75% DSO)과 동일; static 재시도는 컨테이너 userland 전체를 pass로 재빌드해야 함 | 작은 서비스가 miss 밀도가 높고 명령 수는 nginx·post-storage에 집중 | `screens/dsb_dso.sh` (wrk2 lua는 luasocket 제거본 `mixed-workload-nosocket.lua` 필수 — 원본은 wrk2에서 로드 실패해 `/`만 때림) | **2026-09-17 밤: user-timeline post-link 캠페인**(재빌드 없이 stock 바이너리·.so 패치, R=6,000, 3회): 호출 사이트 stub(callee burst)·PLT in-place·caller-stream stub·per-request hot-set burst 전부 twin과 동일(효과 0); trace-guided plan(직접 call 사이트→miss 라인, GOT anchor로 cross-DSO) **pgo75 1.010x, MPKI 22.3→19.8**(명령 +5.7%가 상쇄); **pin4(코어 4개 고정) MPKI 22.5→6.4, cycles 1.51x** → miss의 대부분은 86코어를 공유하는 26개 컨테이너의 L2 오염(스레드 71개 상주, 동시 실행 1~4개, 요청 사이 idle 중 오염). 전면 재빌드(IR pass, plan-free burst/seq) arm도 1.001x/0.992x = 효과 없음; inline trace plan(재빌드) 비고정 1.012x, 메인/풀 고정 1.003x; wake-up warm-up(LD_PRELOAD) 64라인 1.019x, paced 1,024라인 MPKI −16%이나 0.982x; 격리 baseline(1.9 MPKI) 위에서는 1.002x. 상세 `flat_codegen/dsb_build/postlink/RESULTS.md` |
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

- `README.md`(이 문서) · `docs/TODO.md`(해야 할 일) · `docs/SETUP.md`(호스트 복구/설치 로그)
- 설계 노트: `llvm_prefetchit/docs/design.md`(pass, plan 스키마, 레이아웃 보정·재앵커링), `llvm_prefetchit/docs/prefetch_experiment_variables.md`, `static_prefetch/docs/static_return_algorithm_v2.md`, `static_cond_algorithm_v1.md`, `static_cond_sampleip_update.md`, `jit_prefetch/docs/PLAN.md`(C2 V1–V4), `flat_codegen/docs/PLAN.md`(arcilator)
- 매니페스트/증거: `llvm_prefetchit/migration/{README,REPRODUCIBILITY,HOST_REFERENCE}.md`, `core_results.tsv`, `evidence/`
- 과거 캠페인 로그(2026-07/08)는 git 이력에만 남겼다: `git show 5be05f7:docs/archive/PAPER_RESULTS_AND_FEEDBACK.md` 등.
