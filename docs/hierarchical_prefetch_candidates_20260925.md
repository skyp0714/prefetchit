# Hierarchical Prefetching 워크로드 대조 — 2026-09-25

**상태 갱신: 2026-09-25 후속 사용자 요청으로 실행 보류 해제.** [확장 실험](class_a_expansion_20260925.md)에서 진행한다. 최초 목록 작성 이후 웹4종과 GORM의 정상 부하 qualification을 완료했다. 아래는 갱신된 상태이며, 논문의 정확한 설정 재현이나 새로운 prefetch 성공 사례 수를 뜻하지 않는다.

대상은 ASPLOS 2025 **Hierarchical Prefetching: A Software-Hardware Instruction Prefetcher for Server Applications**이다. 기존 후보 문서의 MICRO 2026 **Prefetching for Hierarchical Branch Target Buffers / BTB-Ferret**와 다른 논문이다.

## 논문 구성과 로컬 실험 대조

논문 [§6.2, PDF 10쪽](https://ease-lab.github.io/ease_website/pubs/HP_ASPLOS25.pdf#page=10) 및 Figure 9의 11개 구성을 기준으로 했다. 논문은 모든 버전·입력·부하 설정을 이 절에 명시하지 않으므로, 같은 앱을 실행했더라도 논문 설정 재현으로 간주하지 않는다.

| 논문 표기 | 앱 / 부하 구성 | 현재 로컬 기록 | 후보 상태 |
|---|---|---|---|
| beego | Beego / Web Framework Bench | 원본 hello, c1/8/32/128 정상검사 완료; 선택 MPKI **0.0840** | 낮은 code miss로 해당 설정 제외 |
| gin | Gin / Web Framework Bench | 원본 hello, c1/8/32/128 정상검사 완료; 선택 MPKI **0.0752** | 낮은 code miss로 해당 설정 제외 |
| echo | Echo / Web Framework Bench | 원본 hello, c1/8/32/128 정상검사 완료; 선택 MPKI **0.0735** | 낮은 code miss로 해당 설정 제외 |
| caddy | Caddy / nghttp2의 HTTP/2 부하 | TLS HTTP/2 1–64KiB file mix 4점 완료; 선택 MPKI **0.2797** | 낮은 code miss로 해당 설정 제외 |
| dgraph | DGraph / 그래프 DB | 공식1,041,684facts, 3종 query mix; 300QPS MPKI **2.671**, 활용률19.93% | qualification 완료, 정적 삽입 비교 대기 |
| gorm | GORM / ORM Bench + PostgreSQL | 원본5연산·PG16 durable, 3회 MPKI **0.0635–0.0655**, app1코어 활용률34.8–36.7% | 낮은 code miss로 해당 설정 제외 |
| mysql | MySQL / sysbench read-write | **동일 앱·부하 계열 측정 및 prefetch 실험 있음**; 논문 설정과 동일 여부 미확인 | 기존 참조 |
| tidb | TiDB / sysbench read-write | 측정 기록 없음 | 신규, 실행 준비/측정 대기 |
| tpcc | TiDB / TPC-C | 측정 기록 없음; Silo/TailBench TPC-C와 별개 | 신규, 실행 준비/측정 대기 |
| sibench | MySQL / OLTP-Bench SiBench | 측정 기록 없음 | 신규 구성, 실행 준비/측정 대기 |
| ycsb | MySQL / YCSB | 측정 기록 없음; Cassandra/Scylla YCSB와 별개 | 신규 구성, 실행 준비/측정 대기 |

**11개 중 1개는 기존 앱·부하 계열 실험이 있고, 새 웹4종·GORM·Dgraph는 qualification 완료, 나머지4개는 미측정이다.** Dgraph 첫 launcher PID 측정은 무효로 보존하고 실제 Alpha PID 집합을 측정한 재실행만 채택했다. 웹서빙 후보는 Beego·Gin·Echo·Caddy 네 가지다. 문서·결과 요약·CSV/TSV·보존 evidence를 대조했으며, “측정 기록 없음”은 이 저장소의 확인 가능한 기록 기준이다.

MySQL 기존 근거:

- 09-21 측정(로컬 기록: `llvm_prefetchit/results/newcands_20260921/README.md`): MySQL 8.0, durable `oltp_read_write`, 16 tables × 200k rows, 16 clients, 4 cores. 선택점 L2 code MPKI 2.35.
- [09-23 A-2 후속](class_a2_campaign_20260923.md): 정상 400 TPS에서 MPKI 4.243, 활용률 16.11%; 정적 정책 및 LBR 후속 실시. 이는 별도 설정의 결과이며 논문 워크로드 전체를 검증했다는 뜻이 아니다.
- 기존 BenchBase 빌드 실패는 SiBench/MySQL 측정 완료가 아니다. PostgreSQL 단독 실험도 GORM 실행 기록을 대신하지 않는다.

## 재개 시 확인할 사항 — 계획만

다음은 논문의 실측 결과가 아니라 우리 A-2/A-3 적용을 위한 검토 항목이다.

- 웹서빙 네 가지는 HTTP 프로토콜, 라우트·middleware·응답 크기, 연결 재사용, TLS 여부를 명시한다. 기본 최소 응답과 실제 서비스에 가까운 요청 처리를 구분하고, 인위적인 코드 부풀리기를 하지 않는다.
- GORM은 Go 앱과 PostgreSQL 서버를 따로 측정한다. DGraph는 데이터와 쿼리 혼합, TiDB는 SQL/TiKV/PD 구성과 데이터 규모·트랜잭션 mix를 먼저 정한다. DB별 durable 설정과 정답·오류·지연 검증을 유지한다.
- Go 계열은 기존 LLVM/C++ 또는 JVM 삽입기가 그대로 적용된다고 가정하지 않는다. **A-2**는 정적 direct-call/단계 그래프를 조사하고, **A-3**는 handler·interface·callback의 미래 타깃이 실제로 미리 읽히는지 확인한다. 현재는 두 방식의 후보이며 효과를 확인한 분류가 아니다.
- 활용률 ≥15%인 유효 부하 중 baseline L2 code MPKI 최대점을 고른다. user/kernel MPKI와 top-down을 분리하고, miss 샘플의 indirect-call target 기여 및 lead time을 확인한 뒤 삽입 여부를 판단한다. 높은 간접 호출 빈도만으로 A-3에 적합하다고 판정하지 않는다.
- 논문의 하드웨어 지원 bundle prefetch 성능을 실기 SW `prefetcht*`의 예상 이득으로 사용하지 않는다.

## 출처

- [논문 원문](https://ease-lab.github.io/ease_website/pubs/HP_ASPLOS25.pdf): §6.2 및 참고문헌 [1, 2, 5–11, 22, 41].
- [저자 공개 gem5-hp](https://github.com/CRAFT-THU/gem5-hp): HP 구현 및 bundle 표식 설명. 이번 작업에서 빌드/실행하지 않았다.
- 논문이 지정한 [Web Framework Bench](https://github.com/smallnest/go-web-framework-benchmark), [ORM Bench](https://github.com/efectn/go-orm-benchmarks), [YCSB](https://github.com/brianfrankcooper/YCSB), [nghttp2](https://nghttp2.org/). 정확한 revision과 운영 설정은 재개 시 확인한다.
