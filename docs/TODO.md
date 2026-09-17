# TODO — 다음 작업 (2026-09-16 기준, 에이전트가 바로 이어서 진행 가능하도록)

전제: `README.md`의 용어·측정 규칙을 따른다. **PGO = trace로 prefetch 위치만 정하는 것**,
레이아웃을 바꾸는 최적화(AutoFDO/BOLT/-fprofile-use)는 어떤 arm에도 쓰지 않는다.
모든 수치는 NOP twin 대비, 클럭 고정, 인터리브 ≥3회.

## 0. 시작 전 체크리스트 (매 세션)

```bash
cd ~/prefetchit
cat /proc/cmdline                      # 기대: quiet splash efi=nosoftreserve (intel_pstate 활성, 6.8.0-139)
llvm_prefetchit/scripts/platform/freeze_platform.sh show
sudo MODE=3.8ghz llvm_prefetchit/scripts/platform/freeze_platform.sh   # 단일코어(Verilator/JCS) / MODE=2ghz 서비스
llvm_prefetchit/migration/verify.sh --root "$PWD"                      # 소스·패치·툴 해시
export PATH=$PWD/benchmarks/tools/miniforge3/bin:$PATH; set +u; source benchmarks/chipyard/env.sh; set -u   # Verilator 작업 시
```
- 측정 중에는 다른 빌드/실험 금지(공유 서버: `uptime`, `ps`로 확인).
- 끝나면 `sudo MODE=restore …/freeze_platform.sh`.
- 7개 저장소 커밋 후 **push는 사용자 확인 필요**(자동 모드에서 차단됨):
  `for d in profiling jit_prefetch flat_codegen static_prefetch llvm_prefetchit .; do git -C $d push origin main; done; git -C icache_microbenchmark push origin prefetch_benefit`

GRUB 현황: 2026-09-15 재부팅으로 `intel_pstate=disable` 제거됨. 남은 선택지(필수 아님):
`isolcpus/nohz_full/rcu_nocbs=10-31`(기준 호스트가 썼던 격리), 2 MiB hugepage. 스크립트가 스레드를 직접 pin하므로 현재로선 불필요.

---

## 1. Verilator — static pass 대수술 (2026-09-16 진행 결과와 남은 일)

결론(README §2-1): miss는 순차 코드 스트림이므로 static은 **sequential lookahead**(`prefetcht1 D(%rip)`, plan/profile 불필요)로 간다.
qsort 100k 사이클, 3.8 GHz, 3회: seq D=4 KB K=20 + burst4 **1.149x / 1.236x vs twin**(MPKI 56.9→13.7, 함수 자동 선택), D=8 KB K=40 + burst8 1.145x(+4.2% 명령);
dhrystone/median/towers 1.143x(payload 무관), full run 1.139x; arcilator DMB K=10 1.543x. 결과 표: `python3 llvm_prefetchit/results/static_overhaul_20260916/summarize_all.py`.
callsite/continuation 계열(PGO RET 1.02x, RET v3 1.00x)은 원리적 한계 — 1-A/1-B(사이트 선택·앵커링)는 종결.

### 1-A'. seq 모드 튜닝 (남은 축)
- 밀도 K vs 거리 D(측정 완료): 순효과는 K=20+burst에서 1.23x로 포화, 삽입 명령 비용 ≈ 명령 수 증가분(K=20 −5.7%, K=40 −3.4%, K=80 −1.8%).
  D는 4 KB 이상이면 동등(8 KB ≈ 4 KB), burst 4라인이 8라인보다 net이 좋다(명령 비용). 1.14–1.15x plateau — 다음 이득은 **명령 비용 절감**에서 나온다.
- 잔여 miss(seq D=4K 후 MPKI 16.6) trace(`traces/seq_d4096_k20_trace01/`): 55%가 nba_sequent 본문 앞 ~300 B(callee 진입 — burst가 이걸 잡아 14.0),
  38%가 eval_nba__0 중간(COND 58%, CALL 26%). 남은 축: 인접하지 않은(11%) callee 전환, memset/memcpy 반환 직후.
- 명령 비용 줄이기: 7 B 인코딩이 fetch 대역폭을 먹는다. MachineFunction pass에서 정확히 128 B마다 1개(IR K는 p10–p90 31–125 B로 흔들림)
  또는 128 B-pair(adjacent-line prefetcher) 의존 → 마이크로벤치 S=128 결과(D=4 KB에서 S=64와 동등)를 Verilator에서 확인.
