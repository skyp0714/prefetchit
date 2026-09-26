# TODO — 다음 작업 (2026-09-22 갱신)

전제: `README.md`의 용어·측정 규칙과 `docs/prefetch_plan_by_miss_class.md` §0의 세팅(코어 고정, 사용 코어 C6 off, 현실적 부하,
alone/interleaved 두 regime, `:u` 카운터, NOP twin, 같은 라운드 인터리브 ≥3회)을 따른다. **PGO = trace로 prefetch 위치만 정하는 것**,
레이아웃을 바꾸는 최적화는 어떤 arm에도 쓰지 않는다. 2026-09-17의 공유 코어·C6 켜진 세팅 결과는 참고값(`docs/archive/`)이며 목표치가 아니다.
서비스 후보 선택은 **활용률 ≥15%인 유효 부하 중 baseline MPKI 최대점**으로 한다(2026-09-22 사용자 합의). 전체 sweep과 오류율·지연을 남기고, 배치의 정상 포화 실행은 유지한다.

## 0. 시작 전 체크리스트 (매 세션)

```bash
cd ~/prefetchit
llvm_prefetchit/scripts/platform/freeze_platform.sh show
sudo MODE=3.8ghz llvm_prefetchit/scripts/platform/freeze_platform.sh   # 단일코어(Verilator) / MODE=2ghz 서비스
# 서버 코어 C6 off: for st in /sys/devices/system/cpu/cpu{N..M}/cpuidle/state*; do [[ $(cat $st/name) == C6* ]] && echo 1 | sudo tee $st/disable; done
llvm_prefetchit/migration/verify.sh --root "$PWD"
export PATH=$PWD/benchmarks/tools/miniforge3/bin:$PATH; set +u; source benchmarks/chipyard/env.sh; set -u   # Verilator 작업 시
```
- 소켓 1(코어 0–42)만 사용, 측정 중 빌드 금지, 끝나면 `MODE=restore` + C6 재활성 + `docker compose down -v`.
- DSB socialNetwork는 `flat_codegen/dsb_build/postlink/reset_sn_stack.sh`로 올린다(redis 스냅샷 off, 새 볼륨, 그래프 로드).
- 긴 체인은 단계마다 `timeout`, 인자 없는 `wait` 금지, `pgrep` 패턴은 `^`로 앵커(스크립트 자기 자신·툴 셸 매칭 사고 3회).
- 저장소는 `prefetchit` 하나다(2026-09-22 통합, 6개 컴포넌트 history 보존). 커밋 후 **push는 사용자 확인 필요**.

---

## 1. A 부류(capacity) — `docs/prefetch_plan_by_miss_class.md` §2

### 진행 중: JVM 100블록·miss 타깃 분석·CloudSuite/HP 확장 (2026-09-25)

- [현재 확장 실험](class_a_expansion_20260925.md): Pinot F16 / Spring GF / Flink G 각각 새 100블록(base/prefetch/NOP) 재검증 시작. L3 code miss 총량·precise sTLB miss target·Intel PT 경로 분석을 준비하고 CloudSuite JVM 및 HP qualification을 이어간다. 이전 HP 실행 보류는 사용자가 해제했다. 중간 양의 평균을 성공으로 세지 않는다.

### Hierarchical Prefetching 논문 후보 대조 (2026-09-25)

- [11개 구성 대조 및 후보 목록](hierarchical_prefetch_candidates_20260925.md): MySQL/sysbench는 기존 실험과 겹친다. Beego·Gin·Echo·Caddy·DGraph·GORM/PostgreSQL·TiDB/sysbench·TiDB/TPC-C·MySQL/SiBench·MySQL/YCSB의 **10개 당시 미측정 구성**을 등록했다. 최초에는 목록만 유지했으며 후속 요청으로 실행 보류를 해제했다. ASPLOS 2025 HP와 기존 BTB-Ferret 후보를 구분한다.

### 1-0-A3. 먼저 정상 설정·cold target을 선별 (2026-09-24)

