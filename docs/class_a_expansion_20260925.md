# Class A 확장·JVM 100블록 재검증 — 진행 중

2026-09-25 사용자 요청: 양의 평균이나 넓은 CI를 보인 JVM 후보를 반복 확인하고, A-2의 L3 instruction miss / sTLB miss 타깃 선별과 실제 trace 분석을 검토하며, CloudSuite JVM과 HP 워크로드를 실행한다. **HP의 이전 실행 보류 요청은 이번 요청으로 해제됐다.** 이 문서는 진행 상태이며 성공 결과가 아니다.

## 고정한 재검증 설계

Pinot F16, Spring GF, Flink G를 각각 **100개의 독립 JVM 블록**으로 확인한다. 각 블록에는 baseline·선택 정책·그 정책과 일치하는 NOP가 들어가므로 총 900실행이다. 6개 순열을 균형 배치하고 순서를 고정 seed로 섞는다. 이전 5블록은 새 통계에 포함하지 않는다. 기존 JVM 바이너리 SHA-256과 운영 설정을 유지한다.

주요 지표는 Pinot CPU/완료 query, Spring operation 실행시간, Flink TaskManager CPU/nominal event다. Flink 분모는 실제 source 진행률로 검증하지만 정밀한 완료 event 계측은 아니며 datagen도 CPU에 포함된다. 유효 실행의 JIT/GC spike를 사후 삭제하지 않는다. 유효성 실패는 기록하고 원인을 조사한다. 효과가 좋아 보일 때 중단하지 않으며, 최종 paired log-ratio CI와 6개 비교의 Holm 보정을 함께 보고한다. baseline과 NOP 양쪽의 양의 효과가 확인되어야 prefetch 이득으로 채택한다.

- 실행기: `llvm_prefetchit/results/class_a_expansion_20260925/confirm100.py`
- 계획·실행·중간 통계: `/storage/prefetchit/class_a_expansion_20260925/confirm100/{plan,runs,summary}.json`
- 첫 블록부터 실제 실행 시작. 100블록 완료 전 통계는 기술적 중간값이며 확정 판단에 사용하지 않는다.

## L3 / sTLB 타깃 선별

