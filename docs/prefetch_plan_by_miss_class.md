# 명령어 프리페치 대상 워크로드의 두 부류와 해결 계획 (2026-09-19)

이 문서는 2026-09-18~19의 현실적 세팅 스크리닝(README §2-4, `llvm_prefetchit/results/realistic_screen_20260918/`)에서
확정한 사실 위에 세운 설계 문서다. 이전(2026-09-17)의 공유 코어·C6 켜진 세팅에서 얻은 결론과 설계는 `docs/archive/`로
옮겼고, 이 문서와 충돌하면 이 문서가 우선한다. 유효한 과거 결과는 Verilator/arcilator의 sequential lookahead(README §2-1)뿐이다.

## 0. 유효한 측정 세팅 (이 문서의 모든 숫자가 따르는 조건)

| 항목 | 규칙 | 근거 |
|---|---|---|
| 코어 | 워크로드를 코어에 고정한다(서비스는 cpuset, 배치·JVM은 taskset). 소켓 1(0–42)만 사용 | 프로덕션 배치 방식; 스케줄러 이동을 원인에서 제거 |
| C-state | 사용 코어의 deep C-state(C6/C6P)를 끈다 | 유휴 코어가 C6로 들어가면 L2가 통째로 비워져 wake마다 전량 cold miss가 난다(PG 18.5 → 0.06, Router 55/110 → 0.06/0.11, MariaDB 11.7 → 0.9). 이것은 설정 한 줄로 없어지는 miss이고 latency-critical 서비스는 이미 그렇게 운영한다 → **프리페치 대상이 아니다** |
| 부하 | 벤치마크 기본 config, 활용률은 현실 범위(서비스 20–70%, 배치 100%) | "MPKI가 잘 나오는" 저부하 점을 골라 맞추지 않는다 |
| 두 regime | **alone** = 서비스별 전용 cpuset / **interleaved** = 스택 전체가 8·16코어 pool 공유 | 후자가 논문들(Lukewarm/Ignite, DeathStarBench)의 "cold start" 세팅이다 |
| 카운터 | user-mode(`:u`) L2 code read miss(0x24/0x24) / 명령 / 사이클, 30 s 창, 컨테이너는 cgroup별 | 커널 fsync 경로·다른 컨테이너를 섞지 않는다 |
| 비교 | NOP twin 필수, 같은 라운드 안의 인터리브 ≥3회(서비스 5회), 중앙값 | 베이스가 시간에 따라 움직인다(socialNetwork는 쓰기 부하로 5시간 동안 55 → 64 G cycles) |
| 클럭 | `freeze_platform.sh MODE=3.8ghz`(단일 코어) / `2ghz`(서비스), 끝나면 `restore` | DVFS가 prefetch arm에 유리하게 작용하는 것을 막는다 |

## 1. 분류 (2026-09-21 기준 최신: 09-19 밤 추가 스크린까지 반영)

miss 원인은 세 가지로 판정했다: **cold(C6 wake)** = 서버 코어 C6를 끄면 사라짐, **capacity** = C6를 꺼도 코어 하나에 홀로 두어도 남음,
**interleaving** = 홀로 두면 없는데 다른 서비스와 코어를 나누면 생김. cold는 위의 이유로 제외한다. 남는 두 부류:

### A. capacity-dominant — 코드 working set이 L2(2 MB)보다 크거나 요청 안에서 한 번씩만 실행되는 코드가 많다