- 함수 선택 규칙 일반화(구현·검증 중): `static_prefetch/tools/seq/select_seq_functions.py`(main loop에서 도달 가능한 함수 전부, 3,987개/13.6 MB = miss 97.4%)
  → pass `-prefetchit-seq-functions-file`. **round 4 확인 완료: `seq_d4096_k20_b4_auto` 1.149x / 1.236x vs twin(MPKI 13.7) = regex 버전(1.148x)과 동일** → 이제 Verilator 이름에 의존하는 규칙은 없다.

### 1-A''. plan 기반 static 생성기의 확장성 (2026-09-16 발견)
- `static_prefetch/tools/ret/static_return_target_candidates.py`의 `compute_reachable_depths`(호출 그래프 DFS, max-depth 96)가 60–100 MB 바이너리(llvm-opt, mariadbd, php-fpm)에서 2시간 넘게 끝나지 않는다.
  → 깊이 상한을 8–16으로 낮추고 함수당 메모이제이션을 depth 무관하게 바꾸거나, 큰 바이너리에서는 `--mode footprint`(도달 깊이 불필요)만 쓰도록 static_plan.py에 가드 필요.
  단일 자릿수 MPKI 워크로드의 PGO/static 검증(`llvm_prefetchit/results/pgo_static_20260916/`)에서는 이 때문에 static arm을 생략하고 PGO ceiling만 측정했다.

### 1-A'''. 일반 코드용 PGO planner의 사이트 비용 (2026-09-16 발견)
- `prefetchit_trace_to_plan.py`의 top-sites/budget-8/depth 4–24 정책은 SPEC llvm_r/gcc_r에서 hot loop 안에 사이트를 놓아 동적 명령 수를 ×1.87/×2.87로 불렸다(NOP twin이 0.77x/0.60x).
  Verilator처럼 사이트가 사이클당 한 번 실행되는 코드에서만 안전한 정책. 필요: 사이트별 실행 빈도(LBR 샘플 수 또는 backedge 깊이) 상한, target당 예상 miss 절감 대비 삽입 비용(dynamic count × 7 B) 기준의 선택, 결과 plan의 예상 동적 명령 증가율 출력.
- 검증 표: `llvm_prefetchit/results/pgo_static_20260916/summarize.py` (CXXRTL seq K=80 1.025x, SPEC PGO 음수, WordPress/MariaDB arm 무효·빌드 불가).

### 1-B'. 일반화 검증
- cross-payload: 같은 바이너리로 dhrystone/median/towers(`scripts/static/measure_verilator_variants.sh PAYLOAD=…`).
- full 538,240 사이클 1회(1-C).
- 다른 SoC(LargeBoom/Quad, chipyard-local.patch) — Verilator 재빌드(수 시간) 필요, 우선순위 낮음.
- arcilator DualMegaBoom(`flat_codegen/work/{build,measure}_arc_variants.sh`, K=20 ≈ 100 B 간격): seq가 arc의 saturation 영역(MPKI 79)에서도 먹히는지.

### 1-C. PGO 시간 이득이 기준(7.6%)보다 작은 이유 — 확인 완료 부분
- MSR 0x1a4 = 0(HW prefetcher 전부 on), microcode 0x1000405: 기준 호스트와 동일. 남은 차이는 커널 139 vs 136, 언코어 고정값.

### 1-D. arcilator 재검 → 1-B'로 합침. 1-E. 정리: README §2/§5·`core_results.tsv` 갱신(seq 행 추가 예정).

## 2. 이전에 실패한 워크로드 포함, static 광범위 재시도 (correctness 우선)

**2026-09-16 추가 — 절차에 "miss 스트림 진단"을 넣는다.** flattened 코드(Verilator/arcilator)에서는 plan 기반 static이 아니라 pass의
seq 모드가 정답이었다(README §2-1). 다른 워크로드도 trace를 뜨면 먼저 `static_prefetch/tools/ret/miss_stream_characterization.py`로
(a) sample IP가 LBR[0].to 라인 밖으로 얼마나 흐르는지, (b) miss가 몇 개 함수에 집중되는지를 본다.
- 순차 스트림형(sample IP가 target 라인 뒤로 길게 흐름, 큰 직선 함수) → seq 모드(`SEQ_DISTANCE=4096 SEQ_STRIDE=20`, 함수 집합은
  `static_prefetch/tools/seq/select_seq_functions.py`)를 바로 시도. 후보: 다른 HDL 시뮬레이터(ESSENT, 다른 Verilator 디자인), 생성 코드가 큰
  파서/직렬화 코드(FleetBench proto arena), JIT가 뿜는 직선 코드(4단계 C2와 연결).