[Intel Granite Rapids PMU 정의](https://raw.githubusercontent.com/intel/perfmon/main/GNR/events/graniterapids_core.json)를 현재 Xeon 6787P에 맞춰 확인했다. 호스트 perf의 내장 이벤트 이름이 부족해 raw encoding을 사용한다. 추출한 정의와 출처는 `intel_gnr_target_events.json`에 보존한다.

| 목적 | 이벤트 / 접근 | 해석 한계 |
|---|---|---|
| instruction sTLB miss 타깃 | `FRONTEND_RETIRED.STLB_MISS`: event C6, umask 03, frontend 15, PEBS | retired instruction 위치의 증거; 모든 speculative fetch miss를 세는 것은 아님 |
| L1 iTLB miss 이후 sTLB hit | `ITLB_MISSES.STLB_HIT`: 11/20 | sTLB miss와 별도 집계 |
| instruction page walk | `ITLB_MISSES.WALK_COMPLETED`: 11/0e | 전체 수량 진단; precise 타깃 IP가 아님 |
| L3 code miss 수량 | `OCR.DEMAND_CODE_RD.L3_MISS`: 2A/01, offcore_rsp 3FBFC00004 | demand fetch와 L1I prefetch 포함; precise IP 없음. overflow IP를 miss target으로 쓰지 않음 |
| backend stall과 겹치지 않은 긴 FE 지연 | `FRONTEND_RETIRED.LATENCY_GE_128`: C6/03, frontend 608006, PEBS | 긴 FE 지연의 위치이며 L3 miss 전용 표식은 아님 |

따라서 sTLB-only 타깃 선별은 직접 실험할 수 있다. L3-only는 현재 PMU만으로 정확한 타깃을 단정하기 어려워 aggregate miss와 FE 지연 및 실행 경로를 결합한 후보 선별로 시작한다. 데이터 prefetch가 주소 변환에 도움을 줄 가능성과 실제 instruction-side walk 감소는 별도로 검증한다.

[Intel PT 문서](https://raw.githubusercontent.com/torvalds/linux/master/tools/perf/Documentation/perf-intel-pt.txt)를 기준으로 PT를 준비한다. PT는 실행 경로이며 miss trace 자체가 아니다. 짧은 정상 steady-state 구간에서 시작해 AUX loss·decode error·코드 mapping을 확인한 뒤 확대한다. PEBS로 target을 정하고 PT로 LBR 범위 밖의 선행 경로·반복성·lead를 분석하며, 별도 입력/요청 mix에서 검증한다. 프로파일 수집 실행과 성능 비교 실행을 분리한다.

## 새 workload 및 저장소

- HP: [기존 11구성 목록](hierarchical_prefetch_candidates_20260925.md)을 실행 후보로 전환한다. Beego/Gin/Echo와 Caddy부터 하네스·운영 설정을 확인하고, GORM/PostgreSQL, DGraph, TiDB/sysbench·TPC-C, MySQL/SiBench·YCSB로 이어간다. 앱을 시작한 것과 정상 부하 qualification 및 prefetch 이득 확인을 구분한다.
- Go Web Framework Bench는 2024-08-15 revision `b07cebd150aa2458ba2df1726a284ea4fd36fad4`, ORM Bench는 2024-10-15 revision `66291c9549c66ccca00003b3f735ca2f45e9ca2a`를 먼저 조사했다. **논문이 쓴 정확한 revision이라고 주장하지 않는다.** Go 웹 하네스의 zero-sleep handler는 `runtime.Gosched()`를 포함하므로 원본 결과를 실제 business logic 대표값으로 단정하지 않는다.
- CloudSuite JVM: [공식 CloudSuite 4](https://github.com/parsa-epfl/cloudsuite)의 Solr·Cassandra와 Spark/Hadoop 계열을 확인한다. 기존 50k Wikipedia Solr 결과는 공식 14GB index 결과가 아니며 새 스토리지를 이용한 정상 corpus 실험을 구분한다. Cassandra 4.1의 JDK11 요구와 현재 G/F 구현 JDK17/21의 호환성을 먼저 해결해야 한다.
- `/storage` 초기 여유 916GiB: 패키지·빌드·dataset·현재 실험 작업 공간. `/trace` 초기 여유 835GiB: 원본 PT/PEBS와 일시 decode 작업. root filesystem 여유 약13GiB는 더 소모하지 않도록 한다.
- 실패/대체된 생성 bulk는 compact evidence·설정·hash·제외 사유를 남긴 뒤 즉시 삭제한다. 추가 디스크가 생겨도 기존 retention 규칙을 유지한다. NAS 이동 시 한 번에 하나의 rate-limited rsync와 순차 SHA 검증을 유지한다.

## 실제 진단 및 준비 결과 (진행 중)

- FleetBench 동일 Arena 기준 10초 진단: L2 code MPKI **16.6828**, L3 code MPKI **0.0000257**, instruction page-walk MPKI **0.07494**, L1 iTLB miss/sTLB hit MPKI **0.85542**. L3-only는 이 workload에서 대상으로 삼을 miss가 거의 없다. 다른 workload에 대한 일반화는 아직 하지 않는다.
- 실제 Intel PT + PEBS를 함께 수집하고 AUX loss·decode error가 없는 세 캡처를 확인했다. 순서 있는 call 약 761만–793만개를 분석했다. L2 PEBS 7,215개, FE≥128 PEBS 2,395개, sTLB PEBS 41개다. **sTLB 표본은 최종 선택에 부족하여 별도의 긴 PEBS 수집을 준비했다.** PT 시각 차이는 timing estimate이며 정확한 call별 cycle latency가 아니다.
- 첫 branch histogram의 parser 오류를 발견해 잘못된 요약을 폐기하고 거부 사유와 삭제 기록을 남겼다. 원본 trace로 다시 분석한 `path_analysis.json`만 사용한다. 이후 실제 trace 기반 삽입의 첫 성능 비교까지 완료했으며 아래에 별도로 기록한다.
- JDK11.0.28+6에 G2/F2를 포팅했다. 15개 의미 보존 검증과 live code의 prefetch/NOP 위치·길이 검증을 통과했다. JDK11의 기본 disassembly 출력만으로는 인코딩을 확인할 수 없어 프로세스 코드 바이트를 직접 읽어 검증했다. Cassandra 적용 결과는 아직 없다. 빌드 생성물 약940MB는 제거했고 source/package/patch/runtime은 보존했다.
- CloudSuite 공식 Solr 인덱스는 압축11,988,330,616 bytes, 압축 해제13,987,582,074 bytes이며 전체 압축 해제와 SHA-256 기록을 완료했다. JDK17로 실행하는 별도 4코어·14GB heap 하네스를 준비했다. 공식 term/cardinality 분포를 쓰지만 Faban 또는 분산 클러스터 실적이라고 주장하지 않는다.
- JVM 재검증의 첫 Pinot 블록은 완료됐다. prefetch 9.4622 / baseline 8.8778 / NOP 8.4533 CPU ms/query로, 이 블록에서는 악화됐다. **n=1 결과로 이득 유무를 판정하지 않으며**, 나머지 고정 반복을 계속한다.

## FleetBench 타깃 필터 비교 완료

학습 seed0의 baseline에서 이벤트별 PEBS 10초를 수집하고, 해당 이벤트 표본의 80%를 차지하는 **함수**에 들어가는 기존 정적 힌트만 남겼다. seed1에서 새 5쌍×100 iterations를 측정했다. 제거한 힌트는 동일 길이 단일 NOP로 바꾸므로 코드 배치와 명령어 수를 유지한다. 정확한 miss 페이지 선별이나 PT 기반 새 삽입 위치의 실험은 아니다.

| 정책 | 남긴 힌트 | baseline 대비 CPU speedup, paired 95% CI | L2 code MPKI |
|---|---:|---:|---:|
| 기존 전체 정적 schema graph | 19,718 | **+3.51% [3.44, 3.58]** | 12.879 |
| L2 miss 함수 필터 | 7,991 | +2.15% [2.05, 2.25] | 14.436 |
| 긴 FE stall(≥128) 함수 필터 | 4,033 | +0.79% [0.69, 0.90] | 15.610 |
| sTLB miss 함수 필터 | 608 | −0.64% [−0.67, −0.60] | 16.816 |
| 모든 힌트 NOP | 0 | −0.80% [−0.92, −0.69] | 17.087 |
| 원래 baseline | — | 기준 | 16.588 |

이 조건에서는 기존 정적 정책을 유지한다. sTLB 필터는 NOP 대비 +0.17% [0.09, 0.25]이지만 원래 baseline보다 느려 채택하지 않는다. 나머지 필터도 기존 전체 정책보다 나쁘다. CI는 탐색 비교용이며 독립 workload 일반화 증거가 아니다. NOP 삽입 비용을 남겼으므로, 필터에 맞춘 재컴파일이나 실제 miss 페이지를 겨냥한 정책의 상한으로 해석하지 않는다.

원본 측정: `/storage/prefetchit/class_a_expansion_20260925/fleet_filter_eval/{runs.csv,paired_summary.json}`. 함수별 학습 표본: sTLB 2,013 / FE≥128 9,691 / L2 29,621개, lost sample 0. 첫 symbol-only decode 출력 문제는 `ip,sym` 출력으로 수정해 원본 PEBS를 다시 해석했다.

## HP 웹 계열 qualification 완료

| workload | 선택 조건 | L2 code MPKI | 활용률 |
|---|---|---:|---:|
| Beego | 원본 zero-sleep hello, c128 | 0.0840 | 91.0% |
| Gin | 원본 zero-sleep hello, c128 | 0.0752 | 89.6% |
| Echo | 원본 zero-sleep hello, c128 | 0.0735 | 89.6% |
| Caddy 2.9.1 | TLS1.3 HTTP/2 static1–64KiB mix, c1/m1 | 0.2797 | 34.4% |

3프레임워크는 c1/8/32/128, Caddy는 (connections,streams)=(1,1)/(8,4)/(32,8)/(128,16)을 확인했다. Go3종은 모든 응답 본문을 검사했고, Caddy는 모든 결과 status와 시작/종료 본문 oracle를 검사했다. h2load의 warm-up 경계에서 header status와 completion 집계가 다르게 이루어지는 점을 [v1.59 원본](https://raw.githubusercontent.com/nghttp2/nghttp2/v1.59.0/src/h2load.cc)으로 확인했다. 원래 엄격한 동일-count 판정과 경계 차이를 기록한 재검증은 `caddy_qualification/validation_audit.json`에 함께 보존했다. 이는 원 논문의 정확한 설정 재현이나 prefetch 이득 결과가 아니다.

활용률≥15%인 정상점 중 MPKI 최대를 골라도 모두0.3미만이므로 이 조건은 우선 제외한다. source/package/patch/settings/results는 보존하고 사용이 끝난 Go-web·Caddy 바이너리83,659,667 bytes를 삭제했다.

## CloudSuite 공식 Solr qualification 완료

Solr9.1.1, 공식14GB index의165,255문서, 4코어·14GB heap에서 원본 term/cardinality 분포의4096쿼리를 사용했다. 모든 부하 응답의 numFound와 순서 있는 URL 결과를 baseline oracle와 비교했다. 독립 JVM 비교에는 같은 linked JDK17 image/libjvm을 사용하며 기존100블록 런타임은 변경하지 않았다.

| 부하(QPS) | 활용률 | L2 code MPKI | 선택 |
|---:|---:|---:|---|
| 50 | 2.65% | 1.479 | 활용률 미달 |
| 150 | 7.06% | 1.364 | 활용률 미달 |
| 300 | 13.33% | 1.359 | 활용률 미달 |
| 600 | 24.99% | 1.444 | 선택 |

600QPS의 clean primary CPU는1.6662ms/query, p99는4.18ms다. PMU는 별도 구간에서 수집했다. 현재는 정상 baseline qualification이며 G/F 이득 결과가 아니다. 7개 fresh JVM의 base/G/F/GF 및 각 NOP 비교를 준비했다.

## GORM/PostgreSQL qualification 완료

원본 GORM의 Insert·InsertMulti·Update·Read·ReadSlice를 각 표준 Go benchmark10초로 실행하고 전체5연산을3회 반복했다. 순차 앱은1코어, durable PostgreSQL16은 별도4코어다. 앱 활용률34.83–36.74%, L2 code MPKI0.0635–0.0655로 낮아 이 설정은 제외한다. 이는 PostgreSQL 자체의 MPKI가 아니다. fsync/synchronous_commit/full_page_writes=on을 확인했고5연산 결과와 최종 모든 행을 검증했다. 표준 testing.B calibration이 ReadSlice의100행 초기화를 반복하므로 최종 행 수는400 등100의 배수다.

원본 소스·정확한 패치·입력 DB·결과·해시를 남기고 사용이 끝난 ORM 바이너리2개와 웹/ORM의 생성된 작업 소스 복사본100,732,365bytes를 삭제했다.

JVM100 첫 round(3개 후보 각1블록)는 모두 유효했지만 baseline과 NOP 양쪽을 이긴 후보는 없다. 현재 표본은 추론에 부족하며100블록 프로토콜을 유지한다.

## 실제 PT 기반 삽입의 첫 비교 완료

FE≥128 PEBS와 순서 있는 Intel PT call을 결합해 다음 함수의 실제 hot cache line을 선택했다. 한 학습 캡처에서 조건부 발생 비율≥0.8, 동시 출현≥20, 추정 lead 100–10,000ns인 direct-call 위치만 사용했다. 각 target 함수의 상위4개 hot line까지 삽입하며, call depth4/16/64를 비교했다. trace 시간은 정확한 CPU cycle 측정이 아니며, 별도 seed 결과가 일반적인 경로 예측 정확도를 보장하지 않는다.

| PT 깊이 | 삽입 위치 / 힌트 | baseline 대비 CPU speedup, 95% CI | 해당 NOP 대비 |
|---:|---:|---:|---:|
| 4 | 15 / 46 | +0.258% [−0.018, 0.535] | +0.155% [−0.007, 0.318] |
| 16 | 12 / 24 | +0.166% [0.060, 0.272] | −0.008% [−0.034, 0.019] |
| 64 | 4 / 4 | +0.094% [−0.191, 0.379] | −0.108% [−0.325, 0.110] |

각각 새 seed1의3쌍 탐색 결과다. baseline/NOP 양쪽 대비 평균≥1%라는 후속 검증 기준에 모두 미달했다. 기존 정적 schema graph의 +3.51%를 개선한 결과가 아니며, trace 기반 접근 전체의 상한이라고도 해석하지 않는다. 정확한 삽입 계획·원본 trace·패치 도구·결과·해시를 보존하고 탈락한6개 바이너리304,609,456bytes를 삭제했다. 결과 위치는 `/storage/prefetchit/class_a_expansion_20260925/fleet_pt_eval/`다.

## Dgraph qualification 및 정적 삽입 준비

Dgraph24.0.5, 공식 movie RDF 1,041,684facts, detail/actor/genre-recommendation 3종 query mix, 4코어 Alpha와 분리된 Zero에서 모든 응답을 oracle와 비교했다. 첫 실행은 실제 Alpha 대신 launcher PID를 측정해 **4개 점 전부 무효**로 처리했다. 잘못된 MPKI를 활용률 미달 또는 낮은 miss의 근거로 사용하지 않는다. 원본 결과와 제외 이유를 보존하고 생성된 DB/index679,139,906bytes를 삭제한 뒤 실제 Alpha 프로세스 집합을 측정해 다시 실행했다.

| 부하(QPS) | 활용률 | L2 code MPKI | 선택 |
|---:|---:|---:|---|
| 50 | 3.78% | 2.505 | 활용률 미달 |
| 150 | 10.23% | 2.691 | 활용률 미달 |
| 300 | 19.93% | 2.671 | 선택 |
| 600 | 38.70% | 2.485 | 유효 |

선택점 p99는10.19ms이며 오류·drop 없이 부하 목표를 달성했다. 논문의 정확한 revision/설정 재현이나 prefetch 이득 결과는 아니다. 정상 결과는 `hp/dgraph_qualification_v2/`에 보존한다.

기존 함수 내부 NOP를 같은 길이의 RIP-relative prefetch로 교체하는 두 정적 direct-call lookahead 변형을 준비했다. 최소128byte/512byte lead 조건에서 각각537/426개 위치가 생겼고, 패치를 되돌린 SHA가 원본과 일치한다. 코드 주소를 유지하며 원본이 정확한 NOP 대조군이다. 정적 byte 거리는 실행 cycle lead와 다르다. version smoke만 통과했으며 실제 서비스 의미 검증과3블록 비교는 대기 중이다.

## 연결 중단 이후 실행 상태 — 2026-09-26

독립 세션의 단일 실행기 `serial_campaign.py`가 디스크의 queue/runs/active 기록으로 이어간다. 동시에 두 실험을 돌리지 않으며 각 단계의 플랫폼 복구를 검사한다. 실패 시 결과를 보존하고 원인을 확인할 때까지 다음 단계를 중단한다. 무조건 성공으로 처리하거나 실패 표본을 지우지 않는다.

Solr7개 arm 비교가 실행 중이다. 이후 JVM100의 다음 round3블록 → Cassandra qualification → Dgraph 정적 삽입 비교 → TiDB/sysbench·TPC-C → JVM100 잔여 순서다. JVM은 현재 후보별1블록만 완료했다. TiDB 하네스는 준비·구문 검증 상태이며 실제 측정은 아직 없다. MySQL SiBench의 pinned BenchBase 빌드와 YCSB JDBC 준비는 완료했지만 두 부하의 실제 측정은 남아 있다.

2026-09-26 04:48UTC 갱신: Solr7-arm 및 JVM 다음 round를 완료해 JVM은 후보별2블록이다. 후속 요청에 따라 [실제 trace 기반 AsmDB식 삽입 비교](class_a_asmdb_trace_20260926.md)를 먼저 완료했다. 전체4.49억 명령어 캡처와4,096위치 삽입까지 비교했지만 새 정책은 baseline 대비−1.94%, 같은 배치 NOP 대비+0.99~1.23%였고 기존 schema static의+3.57%를 개선하지 못했다. 탈락 생성물은 정리했으며 기존 Cassandra 이하 직렬 실험 순서로 복귀했다.

2026-09-26 정리: [스킴 결과·takeaway](class_a_asmdb_trace_20260926.md), [JVM 최신 결과](class_a_jvm_status_20260926.md). 완료된 중간 파일 611개(6.66GB)를 제거하고 검증된 압축 재현 기록 94.7MB를 남겼다. JVM 100회 확인은 후보별 2/100블록으로 미완료이며, Cassandra는 baseline 선별까지만 완료했다. Dgraph 변형 바이너리의 PID 식별 오류를 고쳐 새 디렉터리에서 비교를 재개했다.