| 워크로드 | 세팅 | L2I MPKI (user) | IPC | 코드 종류 | 우리 도구 적용 가능? |
|---|---|---:|---:|---|---|
| **Verilator DualMegaBoom** (qsort/dhrystone/median/towers) | 1코어 3.8 GHz | 57 | 0.6 | flattened C++ (단일 TU 수 MB) | **가능, 검증됨: seq D=4 KB K=20 + burst4 → 1.149x / twin 대비 1.236x, MPKI 56.9 → 13.7** |
| **arcilator DualMegaBoom** | 1코어 | 79 | — | flattened LLVM IR → 오브젝트 | **가능, 검증됨: seq K=10 → 1.543x / 1.683x, MPKI 79 → 35** |
| CXXRTL picorv32×48 | 1코어 | 3.0 | 1.1 | flattened C++ | 가능: seq K=80 1.025x(저밀도) |
| **ARM core-benchmarks `frontend` dfs_chase (depth 16)** — 합성, 65k 함수 9.0 MB text | 1코어 C6 off | **72.1** | 0.47 | C 단일 링크 단위(gcc -O0) | **가능, 즉시 착수**: 함수마다 한 줄, 경로가 무작위 — callee burst의 극단 케이스. 생성기에 `--insert_code_prefetches`가 있어 우리 pass와 같은 바이너리에서 비교 가능 |
| **ARM core-benchmarks `frontend` inst_pointer_chase (3000 chains × depth 20)** — 60k 함수 6.7 MB text | 1코어 C6 off | **48.9** | 0.41 | C 단일 링크 단위 | **가능, 즉시 착수**: 다음 callee가 정적으로 정해져 있어 직접 참조 prefetch 한 줄로 끝남(A-1 callee burst) |
| (같은 생성기, 상류 기본값 1000 chains = 20k 함수 2.25 MB text) | 1코어 C6 off | 2.31 | 0.63 | 〃 | 기본 footprint가 L2와 같은 크기라 경계값 — 스케일 파라미터가 곧 MPKI |
| **MySQL 8.0** sysbench oltp_read_write (16테이블×20만, 16스레드, durable) | 4코어 75% | **2.35** | 1.45 | C++ 단일 타깃 빌드 | **가능**: MariaDB(0.8–1.1)와 달리 단일 타깃이라 A-4의 다중 타깃 문제가 없음 |
| **Rails 8 API + puma**(4 worker×8 threads, CRuby 3.2 YJIT off, production) | 4코어 38% | **1.91** | 1.34 | CRuby 인터프리터 = AOT C, 하나의 링크 단위 | **가능**(Django/CPython 2.4와 같은 부류, cold plan) |
| **FleetBench proto_benchmark** (protobuf 직렬화·파싱 mix, Google fleet 대표 마이크로벤치) | 1코어 C6 off | **16.9** | 0.70 | C++ 단일 바이너리(bazel, clang-19) | **가능, 즉시 착수 후보**: Verilator처럼 한 링크 단위 — seq/cold plan 그대로 적용. FleetBench 나머지(rpc 0.65, swissmap·hashing·compression·libc·stl·tcmalloc ≤0.01)는 탈락 |
| TailBench masstree (integrated harness, 4 스레드, 2,000 qps) | 4코어 16% | 1.4 (500 qps 1.2) | 0.19 | C++ | 경계값(IPC 0.19는 데이터 miss 주도) |
| TailBench silo (TPC-C in-memory DB, integrated harness, 4 스레드, 1,000 qps) | 4코어 3% | 9.8 (250 qps 9.8) | 0.17 | C++ 단일 바이너리 | 가능하나 활용률 3%: 요청 사이 idle 동안 하네스·OS가 L2를 비우는 저부하 패턴(C6는 꺼짐) — 부하를 올려 재측정 필요 |
| DCPerf v2 DjangoBench (uwsgi×4, CPython) | 4코어 68% | 2.4 (C6 off 2.4) | 1.6 | CPython 인터프리터 = AOT C, 하나의 링크 단위 | 가능(cold plan, file-qualified 사이트) |
| DCPerf v2 FeedSim (feedsim_dlrm) | 8코어 19% | 2.1 (C6 off 2.3) | 1.7 | C++ AOT + LibTorch | 가능(서비스 코드), LibTorch는 .so |
| media C++ 서비스 alone: movie-id / compose-review / nginx / rating | 1–2코어 20–70% | 4.9 / 3.8 / 3.6 / 2.2 | 1.0–1.2 | C++ thrift 서비스 | 가능(fat-static + plan) |
| socialNetwork C++ 서비스 alone: user-timeline / compose-post / nginx-thrift | 1코어 15–27% | 1.1 / 1.0 / 1.2 | 1.3–1.9 | C++ / OpenResty | nginx AOT 부분만 |
| MariaDB durable read-write | 4코어 45–86% | 0.8–1.1 | 1.9 | C++ 다중 타깃 빌드 | 경계값; pass는 타깃별 주입 필요(과거 6회 빌드 실패) |
| JVM: DaCapo cassandra(JDK 17 / 21) / tomcat / spring / fop / kafka, Renaissance dotty / finagle-chirper / tradesoap | 4코어 | 4.3 / 3.2 / 3.0 / 2.9 / 1.8 / 1.0 / 1.9 / 1.2 / 1.2 | 1.3–2.4 | JIT | **불가**(AOT pass 대상 아님; C2 삽입은 중립이었음) |
| CloudSuite web-serving(php-fpm+opcache JIT) / web-search(Solr) / data-serving(Cassandra) | 4코어 | 5.0 / 2.5 / 2.1 | 1.3 / 1.9 / 0.9 | JIT/JVM | **불가** |
| 제외(C6 off 후 ≤0.3): PostgreSQL, TaoBench v2(클라이언트 memtier 22k+80k ops/s 확인 후에도 0.3), data-caching, μSuite Router, hotel Go alone, avrora/jme/tradebeans, DaCapo h2o(0.24) | | | | | |
| 제외(2026-09-21 추가 스크린, C6 off): **ScyllaDB 6.2** 0.36–0.50(부하 5k–200k ops/s, Seastar shard-per-core의 hot loop가 작다 — 단, B 부류로는 최상위, §1-B 참고), **Renaissance finagle-http** 0.26(JIT), **OpenMM** 0.01(MD 커널) | | | | |
| 제외(2026-09-19 밤 추가 스크린, C6 off): DCPerf v2 batch — xsbench / gapbs bc / graph500 / liblinear / syscall / schbench **모두 ≤0.01**(데이터·커널 bound); CloudSuite 4 graph-analytics 0.04–0.25 / in-memory-analytics 0.03–0.09(Spark, JVM); TailBench img-dnn 0.33 / moses 0.42 / shore 0.01; FleetBench 7종 ≤0.65; DCPerf v2 cdn_bench proxy 0.4(활용률 12–81%), adsim server 0.6(활용률 90%, IPC 3.6) | | | | | |

읽는 법: 우리 도구로 닿는 capacity 후보는 flattened 시뮬레이터(수십 MPKI, 검증 완료)와 2–5 MPKI의 AOT 서비스(Django v2, FeedSim v2,
media/socialNetwork C++ alone)다. 후자는 MPKI 자체가 작아 0.7 %/MPKI 환산으로 상한이 1.5–3.5%다.

### B. interleaving-dominant — 요청 사이에 다른 서비스가 같은 코어에서 돌아 L2를 밀어낸다 (논문들의 "cold start")

C6를 끄고 스택 전체를 8·16코어 pool에 올린 값(alone 값과 나란히):

| 서비스 | alone | interleaved (pool 8 / 16) | 코드 종류 | 적용 가능? |
|---|---:|---:|---|---|
| media movie-id / rating / user-service / unique-id / text | 4.9 / 2.2 / 1.1 / 0.7 / 0.8 | **55 / 49 / 45–47 / 46–48 / 46–47** | C++ thrift | 가능 |
| media compose-review / user-review / movie-review / nginx | 3.8 / 0.7 / 0.6 / 3.6 | **38 / 34–40 / 34–40 / 22–26** | C++ / nginx | 가능 |
| socialNetwork compose-post / user-timeline / home-timeline / text | 1.0 / 1.1 / 0.1 / 0.05 | **42–44 / 9–13 / 8–9 / 4** | C++ thrift | 가능 |
| socialNetwork nginx-thrift / post-storage, hotel reservation | 1.2 / 0.2 / 0.04 | 2.1–2.3 / 1.8 / 0.15–0.26 | (바쁜 tier) | 코어가 안 식음 → 대상 아님 |
| hotel frontend / profile / recommendation / geo / search (Go) | ≤0.5 | 11–13 / 12–13 / 15–16 / 8–10 / 3–5 | Go | Go 삽입기 없음 → 보류 |
| 스토어: mongodb / redis / memcached | ≤2.3 | 14–105 | C/C++ 바이너리(소스 재빌드 또는 post-link) | post-link 재작성기로 가능 |
| **ScyllaDB 6.2** (2026-09-21) | 0.40 | **6.05**(이웃=MySQL) / **10.97**(이웃=Rails) | C++ AOT(Seastar) | 가능 — alone 0.4인데 코어를 나누면 셋 중 가장 나빠진다 |
| **MySQL 8.0** (2026-09-21) | 2.35 | **9.25**(이웃=Scylla) | C++ AOT | 가능 |
| **Rails + puma** (2026-09-21) | 1.91 | **3.48**(이웃=Scylla) | CRuby AOT 인터프리터 | 가능 |