- 분산형(수천 지점, DSO 안, target 라인에 국한) → 기존 절차(trace ceiling → plan). 아래 표의 서비스형 워크로드가 여기다.

**2026-09-16 광범위 스크린 결론** (표: README §5, raw `llvm_prefetchit/results/{broad_screen,spec2026}_20260916/`): SPEC CPU2026 43개, gem5, 과학 시뮬레이터 9종,
인터프리터/JIT 8종, 컴파일러, DB 6종(PostgreSQL·MariaDB·ClickHouse·DuckDB·MongoDB·RocksDB), Envoy, WordPress, PyTorch, CXXRTL/GHDL/QEMU — **전부 L2 상주(≤3.3 MPKI)**.
유일하게 통과한 것은 DeathStarBench 마이크로서비스(서비스별 20–92)인데 miss가 libc/libstdc++/jaeger 등 DSO에 분산되어 pass 단독으로는 닿지 않는다.
따라서 static pass의 대상 클래스는 flattened 생성 코드(Verilator 1.149x, arcilator 1.543x)로 확정하고, 서비스 클래스는 "DSO 포함 전체 userland 재빌드"가 전제다.
주의: 서버형 스크린은 `:u` 이벤트로(패키지 MariaDB의 9.3은 커널 fsync 경로), 측정 중 빌드·docker 컨테이너(핀 안 됨) 금지, wrk2 lua는 luasocket 의존 제거본 사용.

워크로드별 절차(모두 동일):
1. **스크린**: `llvm_prefetchit/scripts/platform/screen_l2i_mpki.sh`(또는 서비스는 `campaign_common.sh` 기반 harness)로 부하 상태 L2I MPKI. 한 자리 수 미만이면 제외하고 표에 기록.
2. **trace-guided ceiling**: baseline을 clang-19 `-O3 -g`로 빌드 → trace 3회 → `prefetchit_trace_to_plan.py` → pass 빌드 → resolve/reanchor/drift → NOP twin → A/B. **ceiling이 없으면 static도 없다** — 여기서 멈추고 기록.
3. **static**: `static_prefetch/tools/static_plan.py --kinds ret|cond|ret,cond` → 같은 경로 → PGO 대비 비율 보고.
4. **correctness 체크리스트**(하나라도 실패하면 결과 폐기): objdump prefetch 개수 = 계획 수(클론 허용), `check_prefetch_drift.py` ≥90%(callsite 계열), `validate_prefetch_asm.py`(resolved plan 기준) 100%, NOP twin과 명령 수 동일, 완료 작업량/오류 0 동일, 클럭 고정 로그, 스레드 pin 감사(`valid=1`), 인터리브 순서 기록.

우선순위와 출발점(`llvm_prefetchit/archive/scripts/`에 과거 빌드/실행 스크립트가 있다 — 경로는 `scripts/…`가 `scripts/static|dispatch|platform/…`로 바뀌었으니 수정해서 쓸 것):
| 워크로드 | 왜 다시 | 스크립트 |
|---|---|---|
| MicroSuite Router / HDSearch / SetAlgebra / Recommend | MPKI 25–85, 이전 결론은 재앵커링 이전 파이프라인 | `build_microsuite_lbr_pgo_variants.sh`, `run_final_microsuite_paired.sh`, `build_setalgebra_*`, `run_router_*` |
| PostgreSQL TPC-C (sysbench-tpcc) / pgbench | MPKI 51, "밀도 sweep 전부 음수"가 drift 때문일 가능성 | `build_postgresql_lbr_pgo_variants.sh`, `run_final_postgresql_paired.sh`, `archive/work/pg_tpcc_variants` |
| DeathStarBench PostStorage(fat-static) | 74% miss를 메인 바이너리로 끌어온 빌드 존재 | `flat_codegen/dsb_build/` |
| TailBench Silo/Shore/Masstree | MPKI 있음, 짧은 실행 → 실행 길이 늘려서 | `run_tailbench_highmpki_pgo.sh` |
| FleetBench proto arena | high MPKI | `build_proto_arena_lbr_pgo_variants.sh` |
| Verilator 다른 SoC(LargeBoom/Quad), Chipyard 다른 payload | static 일반화 검증(qsort로 튜닝, 다른 설계로 평가) | `run_verilator_crosspayload_transfer.sh`, `chipyard-local.patch`의 `QuadMegaBoomConfig` |
| 신규 후보 | computed-goto 인터프리터(CPython/QuickJS/wasm3, 큰 앱), 이벤트루프(nginx 모듈 다수), 와이드 API 서비스 | 스크린부터 |