- [qualification 결과](class_a3_qualification_20260924.md): gem5 O3/Timing/Ruby 5설정 0.0034–0.0575 MPKI, Envoy 정상 proxy/JWT/RBAC/TLS/gzip 최대 0.3640, μSuite SetAlgebra 정답 검증 수정본 3k QPS 전체 0.0444. 새 고MPKI 후보 없음; prefetch 삽입/새 gain 주장 없음.
- SetAlgebra 옛 결과는 그대로 재사용하지 않는다. 인자 누락·내부 진단을 분리했고, response vector 전달 및 빈 교집합 처리 버그를 실험용 복사본에서 수정했다. 1k/3k QPS는 14만 응답 정답 일치, 6k는 요청 오류 1건으로 제외했다. patch와 재현 script를 증거 묶음에 보존하고 생성 바이너리는 정리한다.
- [추가 탐색](class_a_search_20260924b.md): **Ceph RGW를 새 후보로 확인**. SigV4/cephx, RADOS 3중 복제의 GET/LIST/PUT 혼합에서 로그를 꺼도 4-worker MPKI 7.62, 1-worker/core MPKI 5.91–6.96(활용률 30–49%, 오류 0). PEBS/LBR의 간접 CALL target 같은 line 8.88%, +256 B 10.89%; 직접 CALL은 30.19%/41.27%여서 A-2/G도 가치가 있다. 제한된 정적 callee/NOP 정책 2개는 +0.007%/−0.131%로 탈락. live-target F/F+G는 아직 미실험이며 execute 하나보다 auth/SAL/completion 전체를 검토한다.
- ATS 초기 높은 MPKI는 ET_NET affinity가 전체 코어로 풀린 결과라 폐기했다. 실제 TID pin 뒤 cache hit는 0.008–0.014, TLS mix는 0.148–0.198. 모든 service 측정에 TID mask 전후 검사를 적용한다. LibreOffice, ns-3, OMNeT++, Cppcheck, Yosys의 정상 작업도 낮은 MPKI로 탈락했다. PostgreSQL/ClickHouse/MongoDB의 정상 mixed-query 경로는 여전히 미탐색 후보다.
- 활용률 ≥15%·오류/지연 조건 통과점 중 최대 MPKI를 선택한 뒤, baseline PEBS L2 miss + LBR로 **indirect CALL target의 cold coverage**를 확인한다. 간접 분기 빈도 자체를 miss 기여라고 부르지 않는다. 별도 ITLB walk/STLB-hit 진단 후 live target 위치를 정적 분석으로 hoist하고, depth/lead 부족 때만 예측한다.

### 1-0-A2. 남은 복잡한 control flow workload (2026-09-23)

- [실험 기록](class_a2_campaign_20260923.md): FeedSim v2는 약 5% CPU 절감 확인. Rails/MySQL/Silo의 static padding 및 LBR 후속에서 3% 미달. Django의 추가 네 LBR 정책도 3% 미달. Media는 전체 C++ 서비스 info 로그·매 실행 새 스택으로 다시 검증했으며, MovieId/ComposeReview/Rating의 최선 단일 관측은 +0.13/+0.56/+1.18%로 미확정이다. 전체 workload의 3% 목표는 미달성.
- [커널 경계 후속](class_a_kernel_20260923.md): Media return-code prefetch는 새 5 paired 라운드에서 유의한 이득 없음(static 세 서비스 CPU 합계 +0.14%, NOP 대비 dynamic −0.10%). MySQL 전이 스크린은 +0.33~0.38%로 미확정. 전체 workload ≥1% 목표도 미달성이다. 커널 I-cache stall의 조건부 회수 모델과 실측 이득을 구분한다.
- LLVM CPU2026 refrate의 모든 입력·출력을 검증했고 합산 L2I MPKI 1.489, FE 39.6% / BE 15.5%를 확인했다. 09-24 전체 reference mix의 두 라운드에서 static call512/call2048/wrapper2048의 CPU 효율은 −0.0018/−0.0148/+0.0589%로 중립이었다. 출력 SHA-512는 모두 통과했고, 제한된 NOP-site 정책의 결과를 성능 상한으로 해석하지 않는다. GCC는 선택한 `gcc-pp.c`만 1.098이고 전체 reference mix는 0.672다.