(media pool 16 재측정 2026-09-19: 오류 허용 0.1%로 2,000 req/s에서 22–89 MPKI — movie-id 54, rating 43, compose-review 38, nginx 22, mongodb 29–89; 3,000 req/s는 non-2xx 454건으로 포화.)

2026-09-21에 DeathStarBench 밖의 재고 서버 소프트웨어로도 같은 것을 확인했다: ScyllaDB·MySQL 8·Rails를 코어 4개짜리 cpuset 하나에 둘씩 올리면
서비스별 활용률은 alone 때와 같은데(33%·21%·39%) MPKI만 1.8–27배로 뛴다. 즉 B 부류는 마이크로서비스 벤치마크의 성질이 아니라 **코어 공유 자체의 성질**이다.

두 가지가 중요하다. (1) pool 8과 16에서 값이 같다 → miss는 **이웃 서비스가 요청 사이에 코드를 밀어내는 것**이 원인이지 pool 크기가 아니다.
(2) 서비스 안의 스레드 affinity로는 안 풀린다: alone regime(서비스의 모든 스레드를 코어 하나에)에서 1–5인데 그 코어를 다른 서비스와 나누는 순간 34–55가 된다.
서비스 단위 배타적 cpuset은 풀리지만 코어당 활용률 5–30%(socialNetwork 총 수요 12코어에 27코어)를 감수해야 한다 — 그 트레이드오프가 곧 이 문제다.

## 2. A 부류(capacity)의 해결 계획

### A-1. sequential lookahead (검증됨, 순차 스트림형에 사용)
- 무엇: `prefetcht1 D(%rip)`를 K번째 IR 명령마다, D=4 KB, K=20(≈70 B) + callee-entry burst 4라인. plan/profile 없음, 레이아웃 drift 없음.
- 어디에: miss가 "마지막 taken branch 뒤로 길게 흐르는" 코드(Verilator/arcilator/CXXRTL 같은 flattened 생성 코드). 판정은 `static_prefetch/tools/ret/miss_stream_characterization.py`(sample IP가 LBR[0].to 라인 밖으로 얼마나 흐르는지).
- 결과: Verilator 1.149x, arcilator 1.543x, CXXRTL 1.025x(K=80).
- 남은 일: (a) 명령 비용 절감 — MachineFunction pass로 정확히 128 B마다 하나(IR K는 31–125 B로 흔들림; twin 열이 −5.7%를 보여줌), (b) 다른 설계(LargeBoom/Quad)와 ESSENT로 일반화, (c) 인접하지 않은 callee 전환(잔여 miss 11%)용 burst 규칙.
- 기대치: 현재 1.15x에서 명령 비용을 절반으로 줄이면 1.18–1.20x.

### A-2. trace-guided cold plan (분산형 capacity miss에 사용) — 도구는 있고, 대상만 바꾼다
- 무엇: LBR 붙은 L2I miss trace에서 miss 라인마다 60–4,000 cycle 앞의 함수 진입 중 **실행 빈도가 가장 낮은 것**을 사이트로 잡아 그 라인만 `prefetcht1`(exe 라인은 pc-relative, 다른 파일 라인은 GOT 앵커+변위). 사이트 실행 빈도는 명령 샘플링으로 실측해 가지치기(v10). 도구: `flat_codegen/dsb_build/postlink/cold_plan.py` + pass `PREFETCHIT_COLD_PLAN`(burst는 16 B 배수로 패딩해 오프셋 보존).
- 어디에: Django v2(CPython 2.4), FeedSim v2(2.1–2.3), media C++ 서비스 alone(2–5). 모두 **C6 off, alone** 세팅에서 측정.
- 절차: (1) `-O3 -g` 재빌드(Django는 CPython 3.x를 pass로 재빌드) → (2) LBR trace + rate trace → (3) plan v4 → 빌드 → 명령 샘플링 → v10 → 빌드 → (4) NOP twin과 5회 A/B.
- 기대치: MPKI 2–5의 절반을 잡으면 1.5–3.5%. 이 부류에서 5%는 어렵다는 것을 미리 적어 둔다.
- 알려진 함정: hot 함수를 사이트로 잡으면 명령 +21%(v1); libc 라인은 GOT 형태로라도 넣어야 한다(빼면 이득 2/3 소실); site-exec 가지치기가 오버헤드를 +2%로 묶는다.

### A-3. 링크 단위 통합(fat-static) + 직접 참조
- 무엇: thrift/mongoc/jaeger/libstdc++를 실행 파일에 정적 링크하고 아카이브 전역 심볼 목록(`PREFETCHIT_COLD_DIRECT_SYMS`)으로 선언만 보이는 callee도 한 명령으로 참조.
- 효과: 정적 링크 자체가 PLT/GOT 경유·페이지 분산·ITLB walk를 없애 **4–6%**(user-timeline, 공유 세팅 측정치라 C6-off alone에서 재확인 필요). pass는 그 위에서 동작.
- 제약: .so에는 PC32로 다른 파일을 가리킬 수 없다(bfd/lld 모두 거부) → 라이브러리를 정적 전용으로 다시 빌드해야 한다(`rebuild_deps_static.sh`).
- 계획: A-2의 모든 서비스 실험은 fat-static 베이스(gs)를 기준으로 하고, "정적 링크 몫"과 "prefetch 몫"을 항상 분리해 보고한다.

### A-4. 다중 타깃 빌드의 타깃별 주입 (MariaDB류)
- 문제: IR pass가 실행 파일 심볼 참조를 넣은 오브젝트가 서버·클라이언트 라이브러리·도구에 함께 링크되어 링크 실패(6회 시도).
- 계획: (a) plan에 "타깃 이름"을 넣고 `-DPREFETCHIT_TARGET=`으로 서버 TU에서만 주입, 또는 (b) 약한 참조(`.weak` + 0 체크 없는 prefetch는 주소 0이면 무해) — prefetcht는 fault를 내지 않으므로 미해결 심볼을 0으로 두는 `-z undefs` 계열이 실용적. 우선순위 낮음(MPKI 0.8–1.1).