산출물: 워크로드 × {baseline MPKI, PGO(trace) NOP-twin 비율, static 비율, static/PGO}를 한 표로 `README.md` §5 갱신.

---

## 3. manual 위에 static 얹기 — 추가 효과 확인

- 대상: Django `d4_next`, FeedSim `d16_target_next`(manual이 이미 있는 변형).
- 방법: manual 변형 바이너리를 baseline으로 삼아 trace 3회 → 남은 miss로 PGO plan/static plan → pass 주입(FeedSim은 `build_feedsim_manual_variants.sh` 경로에 `-fpass-plugin` 추가; Django는 `libicachebuster.so`와 uWSGI/CPython 양쪽 — 남은 miss가 어디에 있는지 trace로 먼저 확인) → NOP twin → A/B.
- 보고: base → manual → manual+static의 QPS/MPKI 단계별 표. manual이 놓친 miss(예: Django의 CPython 인터프리터 코드)가 static으로 잡히는지가 핵심.
- 반대 방향도: static/PGO만으로 Django/FeedSim의 ICacheBuster 디스패치를 잡을 수 있는가(README의 "IndirectCallTargetPrefetch" 아이디어: `load fptr; call fptr` 패턴을 pass가 인식해 다음 원소 target을 prefetch) — 성공 시 3단계 결과를 컴파일러 결과로 승격.

---

## 4. JVM에도 static/PGO 시도

- 4-A. **libjvm.so + AOT 부분에 pass 적용**: tomcat miss의 8.4%가 libjvm; JDK 빌드에 `-fpass-plugin` 넣어 trace-guided plan을 libjvm에 주입(GOT/DSO 모드 `prefetchit_external_got_plan.py`). 기대치 작지만 절차 검증용.
- 4-B. **C2 안에서 trace-guided/static**: MDO(메서드 프로파일)를 static 랭킹의 대체 입력으로 써서 V4 burst 사이트를 hot nmethod/entry로 제한(`PrefetchEntryMinBytecode` 게이트를 카운트 기반으로). 대상 워크로드는 L1I≈L2I 스크린(`screen_full_suites.sh`, L1I 컬럼) 통과분만.
- 4-C. **public 워크로드 찾기**: Spring PetClinic/Boot 레퍼런스 앱(wrk), Elasticsearch/OpenSearch, Solr, Kafka Streams, Keycloak, SPECjbb2015 — 스크린 표에 L2I·L1I 모두 기록. tomcat류(L2-resident)는 `prefetchit0`가 살아있는 파트/마이크로코드에서 `-XX:+PrefetchEntryIT0`로 재시도.
- 수용 기준: 자작(JCS/WideApi)이 아닌 워크로드에서 NOP-free JVM 플래그 A/B ≥5%.

---

## 5. 기록 규칙
- 결과 디렉토리 `<topic>_<yyyymmdd>/`, 요약은 README §2/§5 표와 `core_results.tsv`에만(새 md 로그 만들지 않기).
- 실패도 원인(축: MPKI, 결정성, FE-bound, L1I≈L2I, L2 데이터 압력, 정확성 게이트)과 함께 표에 남긴다.

### 2026-09-17 post-link / DSB 후속 (미착수)
- **post-link stub 비용 절감**: 직접 call 사이트는 stub 대신 callee 앞 padding에 prefetch를 두는 방식, PLT 사이트는 in-place 16 B 활용 → 명령 +5.7%를 1% 이하로. 그러면 DSB pgo75의 MPKI −11%가 그대로 cycles로 갈 수 있다(`flat_codegen/dsb_build/postlink/RESULTS.md`).
- **planner 리드 조건 강화**: 사이트 선택 시 lead ≥100 cycles·사이트 실행 빈도 상한을 함께 최적화(현재 c90/c75 cap은 coverage를 너무 잃음, 37%/16%).
- **DSB 구조 문제 보고**: 컨테이너 간 L2 오염(스레드 71개 상주, 동시 실행 1~4개, 요청 사이 idle 중 오염)이 miss의 주원인 — 코어 고정 1.51x. 프리페치 논문에서 DSB를 쓸 때는 cpuset 고정 + 스레드풀 설정을 baseline으로 삼아야 한다.
- `anchors_for()`는 `.plt` 이름만 읽어 `.plt.sec`(IBT) 바이너리에서는 anchor를 못 찾는다 → `.plt.sec`/`.plt.got` 지원.
- `flat_codegen/scripts/project_env.sh`가 자기 자신을 source 하여 bash가 segfault(재귀) — `rebuild_deps_env.sh`에서는 제거했지만 다른 August 스크립트도 점검 필요.