- A-1은 Verilator/arcilator/CXXRTL 순차 스트림으로 분리. A-2는 DCPerf v2 Django/FeedSim, media 서비스, MySQL/Rails, 정상 부하를 만족하는 TailBench DB를 대상으로 한다. ARM은 합성 대조군.
- 각 workload에서 약 3%를 목표로 탐색한다. 기준은 baseline 활용률 ≥15% 중 MPKI 최대의 정상 부하이며, 5회 독립 확인과 NOP twin을 통과한 결과만 prefetch 이득으로 보고한다.
- 기존 Django의 반복 prefetch 과발행, FeedSim의 trace 수집 실패, media의 발행 비용, DB의 다중 타깃 링크 문제를 출발점으로 삼는다. 실패한 과거 스크립트를 그대로 재실행하지 않는다.
- 09-22 call-graph 전이의 Verilator 결과는 dense 0.98792x / sparse fixed-layout 0.98627x(3회), NOP 대비도 이득 없음. 기존 A-1 sequential 정책의 성공과 별개다.

### 1-0. FleetBench proto 확장 (2026-09-22, 3% 확인·5% 탐색)
- 최초 5개 실패 → 30개 추가 탐색에서 +0.53–0.56% → latency/coverage 후속 22개 구성에서 **CPU +3.48%(seed 0) / +3.44%(seed 1)** 확인. Wall +3.52% / +3.44%, NOP 대비 +4.40% / +4.46%. 기본 Arena·100 iterations, 1코어 2 GHz/C6 off, seed별 5회이며 10개 paired 라운드 모두 CPU/wall +3% 이상. 숫자는 README §5·`core_results.tsv`, 절차·한계는 [후속 기록](class_a_proto_lead_20260922.md).
- 정적 schema에서 정확히 두 단계 아래 타입을 예측하고, 함수 크기 안에서 최대 8개 라인 및 생성자 경로를 포함한다. 중복 발행을 줄인 최종 정책은 2,764 sites / 19,718 T1. 명령 +1.02–1.03%, absolute speculative L2 code miss −21.25–21.27%.
- 추가 22개 구성에서 Arena의 5% 목표는 미달, 기존 후보 유지. 동일 바이너리·정책의 upstream NoArena는 CPU +2.18% / NOP 대비 +3.12%(3회). [확장·전이 기록](class_a_generalization_20260922.md).
- 공통 정적 그래프 planner를 분리했다. ARM 합성 ipc3000은 4단계 선행·1라인으로 CPU +9.20% / NOP 대비 +10.42%(새 5회), 기본 ipc1000은 NOP 대비 중립. 적은 backend stall에서 lead/발행 비용을 맞춘 ideal-case이며 범용 실서비스 성능 주장은 아니다.
- 다음: 정적 경로 길이로 lead를 추정하고 함수 alignment 여유와 코드 증가량으로 발행 예산을 제한한다. ARM의 1라인은 .text +104 B, 넓은 정책은 +17.1%였다. 고정 depth/coverage를 모든 A workload에 적용하는 정책은 아직 확정하지 않는다.
- NOP 도구는 custom executable section과 prefix 표기까지 검증한다. 새 harness는 HWP까지 고정·복원한다. 이전 세션의 sysfs 클럭 표기만으로 현재 부팅 환경의 주파수를 가정하지 않는다.

### 1-A. Verilator/arcilator seq 모드의 명령 비용 절감 (검증된 1.149x/1.543x 위에서)
- MachineFunction pass에서 정확히 128 B 간격으로 `prefetcht1 D(%rip)` 1개(IR K=20은 31–125 B로 흔들려 명령 +6.4%, twin −5.7%).
- 잔여 miss: 인접하지 않은 callee 전환(11%), memset/memcpy 반환 직후 → burst 규칙.
- 일반화: LargeBoom/Quad, ESSENT. 결과 표는 `results/static_overhaul_20260916/summarize_all.py`에 행 추가.