### A-5. 소스가 없는 바이너리 — post-link 재작성기
- 무엇: `llvm_prefetchit/tools/postlink/postlink_call_stubs.py`(call 사이트 → stub), `--plt-inplace`, `postlink_trace_plan.py`(LBR plan). 스토어(mongodb/redis/memcached)와 배포 바이너리용.
- 결과(공유 세팅): stub 방식은 명령 +5.7%로 이득 상쇄(pgo75 1.010x). 계획: 직접 call 사이트는 callee 앞 padding에 prefetch를 두는 방식으로 stub 비용을 1% 이하로 → C6-off alone에서 스토어에 재시도. 우선순위 중.

### A-6. JIT 코드(JVM/php/LuaJIT)
- 우리 AOT pass 밖이다. JVM 쪽(C2에 entry burst 삽입, `jit_prefetch/`)은 DaCapo/Renaissance 40종에서 중립이었고 자작 JCS/WideApi에서만 1.1–1.3x였다.
- 계획: 이 문서의 범위에서 제외하고 §5의 "테스트 못 한 목록"에 JVM 후보를 남긴다. 다시 열 조건: L1I≈L2I인 워크로드(miss가 L2에서 해결되지 않는 것)를 찾았을 때.

### A-7. 측정 프로그램 (순서)
1. Verilator A-1 명령 비용 절감(Machine pass, 1주) → 1.15x → 1.18x 확인.
2. Django v2 CPython 재빌드 + A-2/A-3(3일) → 2.4 MPKI 위에서 상한 확인.
3. media C++ 서비스 alone(C6 off)에 A-2/A-3(2일) — B 부류 실험의 베이스도 된다.
4. FeedSim v2 A-2(2일).

### A-8. 레지스터 기반 간접 타깃 prefetch — 어디에 쓸 수 있나 (2026-09-21 측정, `llvm_prefetchit/results/indirect_share_20260921/`)

질문: cross-DSO(GOT 경유) 말고 `prefetcht1 (%reg)` 형태가 필요한 miss가 있는가. L2I miss 샘플의 LBR[0](miss 라인으로 들어온 마지막 taken branch) 종류별 비중:

| 워크로드 (MPKI) | vtable·함수포인터 call (same-DSO) | jump table·tail jmp (same-DSO) | cross-DSO (PLT/GOT) | RET | 직접 분기(COND/CALL/UNCOND) |
|---|---:|---:|---:|---:|---|
| Verilator (57) | 0.02% | 0.5% | ~0 | 7.5% | 92% |
| **FleetBench proto (16.9)** | **13.3%** | 2.6% | 0.6% | 6.3% | 77% |
| **Django uwsgi+libpython (2.4)** | 5.4% | **13.2%** (CPython computed-goto `jmp *(%r14,%rcx,8)`) | 9.7% | 14.5% | 57% |
| UserTimeline / ComposePost / MovieId gs (1.1 / 1.0 / 4.9) | 3.4 / 8.8 / 8.2% | 2.7 / 2.4 / 2.5% | **13.6 / 13.9 / 10.4%** | 14.0 / 12.3 / 16.0% | 66 / 63 / 63% |

결론.
- Verilator·arcilator(flattened)는 간접 분기가 없다 — 지금의 rip 상대 prefetch로 충분하고, 레지스터 형태가 필요한 miss는 0.5%.
- **cross-DSO 말고도 쓸 데가 있다**: proto 16%, Django 19%, thrift 서비스 6–11%의 miss가 레지스터로만 타깃을 아는 분기 뒤에 있다. 다만 세 부류 모두 몇 개의 **런타임 일반 코드 사이트**에 몰려 있다 — proto는 `RepeatedPtrFieldBase::ClearNonEmpty`의 `call *0x10(%rax)`(요소별 virtual Clear) 한 사이트가 전체 miss의 7.9%, `MergeIntoClearedMessages` 3.5%, `InternalWriteMessage` tail-jmp 2.1%; Django는 `_PyEval_EvalFrameDefault`의 opcode 디스패치 점프(한 사이트 3.5%, 복사본 합계 13%); thrift는 `TVirtualProtocol`/handler vtable과 TType switch.
- 분기 자체에서는 리드타임이 0이므로 "레지스터 prefetch"의 값은 **타깃 주소 로드를 앞당길 수 있느냐**에 달려 있다. 상한: proto 16.9×0.16 ≈ 2.7 MPKI → ~1.9%(0.7%/MPKI), Django·thrift는 <0.5%.
- RET(6–16%)는 레지스터 형태가 필요 없다: 되돌아갈 지점은 call 사이트가 알고 있으므로 rip 상대 continuation prefetch(RET v3, Verilator 1.001x)로 표현되고, 문제는 형태가 아니라 리드타임이었다.

실험 두 개(각 반나절, 우선순위는 proto 먼저).
1. **proto — virtual 타깃 hoisting**: IR pass에 "indirect call target prefetch" 모드를 추가. `call *slot(vptr)` 사이트에서 객체 포인터가 루프 밖·함수 진입에서 이미 알려진 경우(ClearNonEmpty의 `rep->elements[0]`, MergeInto*의 소스 메시지), 그 지점에서 `vptr = load obj; f = load vptr[slot]; prefetcht1 f`를 non-null 가드 아래 발행(vptr 슬롯 로드는 유효 객체면 안전). 리드타임 = 루프 준비~첫 호출(20–100 명령). 대상 사이트는 위 6개로 시작(전체 miss의 15%).
2. **Django — 디스패치 한 칸 앞 prefetch**: ceval `DISPATCH()` 매크로에서 다음-다음 opcode의 핸들러 `opcode_targets[next_instr[1].op.code]`를 레지스터로 계산해 `prefetcht1`. 리드타임 = 핸들러 하나(20–50 명령). CPython 재빌드(clang 19, `-fpass-plugin` 빌드와 같은 트리) 후 uwsgi MPKI·wrk 처리량. 같은 원리가 Cython switch 테이블에는 안 통한다(케이스 결정이 분기 직전).
ISA 관점: 현재 ISA도 `prefetcht1 (%reg)`는 있으므로 부족한 것은 명령이 아니라 **리드타임**이다. 그래서 하드웨어 쪽 답은 BTB 메타데이터로 타깃을 미리 아는 방식(BTB-Ferret, §6-1)이나 호출 대상 힌트(보고서 §4-2)이지, 새 주소 지정 모드가 아니다 — GOT 경유 한 명령(보고서 §4-1)만이 cross-DSO에서 명령 수를 줄인다.

