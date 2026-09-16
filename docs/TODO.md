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

## 1. Verilator 재현 — static 파이프라인 대대적 수정

현재: PGO(trace) RET cov90 = 1.021x vs NOP twin, MPKI −6.6%. static 4종 모두 ≤1.003x.
근본 원인: (a) 고른 사이트가 miss를 만드는 call이 아님(15% vs 가능 65%), (b) 사이트 앵커링이 debug line 기반.

### 1-A. static 사이트 선택을 "producing call" 기준으로 다시 설계
- 진단 스크립트(README §2)와 같은 방식으로 trace에서 **RET miss를 만든 call**(LBR에서 RET 직전의 CALL, `call_end == LBR[0].to`)을 뽑아 정답 집합을 만든다 → `static_prefetch/tools/ret/evaluate_static_targets.py`에 `--metric producing-call` 추가.
  현재 metric("site가 LBR 32개 안에 있음")은 너무 느슨해서 0.56이 나오지만 실제 커버는 0.15였다.
- 프로파일 없는 hotness proxy로 **call 단위** 랭킹: caller 루프 깊이/backedge, callee의 정적 호출 수, callee 크기, 같은 라인으로 return하는 call 전부 포함(budget>1). 후보 파일 `static_return_target_candidates.py`의 컬럼(`caller_backedges`, `call_in_loop`, `callee_cachelines`…)을 그대로 활용.
- 평가 루프(빌드 없이): 정답 집합 대비 top-K 커버율 곡선(K=1k…10k)을 `static_plan.py --kinds ret` 옵션별로 그려 65% 근처 정책을 찾는다. 그다음에만 빌드(35분/변형).
- 수용 기준: static plan이 PGO plan MPKI 감소의 ≥80%, 시간 이득 ≥ PGO의 80%, NOP twin 대비.

### 1-B. 사이트 앵커링 정확성
- 현재: IR pass가 (함수, 파일, 라인, 분기종류)로 사이트를 찾고, 같은 라인 후보는 baseline 오프셋 순위로 매핑(`ranked_sites`). top5k에서 52%만 제자리 → 랭킹 매핑 후 재빌드해 `check_prefetch_drift.py` ≥90%인지 확인.
- 근본 해결: post-ISel/MachineFunction 단계에서 **기계어 오프셋으로 사이트 지정**(design.md "known limits"). 또는 링크 후 재앵커링 방식으로 사이트도 검증(prefetch 뒤 call의 순번 k' == plan의 k).
- target 재앵커링은 call 순서 기준(`reanchor_prefetch_targets.py`). COND/JMP 계열 plan에는 분기 순서 기준 앵커를 추가(`--anchor branch`).

### 1-C. PGO 시간 이득이 기준(7.6%)보다 작은 이유
- 이 호스트 baseline IPC 0.62 vs 기준 0.56(같은 명령 수, 같은 MPKI). 확인할 것: HW prefetcher MSR 0x1a4(`sudo apt install msr-tools; rdmsr -p40 0x1a4`, 기준은 0), 마이크로코드(0x1000405), 언코어 고정값(2.2/2.5 GHz), 커널 139 vs 136.
- 100k cycle 대신 full 538240 cycle로도 1회 확인(기준 캠페인은 full run).

### 1-D. arcilator 재검
- `flat_codegen/scripts/`의 s4la16 결과(1.051x)는 재앵커링 도구 이전의 것. 같은 빌드 경로에 `resolve → reanchor → drift` 게이트를 넣고 다시 측정.

### 1-E. 정리
- 결과를 `llvm_prefetchit/migration/core_results.tsv`와 README §2 표에 반영. 재현 안 되는 기준값은 지우지 말고 "not reproduced"로 남긴다.

---

## 2. 이전에 실패한 워크로드 포함, static 광범위 재시도 (correctness 우선)

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