### 1-B. DCPerf v2 DjangoBench (CPython, 2.4 MPKI @68%) — A-2/링크 단위 통합
- CPython 3.x를 `-O3 -g -fpass-plugin` 으로 재빌드(venv_cpython의 인터프리터 교체), uwsgi 워커 4개 코어 36–39, C6 off.
- LBR/rate trace → cold plan v4 → 명령 샘플링 → v10 → NOP twin 5회. `dcperf_v2_screen.sh`의 서버 패턴 `^uwsgi --ini`, `JAVA_HOME=JDK 11`.
- 보고: base / plan / twin의 wrk 처리량과 uwsgi MPKI.

### 1-C. media C++ 서비스 alone — 09-23 production 설정 재검증
- info 로그·새 스택·2,500 RPS에서 MovieId/ComposeReview/Rating MPKI 1.405/2.777/0.711. 다섯 정책씩 단일 스크린 최선 +0.13/+0.56/+1.18%, 3% 미달·확정 이득 아님. User+kernel Top-down은 FE 23–26%, BE 47–50%로 user-only FE보다 불리하다. [측정·제외 사유](class_a2_campaign_20260923.md).
- media 스택용 `build_utl_variant.sh`(SVCBIN=MovieIdService 등) + fat-static; C6 off alone regime에서 gs / plan v10 / twin.
- 이 빌드가 2-A의 베이스가 된다.

### 1-D. FeedSim v2 — array lookahead 5% 확인
- v2-beta b109b09의 원본 함수 포인터 배열 유지 확인. full DLRM/RPC/TLS/ZSTD·40 QPS에서 lead4·진입 1라인 T1, 새 paired 5회 CPU/request −5.19%, NOP 대비 −4.95%, 모든 SLA 통과. 포화 throughput +4.99%는 일부 baseline/NOP SLA 초과로 SLA-qualified capacity로 쓰지 않는다.
- 현재 source prototype이며 자동 compiler transform은 미구현. 배열에서 미래 타깃을 읽을 수 없는 A-2로의 일반화는 별도 과제. [실험·근거](class_a2_campaign_20260923.md).

### 1-E. post-link 재작성기 비용 절감 (스토어용, 설계 문서 구현 3)
- 직접 call 사이트는 stub 대신 callee 앞 padding에 prefetch, PLT 사이트는 in-place 16 B → 명령 +5.7% → <1%. mongodb/redis/memcached에 C6-off alone에서 재시도.

### 1-F. A-3: 미래 함수 포인터 기반 코드 prefetch
- **09-24 8시간 후속 완료**: FeedSim staged entry12/body4는 새 paired 5회 CPU 효율 **+8.54% [8.14, 8.94]**, 기존 lead4 대비 **+2.09% [1.86, 2.32]**. 정상 40 QPS의 leaf CPU/request 기준이며 capacity 향상은 미측정. A-1 추가 정책, A-2 LLVM, A-3 Scylla offline/실제 callback의 새 ≥1% 이득은 미확인. component·graph 결합 및 최종 검증은 [후속 기록](class_a_overnight_20260924.md).
- **09-24 dispatch 확장 완료**: Media RPC·MySQL live-target 스크린 미통과. Scylla는 queue 깊이 부족을 계측한 뒤 aggressive online/frozen 모드까지 검증했으나 새 5쌍 +0.08% [−0.84, +1.01], NOP 대비 +0.19% [−1.51, +1.92]로 유의하지 않음. 예측 정확도 97.22%와 달리 miss/op 감소는 2.45%. 후보들은 A-3 방법으로 분류하되 Scylla B/interleaved regime 유지. VPP AF_PACKET low-MPKI, Envoy/Social은 새 고-MPKI 최적화 검증 없음. [기록](class_a3_dispatch_20260924.md).
- 다음 판단점: 예측한 주소의 **실제 cold line·노출 stall coverage**를 먼저 계측. successor 정확도만 높이는 확장은 근거 부족. 새 성공이 없어 정적 그래프 결합 후속은 아직 실행하지 않음.