## 3. B 부류(interleaving)의 해결 계획

> **2026-09-21 갱신**: B-1/B-2의 프로세스 안 계획은 `docs/prefetch_plan_classB_wakestream.md`(run 종류별 첫 접근 열을 타깃으로, call 경계에 d 라인 앞 k 라인씩 흘리는 wake-stream)로 대체·구체화했다. 아래 B-1/B-2는 배경으로 남긴다. 첫 구현·측정(media movie-id interleaved, 2026-09-21: LD_PRELOAD 1.014x, pass dense drip 1.028–1.031x)은 그 문서 §7.

핵심 제약: miss는 **깨어나는 순간마다** 요청 경로 전체에서 난다(hook별 wake당 miss 434–2,086개, wake 후 5 µs 안에 6%, 40 µs 이후 절반). 프로세스 안에는 이 miss보다
앞서 실행되는 코드가 없다. 블로킹 **전**에 당겨 두는 것은 소용없다(자는 동안 이웃이 다시 밀어낸다). 그래서 프로세스 안 prefetcht의 상한은 낮고, 진짜 해법은 프로세스 밖에 있다.

### B-1. 프로세스 안: trace-guided cold plan v10 (측정된 상한)
- 위 A-2와 같은 도구. 공유 코어·C6 켜진 세팅에서 user-timeline **1.022x 중앙값 / 1.032x 평균(twin 대비 1.032x, miss −12.6%, 명령 +2.6%)**. 카운터: prefetch가 실제로 라인을 가져온 비율 0.2–1%, 잔여 miss의 43%는 "사이트는 있었지만 너무 늦음".
- 계획: C6-off interleaved 세팅(media movie-id 55, compose-post 42)에서 같은 plan을 다시 재서 이 문서 기준의 상한을 확정(2일). 예상 2–4%. 이것이 "prefetcht만으로 되는가"의 답이 된다.

### B-2. 프로세스 안: RPC 디스패처의 method별 warm-up (새 시도, 비용 낮음)
- 아이디어: thrift `TDispatchProcessor::process`는 handler를 부르기 전에 프레임 헤더와 method 이름을 읽는다. 그 시점부터 인자 역직렬화·dispatch까지 수 µs가 있다. trace에서 miss 라인을 **method별**로 귀속해(LBR 창의 handler 이름) method 이름 파싱 직후 그 목록을 뿌린다.
- 구현: pass의 plan 모드에 "site = `TDispatchProcessor::process`, 조건 = method id" 분기를 추가하거나, thrift generated `dispatchCall`의 method별 분기 첫 블록을 사이트로 쓴다(코드 변경 없이 pass가 잡을 수 있음: `processMap_` 조회 후 각 `process_<method>` 진입이 method별 사이트다).
- 배치 규칙: 한 사이트당 ≤32라인(L2 outstanding 한도; 64라인 이상은 버려져 wake burst 1,024라인이 −2%였다), 필요하면 handler 진입·첫 하위 RPC 직전에 2·3차 배치.
- 기대치: "too late" 잔여(43%)의 일부를 앞당겨 B-1에 +1–2%p.

### B-3. 프로세스 밖: 커널 switch-in prefetch 모듈 (5%를 넘길 유일한 후보)
- 근거: 밀려난 라인은 L3(500 MB+)에 남아 있다. 요청 경로 첫 접근 500라인(32 KB)은 L3에서 48 outstanding으로 0.5–1 µs면 채워진다. 스케줄러는 다음 task를 switch-in 1–3 µs 전에 안다. 즉 대역폭·리드타임 모두 충분하고, 없는 것은 "그 시점에 실행할 코드"뿐이다.
- 설계: (1) 사용자 공간에서 스레드별 "wake 이후 사용 순서" 라인 목록을 만든다(이미 있음: `wake_lines.py`, hook별 top-256/1,024). (2) 커널 모듈이 `sched_switch` tracepoint(또는 preempt notifier `sched_in`)에서 next task의 목록을 `prefetcht1`로 32라인씩 나눠 발행(사용자 주소는 next의 mm이 활성이므로 접근 가능; 페이지 없으면 무해). (3) 목록은 `/sys` 또는 ioctl로 등록, PID·hook 종류(recv/poll/cond) 별.
- 검증: user-timeline/compose-post/media 서비스에서 C6-off interleaved 세팅, twin은 "목록은 등록하되 발행 안 함". 기대치: 코드 miss 몫(cold-start 손실의 약 절반)의 상당 부분 → **5–15%**가 가능하지만, BTB/TLB/데이터 cold는 그대로 남는다(감산 분해: 명령 1k당 코드 miss +12.6, 분기 예측 실패 +4.9, 데이터 +2.7).
- 리스크: 공유 서버라 모듈 로드는 조율 필요(GRUB 변경 없음); 커널 6.8 tracepoint 훅으로 구현 가능, 이틀.

### B-4. 하드웨어/ISA: switch-in warm-up 엔진 (보고서 §4-4)
- B-3를 하드웨어로: task 전환 시 "이 task의 최근 명령 working set"을 record/replay(Jukebox/Ignite 계열). 우리 데이터가 제공하는 것: wake당 miss 수, 라인 수 분포(하드웨어 버퍼 크기 근거), L3 상주 여부. gem5 모델링은 선택.

### B-5. 배치·스케줄링 (소프트웨어 대안, 비교군)
- 코어당 공유 서비스 수를 제한하는 cpuset 그룹(서비스 2–3개/코어)으로 MPKI가 어떻게 줄어드는지 sweep해 "affinity로 어디까지"를 수치로 낸다(1시간). 프리페치 제안의 대조군이자, 논문의 배치 정책 논의에 답이 된다.

### B-6. 하지 말 것 (측정으로 배제)
- wake 직후 LD_PRELOAD burst(64라인 1.019x, 1,024라인 0.982x), epoch 게이팅(가드 −2.5%), orphan burst(디스패처 진입의 일반 목록, 0), 요청 경로 hot-set burst(0). 이유는 모두 리드타임·outstanding 한도·오버헤드.

