# 아카이브: 2026-09-17 캠페인 (공유 코어·C6 켜진 세팅 — 유효하지 않은 세팅)

이 절들은 README에서 옮겨 왔다. 측정 세팅이 (a) 86코어를 컨테이너 26개가 공유하는 과다구독 상태, (b) 서버 코어의 C6 idle 상태가 켜진 상태였다.
2026-09-18~19의 진단(`docs/prefetch_plan_by_miss_class.md` §0)에서 이 세팅의 높은 MPKI가 대부분 C6 wake의 cold miss와 과다구독 interleaving의 혼합임이 밝혀져,
여기의 speedup 수치(예: user-timeline plan v10 1.022x, fat-static 1.042x)는 새 세팅에서 재측정 전까지 참고값으로만 남긴다. 도구(post-link 재작성기, cold plan 생성기,
fat-static 빌드, wake-list 파이프라인)는 그대로 유효하며 새 문서가 그 도구들을 재사용한다.

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