- FeedSim 배열 lookahead를 A-3으로 분류했다. 09-23–24 새 paired 5회에서 F 단독 **+6.13%**, 정적 G **−0.43%**(CI가 0 포함), F+G **+6.17%** CPU 효율. G 추가분은 +0.04%(95% CI −0.84~+0.93%)로 미확인. full 40 QPS와 모든 유효성 기준 유지. **FeedSim은 F 단독 유지**.
- protobuf 미래 원소·merge/copy의 다섯 정책은 모두 baseline보다 느렸다. 별도 paired 5회에서 F **−0.46%**, 기존 schema G **+3.45%**, 결합 **+2.81%**. **FleetBench는 G 단독 유지**. [A-3 실험·범위·원시 근거](class_a3_campaign_20260923.md).
- 남은 과제: 미래 target load의 bounds/lifetime/메모리 의존성을 증명하는 범용 compiler transform. 현재 결과는 두 source prototype이며 임의 C++/RPC dispatch 일반화 성공은 미확인이다.
- 아래 간접 분기 비중은 09-21 진단이며 실제 prefetch coverage나 성능 상한을 뜻하지 않는다.
- proto의 위 비율은 이전 이벤트 기반 분석이다. 09-22의 retired-L2 trace에서는 miss가 여러 생성 함수에 분산됨을 확인했으므로, 아래 6사이트의 실제 retired-miss coverage를 재검증한 뒤 구현한다.
- 추가 실험: 이미 계산된 SSA target을 일찍 사용하는 모드는 구현·스크린했으나 NOP 대비 뚜렷한 이득이 없었다. 새 pointer load를 추측 실행하지 않는다. Proto에서는 정적 schema type graph로 child entry를 예측하는 §1-0 방식이 더 나았다.
- proto: IR pass에 indirect-call target hoisting 모드(`ClearNonEmpty`·`MergeIntoClearedMessages`·`InternalWriteMessage` 등 6사이트 = miss 15%) → NOP twin 비교.
- Django: ceval `DISPATCH()`에 다음-다음 opcode 핸들러 prefetch(레지스터 계산) → uwsgi MPKI·처리량.

### 1-G. MariaDB 타깃별 주입 (설계 문서 구현 2, 우선순위 낮음, 0.8–1.1 MPKI)

---

## 2. B 부류(interleaving) — `docs/prefetch_plan_by_miss_class.md` §3

- **09-26 추가, 10% 목표**: [최종 실험 결과](class_b_headroom_20260926.md). 가중 병합·trace 문맥 커널 버스트·NOP 공간 coverage 구현 완료. MPKI 57.38 운영점의 독립 7쌍에서 새 후보는 baseline 대비 전체 타깃 CPU 2.01% 절감(95% CI 1.61~2.41%)이나, 기존 wake16 대비 0.62%(−0.09~1.33%)로 추가 이득 미확정·승격 안 함. 10% 미달. 커널 T1의 캐시 warming은 확인했으나 실서비스 3정책은 풀 CPU 순이득 없이 기각. 관련 테스트16개·lifecycle5개 통과, platform/HWP 1,474개 복구 비교 통과. 탈락 산출물은 근거 보존 후 정리.

### 2-0. wake-stream (2026-09-21, `docs/prefetch_plan_classB_wakestream.md` §7) — 2-A/2-B보다 우선
- **최종(18:05, 5회)**: p11a(dense drip + post-call run 시작부) **1.054x, MPKI 86.6→76.9, 명령 +2.8%**; static plan 1.006x, callee-burst static 1.015x(twin 1.011x). 14 라운드의 결론과 안 되는 것 목록은 §7-21. pass에 `after_call`/`@n` 사이트 종류 추가됨(PrefetchITPass.cpp, 백업 .bak_postcall). `media_stack.sh down`에 `-v` 추가(익명 볼륨 207개·14 GB가 디스크를 채웠음).
- **구현·측정 완료(movie-id interleaved, R=600, 3회, 8 라운드)**: LD_PRELOAD 1.014x → inline drip 1.031x → 아카이브 사이트 **1.046x**(wsp3; 재측정 1.050/1.037) → coverage·overhead·lead 스윕(라벨, 128 B 페어, gap filler, fall-through 제외, d 8–32)은 모두 ±1% 안 = **이 계열의 상한 ≈1.05x**(§7-14). prefetchit1은 같은 자리에서 0.982x. preload stage 0은 래퍼 비용에 지워짐. 남은 일: pass post-call 사이트(run 시작부 inline), glibc 정적 링크, compose-review/compose-post, 5회 확정. 도구 `flat_codegen/dsb_build/media/ws/`; DSB 소스에 mark 패치 적용 상태(`ws_patch_src.sh revert`).
- §5 순서대로: 심볼화 수정(`MovieIdService=0` — 현재 ab_hi의 `effhi` arm은 빈 plan이라 무효) → fill-queue microbench(Q)·L3 latency → interleaved **Intel PT** trace → `run_paths.py`/`wakestream_plan.py` → pass post-call 사이트(rdtsc 게이트, 표 방식 burst) → movie-id A/B(SWPF 카운터, 게이트 G1–G3).