### B-7. 측정 프로그램 (순서)
1. media movie-id/compose-review + socialNetwork compose-post를 fat-static + plan v10으로 C6-off interleaved 세팅에서 A/B(3일) → B-1 상한.
2. B-2 method별 warm-up 추가(2일).
3. B-5 affinity sweep(반나절) — 배치 대안의 수치.
4. B-3 커널 모듈 프로토타입(3일) → 프로세스 밖 리드타임의 가치 실측. 이 결과가 논문의 핵심 주장(§4-4 ISA)의 근거가 된다.

## 4. 공통: 무엇을 보고할 것인가
- 각 워크로드에 한 행: base 대비 실측 speedup, twin 대비, MPKI before→after, 명령 수 증가, 세팅(코어·C6·regime·활용률). 스윕은 CSV에만.
- A 부류는 "정적 링크 몫"과 "prefetch 몫"을 분리, B 부류는 "alone MPKI"와 "interleaved MPKI"를 함께.

## 5. 테스트하지 못했거나 미완인 벤치마크 (2026-09-19 밤 추가 시도 반영)

CloudSuite는 4.0 이미지(2023-06 릴리스: Ubuntu 22, PHP 8.1 JIT, Solr 9.1.1, Cassandra 4.1.0 — 현재 최신 라인)로 측정했다. 아래 "추가 시도" 열이 이번에 새로 한 것이다.

| 항목 | 추가 시도(2026-09-19 밤) | 남은 것 / 다시 하려면 |
|---|---|---|
| DCPerf v2 TaoBench | 클라이언트 로그 확인: memtier가 실제로 22k+80k ops/s를 냈고(일부 TLS 오류) 서버 MPKI 0.3은 유효 → **탈락 확정** | — |
| DCPerf v2 신규 batch: xsbench, gapbs bc, graph500, liblinear, schbench, syscall | 설치·측정 완료(4코어 C6 off; jobs_mem/jobs_system.yml은 `-b/-j` 지정 필요, gapbs/graph500은 `dnf` 가드·`install_remove_git.sh` 스텁, graph500은 root MPI 허용 변수와 pid별 측정) → **전부 ≤0.01 MPKI, 탈락** | — |
| DCPerf v2 cdn_bench (proxygen 리버스 프록시) | 설치 성공(pinned proxygen에 없는 `asBodyEv` 호환 shim). 바이너리가 gflags "static+dynamic" 충돌로 기동 실패 → glog를 gflags 없이 재빌드해 `binaries/lib`에 교체; `run.sh`가 기동 시 8081/8082 리스너를 모두 죽여 같은 호스트의 서버를 잡아먹음 → 9081/9082 포트 사용. **측정 완료: proxy_server 0.39–0.41 MPKI(4코어, 활용률 12→81%, 40k→300k rps, IPC 1.7→1.3), content_server 0.15–2.3(활용률 1–22%) → 탈락** | — |
| DCPerf v2 adsim (광고 랭킹, C++/thrift + FBGEMM) | 설치 7회 시도 끝에 성공(`/usr/bin/clang{,++}` 심링크 → folly `Liburing.h`의 `__has_include` io_uring 감지를 빌드 스크립트에서 끔 → fizz용 libaegis HEAD 추가 → clang-19에 omp.h·libomp.so 연결). treadmill 클라이언트는 libunwind.so.1 심링크 필요. **측정 완료: server 0.57–0.58 MPKI(4코어 89–92% 활용률, IPC 3.6 — FBGEMM 랭킹 커널이 지배, 8 workers에서 11 qps·P95 3.0 s로 포화) → 탈락**(저부하 점은 미측정) | 저부하 점: `adsim_screen.sh WORKERS=1` |
| DCPerf v2 ucache_bench, silo, ai_wdl | ucache_bench(cachelib) 빌드가 디스크를 채워 중단·삭제; silo/ai_wdl은 v2-beta에 job 정의 없음 | 디스크 60 GB+ 확보 후 ucache_bench 재설치 |
| DCPerf video_transcode, Mediawiki(HHVM), WDL(folly), Spark | 미시도(입력 클립 CDVL 등록 / HHVM 3.30이 24.04에서 안 뜸 / folly-fizz 불일치 / 500 GB 스토리지) | 이전과 동일 |
| CloudSuite 4 graph-analytics / in-memory-analytics | 측정: 0.04–0.25 / 0.03–0.09 (Spark local[4], 4코어 C6 off) → 탈락 | — |
| CloudSuite 4 data-analytics (Hadoop/Mahout) | 두 번 재시도(`--master`/`--slave --master-ip`, network alias): NodeManager가 RM:8031에 연결 못 해 job이 ACCEPTED 0%에 머묾 → 미측정(JVM 부류라 우선순위 낮음) | RM 바인드 주소(yarn-site 172.18.0.2) 점검 |
| CloudSuite 4 media-streaming | 클라이언트 하네스(`peak_hunter/launch_remote.sh`)가 클라이언트 호스트에 ssh를 요구 → 미시도 | 컨테이너에 sshd 추가 또는 videoperf 직접 실행 |
| μSuite SetAlgebra, HDSearch | 미시도(로드제너레이터 크래시) | 8월 패치 재적용 |
| DaCapo h2o / fop / kafka | 측정 완료(JDK 17 h2o 0.24, fop 1.8, kafka 1.0; cassandra JDK 17 4.3) | — |
| TailBench (supreethkurpad 포크, 09-15 빌드 바이너리 + 호환 라이브러리 shim) | img-dnn 0.33 / masstree 1.4 / moses 0.42 / shore 0.01 / **silo 9.8**(TPC-C, 4 스레드, 1,000·250 qps에서 활용률 3%·1% — 저부하에서 요청마다 코드가 밀려나는 패턴, IPC 0.17) 측정. sphinx·xapian은 입력이 두 번 다 디스크 풀로 잘림(xapian DB 14 GB; 두 번째 시도도 zero-length 파일 2개 → DatabaseCorruptError, sphinx 디렉터리 미생성) → 미측정 | 디스크 30 GB+ 확보 후 `tailbench.inputs.tgz` 재다운로드, `tailbench_screen.sh ONLY="sphinx xapian"` |
| FleetBench | clang으로 빌드(gcc는 `#pragma GCC unroll` 거부), 1코어 C6 off: **proto 16.9**, rpc 0.65, 나머지 ≤0.01 → proto_benchmark가 새 A 부류 후보 | seq/cold plan 적용은 §2-A-7 순서대로 |
| 서버리스(vHive/vSwarm, FunctionBench) | 미시도 | vHive 설치 |
| hotelReservation Go 서비스 | 도구 없음 | Go 삽입기 |
| DeathStarBench media pool-16 | 오류 허용 0.1%로 2,000 req/s 재측정 완료(§1-B 참고) | — |