### 2-A. 프로세스 안 상한 확정 (B-1)
- 1-C의 빌드로 media movie-id/compose-review + socialNetwork compose-post를 **C6 off + 8/16코어 pool** 세팅에서 gs / plan v10 / twin, 5회.
- 도구: `dsb_shared_screen.sh`(pool), `dsb_warm_ab2.sh`(SVC/SVCBIN/LUA/WRK_URL/CONN/R 환경변수), `cold_plan.py`(--site-exec 가지치기).

### 2-B. RPC 디스패처의 method별 warm-up (B-2)
- thrift generated `process_<method>` 진입을 method별 사이트로 사용, 사이트당 ≤32라인, 2·3차 배치는 handler 진입·첫 하위 RPC 직전.
- plan 생성기: LBR 창의 handler 이름으로 miss 라인을 method별로 귀속(`cold_plan.py --by-method`).

### 2-C. affinity sweep (B-5, 대조군)
- pool 안에서 코어당 공유 서비스 수 1·2·3·전체로 cpuset 그룹을 만들어 MPKI 곡선. `dsb_shared_screen.sh`에 그룹 배치 모드 추가.

### 2-D. 커널 switch-in prefetch 모듈 (B-3)
- `llvm_prefetchit/kernel/wake_prefetch/`: opt-in TGID/mm, pinned executable page의 kernel alias, 8/16/32/64라인 T1/NOP, saved user IP/syscall profile. 등록은 root 전용 misc-device ioctl. 현재 헤더 빌드와 기본 runtime smoke를 통과했고 모듈은 언로드했다.
- 기존 trace의 추정 hook 이름은 정확한 syscall 번호가 아니다. 새 context 수집과 held-out 검증 후 user-timeline·compose-post·media를 비교한다.
- module-off/no-plan/NOP/PF 및 user-stream 조합을 비교하며, outgoing task에 잡히는 callback 비용까지 공유 풀 전체 CPU로 확인한다. 권한 확보·기본 runtime 검증 완료, 실서비스 성능 검증 대기.

---

## 3. 미측정·미완 벤치마크 (`docs/prefetch_plan_by_miss_class.md` §5, 2026-09-19 밤 갱신)
- 09-24 JVM 확대 허용: 신규 데이터센터 A-3 후보 **Artemis, Keycloak, Flink/Nexmark, OpenSearch, Pinot**의 실제 dispatch 소스를 확인했다. 높은 MPKI/이득이 확인된 5종이라는 뜻은 아니다. [운영 설정·target/lead-time 가설·JVM 구현 조건](class_a_jvm_candidates_20260924.md). 기존 Solr/Cassandra/Trino/DaCapo는 중복 후보로 세지 않는다.
- [기존 JVM 후보 재측정](class_a_jvm_recheck_20260924.md): Solr 0.90, 별도 Cassandra 0.92–1.77, Trino 0.17–0.43 MPKI. CSV 없는 DaCapo 최대는 Cassandra 3.28, Tomcat 2.91, Spring 2.06. Cassandra/Spring PEBS에서 간접 CALL+JMP 같은 line 6.70%/9.53%, 직접 CALL 13.80%/25.59%로 A-2/G도 우선 검토한다. Spring filter/interceptor 및 Cassandra transform/completion은 A-3 보류 후보이며, 새 삽입 이득·predictor 필요성은 미확인이다. 신규 5종을 모두 실측한 것으로 세지 않는다.
- 완료(탈락): DCPerf v2 batch 6종, TaoBench(클라이언트 확인), CloudSuite graph/in-memory-analytics, DaCapo h2o/fop/kafka, TailBench img-dnn/moses/shore/masstree, FleetBench 7종.
- **FleetBench proto_benchmark 확장 완료(09-22)** → §1-0. static schema 정책의 +3.44–3.48% 확인, 3% 목표 달성.
- 추가 후보 **측정 완료(2026-09-21, `llvm_prefetchit/results/newcands_20260921/`)**: A 부류 신규 = ARM core-benchmarks frontend(dfs16 **72.1**, ipc3000 **48.9** MPKI, 1코어), MySQL 8(**2.35**, 4코어 75%), Rails+puma(**1.91**, 4코어 38%); B 부류 신규 = ScyllaDB(0.40 → **6.05–10.97** 공유 시), MySQL 8(→**9.25**), Rails(→**3.48**). 탈락 = ScyllaDB alone, finagle-http 0.26, OpenMM 0.01. 보류 = GHDL-LLVM(apt 충돌), BenchBase(JDK 23), HHVM(JIT), Ceph(셋업).
- 다음 착수 순서(A 부류): **proto schema 정책 비용 절감·일반화(§1-0), ARM frontend 메커니즘 대조 → MySQL 8 → Rails**. ARM frontend는 upstream 기본 footprint와 ipc3000을 함께 재고, 합성 결과를 실제 서비스의 개선으로 보고하지 않는다.
- 진행 중/미완: adsim 설치(libaegis 추가 후 재빌드), cdn_bench 측정(IPv6 루프백), TailBench silo/sphinx/xapian(입력 재다운로드), ucache_bench(디스크), data-analytics(YARN NodeManager 등록 실패), media-streaming(클라이언트 ssh), video_transcode 클립, WDL/Mediawiki/Spark, μSuite SetAlgebra/HDSearch, 서버리스(vHive/vSwarm), hotel Go 삽입기.
- 보관 정책(2026-09-24, 사용자 지시): 실패·탈락한 실험의 생성 산출물은 결과/재현 기록을 남긴 뒤 즉시 삭제한다. 확정 바이너리·저빈도 자료는 `/fast-lab-share/hnpark2/prefetchit/archives/20260924T163557Z`에 단일 rsync(20 MiB/s 제한)로 11.56 GB 백업하고 전량 SHA-256 검증했다. 9.18 GB는 NAS로 옮겨 기존 경로에 링크를 남겼다. 현재 성능 측정 기준 세트는 로컬 유지하며, NAS 자료를 다시 측정할 때는 로컬로 복원한다. [지침](../AGENTS.md). 이동 기록은 로컬 전용 `llvm_prefetchit/migration/evidence/nas_backup_20260924.json`에 보존한다.
- 디스크(2026-09-20 정리, 사용자 지시): 삭제 = DCPerf v1 빌드, DCPerf v2 탈락 패키지(adsim, cdn_bench, xsbench/gapbs/graph500/liblinear/schbench/syscall, TaoBench), TailBench moses/img-dnn/shore 입력, PostgreSQL·php/WordPress·ClickHouse 빌드, gem5 빌드, CloudSuite data-caching 이미지 → 69 GB 여유. 남긴 것 = django v2·feedsim v2(A 부류), TailBench 소스(silo/masstree), MariaDB(A-4), MicroSuite(SetAlgebra/HDSearch 미시도), SPEC2026(재설치 어려움), DaCapo 데이터·CloudSuite web-serving/web-search/data-serving 이미지(JVM/JIT 참고값).

## 4. 기록 규칙
- 결과 디렉토리 `<topic>_<yyyymmdd>/`, 요약은 README §2/§5 표와 `core_results.tsv`에만.
- 각 워크로드 한 행: speedup vs base, vs twin, MPKI before→after, 명령 수, 세팅(코어·C6·regime·활용률). A 부류는 정적 링크 몫과 prefetch 몫 분리.
- 실패도 원인(축: cold/capacity/interleaving, 리드타임, outstanding 한도, 오버헤드, 도구 범위 밖)과 함께 남긴다.