## 6. 추가 후보 리스트업 (2026-09-21, 조사만 하고 실행하지 않음)

요청 출처 세 가지(OpenMM, ARM core-benchmarks `frontend`, "Prefetching for Hierarchical Branch Target Buffers"의 벤치마크)와 그 밖에 아직 안 해 본 것을 한 표로 모았다.
"예상"은 이미 측정한 유사 워크로드에서 유추한 값이고, 실행하면 표 §1에 옮긴다.

### 6-1. 요청한 세 출처

| 후보 | 무엇인가 | 우리 세팅에서의 예상 | 도구 적용 | 준비 비용 | 판단 |
|---|---|---|---|---|---|
| **ARM core-benchmarks `frontend`** (github.com/ARM-software/core-benchmarks) | 합성 프론트엔드 스트레스 생성기 두 종. `dfs_chase_gen`: 깊이 D(기본 20)의 완전 이진 호출 트리(2^19 leaf), 함수마다 조건 분기(확률 `--branch_probability`)로 왼/오른쪽 자식 호출, `--use_indirect_calls` 옵션. `inst_pointer_chase_gen`: `--num_callchains`(1000)×`--depth`(20)개 함수를 무작위로 이어 붙인 직접 호출 사슬. 둘 다 protobuf CFG → C 소스 → gcc/make, **`--insert_code_prefetches`로 생성기 자체가 코드 프리페치를 심을 수 있음** | 함수 하나가 한 라인이고 경로가 무작위라 호출마다 L2I miss — 수십 MPKI 이상(우리 `seq_stream` 마이크로벤치 base 71과 같은 급) | **가능**: inst_pointer_chase는 다음 callee가 정적으로 정해져 있어 직접 참조 prefetch 한 줄로 끝남(A-1 callee burst와 동일); dfs_chase는 분기 뒤에 target이 정해지므로 함수 진입에서 두 자식을 모두 당기는 "양쪽 burst"가 필요 — 리드타임 0인 극단 케이스라 ISA 제안(호출 대상 힌트, §보고서 4-2)의 논거로 쓸 수 있다. 생성기 내장 prefetch와 우리 pass의 삽입을 같은 바이너리에서 비교 가능 | 1시간(순수 C, x86에서 그대로 빌드) | **stage-1 합성 후보로 채택 권장** — 현실 워크로드는 아니므로 §1 표가 아니라 마이크로벤치 절에 둔다 |
| **OpenMM** (분자동역학 엔진, C++ 코어 + Python API, CPU 플랫폼) | 비결합력 커널·PME FFT가 시간의 대부분 — GROMACS/LAMMPS/NAMD와 같은 부류 | 이미 잰 GROMACS 0.03 / LAMMPS 0.04 / Quantum ESPRESSO 2.1(예외적)에서 유추하면 **≪1 MPKI** | 가능하나 miss가 없음 | 30분(conda `openmm`, CPU 플랫폼 벤치 스크립트) | 탈락 예상, 최하 우선순위 — 확인용 30분만 |
| **"Prefetching for Hierarchical Branch Target Buffers"** (BTB-Ferret, Huang·Ďuračková·Grot·Schall, MICRO 2026; 사용자 제공 PDF) | gem5 full-system(Granite Rapids급 2-level BTB 128/16K), 37개 앱 Table II: **NodeApp**(Node.js 웹서버), **PHPWiki**(PHP 위키), **Fleetbench Proto / TCMalloc / STL**, **DaCapo** H2·H2O·Luindex·Spring·Tomcat·Lusearch, **BenchBase**(Java) Voter·Twitter·TATP·Epinions·YCSB·Seats·SiBench·Noop·SmallBank, **Renaissance Finagle-HTTP**, SPEC2017 INT 8종·FP 8종. 관찰: L1-BTB 29 MPKI 평균(SiBench 76), miss chain의 트리거는 양방향 조건분기 44%·return 39%, **직접+간접 call은 8.2%**; 코드 저장소 github.com/yongjiehuang/BTB-Ferret에 gem5 체크포인트 워크플로 | 우리 세트와 겹침: Fleetbench Proto(16.9, 이미 1순위 후보 — 이 논문에서도 BTB 미스 상위), TCMalloc(0.01)·STL cord(0.01)는 탈락, DaCapo tomcat 3.0·h2o 0.24, SPEC2017≈우리 SPEC2026 탈락. **새로 추가할 만한 것**: BenchBase(Java, JIT 참고값; SiBench·Twitter·TATP가 BTB miss 최상위) — JVM이라 pass 밖이지만 B/ISA 논거용 참고값 30분; NodeApp·PHPWiki는 V8/opcache JIT라 불가(WordPress 1.15와 같은 급). 결론: **AOT로 추가할 것은 없고, Proto가 1순위임을 재확인** |
| (참고) 계층형 BTB 계열 다른 논문의 벤치마크 | 확인 가능한 것만 적는다: **BTB-X**(HPCA'23, Asheim·Grot·Kumar)와 **CryptoBTB**(MICRO'25, Adak·Rotenberg·Awad·Zhou) = ChampSim + **IPC-1 traces**(Qualcomm 서버 35·클라이언트 8) + **CVP-1 서버 traces** + SPEC2017 simpoint 94 traces(총 476); **Branch Target Buffer Organizations**(MICRO'23, Perais·Sheikh, Qualcomm)와 **AVM-BTB**(ISCA'24, 1,253 traces)는 본문 접근 불가(같은 공개 trace 계열로 추정); **Twig**(MICRO'21, profile-guided BTB prefetch) = 실제 앱 9종: cassandra·kafka·tomcat(DaCapo), finagle-chirper·finagle-http(Renaissance), drupal·wordpress·mediawiki(HHVM OSS-performance), verilator | trace 기반 논문의 워크로드는 **우리 실기 측정 세팅으로 옮길 수 없음**(Qualcomm 내부 앱의 trace). Twig의 9종 중 AOT는 verilator뿐(우리 57 MPKI, 이미 최상위 결과); 나머지 8종은 JVM/HHVM JIT — cassandra 4.3·tomcat 3.0·kafka 1.0·finagle-chirper 1.2는 이미 측정(§1-A JVM 행), finagle-http는 미측정, HHVM 3종은 HHVM 3.30이 24.04에서 안 떠 미측정(php-fpm 8.3 WordPress 1.15로 대체 측정됨) | JIT 부류라 pass 대상 아님(참고값) | finagle-http 30분; HHVM은 Docker 22.04 이미지로 3시간 | **추가할 것 없음**. 논문 원문(저자·링크)을 주면 목록을 다시 확인한다 |

### 6-2. 그 밖의 후보 — **2026-09-21 전부 측정 완료** (원자료 `llvm_prefetchit/results/newcands_20260921/README.md`)

| 후보 | 측정 결과(고정 코어, 사용 코어 C6 off, 2 GHz 고정) | 분류 |
|---|---|---|
| **ARM core-benchmarks `frontend`** | dfs_chase depth 16 = **72.1 MPKI**(1코어, IPC 0.47), inst_pointer_chase 3000 chains = **48.9**(IPC 0.41); 상류 기본값(1000 chains, text 2.25 MB)은 2.31 | **A 최상위**(Verilator 57·arcilator 79와 같은 급) |
| **ScyllaDB 6.2** | alone 0.40(4코어 33%, 5k–200k ops/s에서 0.36–0.50), 코어 공유 시 **6.05**(이웃 MySQL) / **10.97**(이웃 Rails) | A 아님 / **B 최상위** |
| **MySQL 8.0** | alone **2.35**(4코어 75%), 공유 시 **9.25** | **A + B** |
| **Rails 8 + puma**(CRuby 3.2, YJIT off) | alone **1.91**(4코어 38%), 공유 시 **3.48** | **A + B** |
| **Renaissance finagle-http** | 0.26(4코어 92%) | 탈락(JIT) — Twig 세트 완료 |
| **OpenMM 8.6** | 0.01(4코어 84%) | 탈락(MD 커널, 예상대로) |
| GHDL LLVM 백엔드 | 미측정: `ghdl-llvm` 설치가 호스트 패키지 충돌(libgnat-13 ↔ PPA의 gcc-13-base 13.4)로 막힘 | 보류(GHDL 소스 빌드 필요) |
| BenchBase | 미측정: JDK 23 요구(호스트 21/17), JDK 21로는 컴파일 실패 | 보류(JIT 참고값) |
| HHVM drupal/wordpress/mediawiki | 미측정: JIT라 AOT pass 대상이 아님 — php-fpm 8.3 WordPress 1.15가 대체 표본 | 대상 아님 |
| Ceph OSD | 미시도(클러스터 셋업 1일) | 보류 |

착수 순서(A 부류): **ARM frontend ipc3000 → FleetBench proto → MySQL 8 → Rails**. ARM frontend는 생성기 자체에 `--insert_code_prefetches`가 있어
우리 pass가 넣는 prefetch와 같은 바이너리에서 직접 비교되는 유일한 후보다.

<details><summary>측정 전 우선순위 목록(기록용)</summary>

| 우선순위 | 후보 | 왜 | 예상 | 준비 비용 |
|---|---|---|---|---|
| 1 | **ScyllaDB** (Seastar C++ AOT, Cassandra 호환 NoSQL; CloudSuite data-serving의 YCSB 클라이언트로 그대로 부하 가능) | data-serving(Cassandra JVM) 2.1·DaCapo cassandra 4.3의 **AOT 대응물** — 단일 대형 바이너리라 cold plan·fat-static이 그대로 적용됨. A 부류에서 "JIT라 불가"였던 DB 부류를 도구 범위 안으로 가져오는 유일한 후보 | 2–5 MPKI(shard-per-core라 코어 고정 세팅과도 맞음) | 2시간(공식 이미지, YCSB 클라이언트 재사용) |
| 2 | **ARM core-benchmarks frontend** (§6-1) | stage-1 합성, ISA 논거 | 수십 MPKI | 1시간 |
| 3 | **GHDL LLVM 백엔드 + 더 큰 VHDL 설계** | GHDL mcode NEORV32가 2.8이었고 mcode는 런타임 생성 코드라 pass 밖; LLVM 백엔드는 설계를 elaboration 시점에 AOT 컴파일하므로 pass 적용 가능 — A-1(seq)의 세 번째 flattened 시뮬레이터 | 3–10 (설계 크기에 비례) | 3시간(ghdl-llvm 빌드, 64-bit 코어급 VHDL 설계) |
| 4 | **MySQL 8 sysbench oltp** | MariaDB(0.8–1.1)와 코드베이스가 갈라진 지 오래고 바이너리가 더 큼; 단일 타깃 빌드라 MariaDB의 다중 타깃 문제(A-4)가 없음 | 1–2 | 1시간 |
| 5 | **Ruby on Rails 앱 (YJIT off)** | Django v2(CPython 2.4)와 같은 "AOT 인터프리터 + 큰 프레임워크" 부류의 두 번째 표본 | 2–3 | 3시간 |
| 6 | Renaissance **finagle-http** (JVM, 참고값) | Twig 세트에서 유일하게 안 잰 것 | 1–2 | 30분 |
| 7 | HHVM drupal/mediawiki (Docker 22.04, JIT, 참고값) | 데이터센터 프론트엔드 논문들의 표준 워크로드 | 5–20 (논문 기준) | 3시간 |
| 8 | Ceph OSD (대형 C++ AOT 스토리지 데몬) | AOT 대형 서비스 | 미상 | 클러스터 셋업 1일 — 보류 |
| 9 | OpenMM | 확인용 | ≪1 | 30분 |
| — | IPC-1 / CVP-1 / SPEC2017 traces | ChampSim 전용; 실기 측정 세팅 밖 | — | 해당 없음 |

</details>

B 부류 쪽 추가 후보는 §5의 서버리스(vHive/vSwarm)와 TailBench silo 고부하 재측정 그대로다.
