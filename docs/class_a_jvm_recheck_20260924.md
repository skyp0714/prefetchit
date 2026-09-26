# Solr·Cassandra·Trino·DaCapo 재탐색 — 2026-09-24

사용자 요청에 따라 과거 수치로 제외하지 않고 이번 작업에서 직접 재측정했다.
신규 후보 5종은 [별도 보고서](class_a_jvm_candidates_20260924.md)에 정리했다.
이 보고서는 기존 후보의 새로운 qualification 기록이며 prefetch 이득 보고서가 아니다.

## 측정 범위

서버 CPU 32–35, 고정 2 GHz, C6/C6P off. 실제 JVM TID affinity와 PMU scheduling을
확인한다. 별도 클라이언트가 있는 경우 CPU 16–19를 사용한다. 모든 workload를 순차
측정하며, 공유 호스트에서 실행 중인 다른 사용자의 QEMU는 변경하지 않는다.
L2 code MPKI는 user-only L2_RQSTS.CODE_RD_MISS / instructions × 1000이고,
top-down 비율은 raw slot 비율이다. 간접 branch counter는 jump도 포함한다.

- **DaCapo 23.11-MR2:** JDK17, 4 GiB heap, 4 worker/client threads. 공식 JAR의 모든
  entry를 byte-identical하게 보존한 임시 launcher에 측정 callback class 하나를 추가한다.
  공식 `Harness`와 manifest의 module 설정을 유지한다. 최소 5회·60초 warmup 뒤
  완료되고 validation된 반복을 최소 3회·30초 측정한다. 반복 직전의 인위적 System.gc만
  생략하고 정상 GC는 유지한다. 내부 클라이언트·반복별 lifecycle을 포함하는 전체 JVM
  수치이므로 지속 서비스의 서버 전용 수치나 공식 DaCapo score와 구분한다.
- **Solr 9.1.1:** 기존 CloudSuite 이미지에서 새 core를 구성한다. 기존 DaCapo Wikipedia
  원문의 첫 50k 문서를 사용하고 검색·범위 filter·facet·highlight를 섞는다. query cache를
  유지하며 응답의 numFound와 정렬된 ID 목록을 순차 실행 oracle와 검증한다.
  CloudSuite 공식 14 GiB corpus 결과로 부르지 않는다.
- **Cassandra 4.1.0 / JDK11.0.17 CloudSuite 이미지:** 별도 YCSB client, 1M records × (10 fields × 100 B),
  A(50% read/50% update)와 B(95%/5%), 16 client threads. 정상 commitlog 설정을
  유지한다. 단일 노드 CPU qualification으로 RF=1을 명시한다. 원래 CloudSuite script의
  단일 서버 + RF=3 설정을 그대로 재사용하지 않는다. YCSB dataintegrity 검사를 켠다.
- **Trino 483 + JDK25:** 공식 core 배포본에 같은 버전의 memory/tpch plugin을 넣는다.
  기존 419 tarball은 Maven에서 제거된 GitHub release로 redirect되어 받을 수 없었다.
  SF1 tables를 memory connector에 먼저 적재한 실행과 on-demand TPCH connector를
  비교하여 generator CPU 비용을 구분한다. aggregate/join/scan 혼합이며 결과를 대조한다.
  단일 coordinator/worker의 CPU 실험이지 production storage throughput/TPC-H 점수가 아니다.

활용률 ≥15%, 완료된 올바른 작업, 달성 가능한 처리율과 latency 조건을 확인한다.
MPKI ≥5를 우선하며 2–5는 차가운 실제 간접 target과의 충분한 연관이 있어야 승격한다.
warmup만으로 JIT steady state나 A-3 적합성을 확정하지 않는다.

## 재현 과정에서 제외한 실행

- Trino 첫 c4 구간은 perf attach 중 종료된 TID에 event-open을 시도해 ESRCH로 실패했다.
  카운터가 시작되지 않은 구간은 제외했다. 실패 raw/stderr를 남기고, 살아 있는 JVM의
  이 attach race에 한해 최대 5회 재시도하도록 수집기를 보완했다. 첫 c1은 정상 완료됐으며
  별도 JVM에서 세 구간을 다시 측정해 구분해서 보존한다.

- 공식 launcher를 복구한 `verified` 8종은 모두 validation/exit 0을 통과했지만,
  선택적 요청별 latency CSV export가 반복 사이 PMU와 I/O에 포함되어 진단용으로만 남겼다.
  최종 `clean` 그룹에서는 해당 export를 끄고 정상 콘솔 latency 요약만 보존한다.
- Solr 첫 준비는 이미지의 SOLR_HOME과 core home 차이로 CREATE core에 실패했다.
  성능 측정 없이 컨테이너를 제거한 뒤 명시적 server/solr 경로로 수정했다.

- 직접 `TestHarness`를 호출한 첫 시도는 perf 종료 signal이 child sleep까지 전달되지
  않아 정상적으로 닫힌 측정으로 채택하지 않았다.
- 같은 직접 호출은 공식 JAR의 Add-Opens/Add-Exports를 적용하지 않았다. WildFly의
  `java.util.EnumMap.keyType` reflection이 차단되어 app 배포에 실패하고 HTTP404 loop가
  생겼다. 즉시 중단했으며 높은 miss의 근거로 사용하지 않는다.
- 직접 호출한 Spring은 validation이 PASSED했지만 공식 launcher의 System.exit가 빠져
  teardown이 종료되지 않았다. 해당 수치는 diagnostics로 보존하고 공식 launcher 결과로
  대체한다. 초기 Tomcat 3.08/Spring 2.14 MPKI도 최종 표에 재사용하지 않는다.
- callback classpath를 통한 주입은 class resolution에 실패했다. 이후 공식 JAR copy에
  callback class만 추가한 작은 H2 smoke가 validation 및 exit 0으로 완료됐다.
  smoke는 성능 수치가 아니다.

모든 원래 입력·JAR은 유지했다. 실패한 실행의 scratch는 제거했고, 완료된 실행의 요청별
CSV는 파일 hash와 반복별 latency 요약을 남긴 뒤 정리한다. 명령, 설정, source 및 측정
gate 기록은 `llvm_prefetchit/results/class_a_jvm_recheck_20260924`에 보관한다.

## 서비스 재측정 해석

- **Solr:** 300/600 req/s는 MPKI 0.902/0.900, FE 13.9/13.0%였다. 세 부하의
  85,000개 응답에서 numFound/ID 검증 오류와 누락이 없었다. 100 req/s는 활용률 8.7%라
  제외하며, compiler 스레드 CPU 비중도 약 25%였다. 600 req/s에서는 약 0.4%로 낮아졌다.
  현재 검색 혼합을 높은 code-miss 후보로 승격하지 않는다.
- **별도 Cassandra:** 1M건 적재와 1.71M건 READ/UPDATE가 모두 성공했고 모든 읽기 값의
  YCSB VERIFY가 통과했다. perf 구간 내부의 두 10초 상태 구간도 목표 처리율 ±1% 이내였다.
  활용률 기준을 넘은 A/B 설정은 MPKI 0.919–1.772, FE 21–24%, BE 42–47%였다.
  전체 YCSB throughput에는 종료 비용 등이 포함되므로 3k/6k 목표가 약 2.91k/5.82k로
  표시되는 값과 steady-state 처리율을 구분한다. 높은 MPKI/낮은 backend 조건은 미확인이다.
- **Trino:** memory c1 두 JVM 실행은 MPKI 0.428/0.421, c4는 0.375, TPCH generator는
  0.169였다. 모든 완료 SQL 결과가 기준과 일치했다. memory c4는 활용률 99%의 포화
  확인점이며 p99 약 5.5초여서 지연 여유가 있는 운영점이라고 부르지 않는다. c1은 약 90%,
  p99 약 1.6초다. p99는 제한된 혼합 요청 표본의 기술 통계이며 production SLO 검증이 아니다.
  generator를 제외해도 낮은 miss이며, 약 6.6 indirect branches/ki라는 빈도만으로 실제
  차가운 간접 call target이 많다고 판단할 수 없다. 해당 counter에는 jump도 포함된다.

여기서 낮은 MPKI는 우선순위를 낮출 근거이며 prefetch 이득이 정확히 0%라는 측정은 아니다.
새 삽입 실험의 speedup이나 1–5% 향상을 주장하지 않는다.

<!-- MEASURED_TABLE -->
## 새 실측 결과

모든 수치는 prefetch 미삽입 qualification이다. 한 번의 30초 이상 측정으로, 반복 간
신뢰구간이나 JVM 간접 target의 miss 기여를 확정한 결과가 아니다. FE/BE/Retiring/Bad-spec은
raw top-down slot 비율이며 Fetch latency는 FE의 하위 항목이다. 표의 낮은 활용률 행은
설정 탐색 기록으로만 남긴다.

| 측정 | L2 code MPKI | 활용률 % | FE % | BE % | Retiring % | Bad spec % | Fetch latency % |
|---|---:|---:|---:|---:|---:|---:|---:|
| clean/tomcat | 2.914 | 16.1 | 34.2 | 29.3 | 22.7 | 14.4 | 24.7 |
| clean/spring | 2.056 | 70.3 | 33.3 | 16.3 | 36.6 | 16.0 | 18.2 |
| clean/tradesoap | 0.949 | 31.5 | 31.0 | 20.9 | 37.6 | 11.0 | 18.8 |
| clean/tradebeans | 0.080 | 30.1 | 25.3 | 20.9 | 47.3 | 7.2 | 11.1 |
| clean/cassandra | 3.284 | 46.1 | 34.9 | 37.5 | 18.1 | 11.8 | 26.0 |
| clean/kafka | 0.779 | 19.7 | 17.5 | 48.9 | 25.8 | 8.8 | 10.3 |
| clean/lusearch | 0.053 | 97.8 | 12.9 | 13.7 | 50.5 | 23.3 | 5.8 |
| clean/h2 | 0.248 | 74.8 | 15.9 | 39.2 | 33.1 | 12.1 | 8.3 |
| solr/Solr_100 | 1.280 | 8.7 | 18.4 | 21.7 | 40.8 | 19.5 | 10.1 |
| solr/Solr_300 | 0.902 | 20.0 | 13.9 | 22.6 | 43.8 | 20.3 | 7.4 |
| solr/Solr_600 | 0.900 | 37.0 | 13.0 | 22.2 | 44.9 | 20.0 | 6.6 |
| cassandra/Cassandra_A_1000 | 1.684 | 9.3 | 27.1 | 42.1 | 22.5 | 9.8 | 19.3 |
| cassandra/Cassandra_A_3000 | 1.772 | 18.8 | 23.9 | 47.3 | 20.9 | 8.0 | 17.6 |
| cassandra/Cassandra_A_6000 | 1.593 | 31.1 | 24.2 | 41.5 | 24.9 | 10.3 | 17.1 |
| cassandra/Cassandra_B_3000 | 0.972 | 19.0 | 22.0 | 44.4 | 25.4 | 9.6 | 15.1 |
| cassandra/Cassandra_B_6000 | 0.919 | 26.5 | 21.4 | 44.9 | 26.1 | 9.4 | 14.7 |
| trino/memory_default_c1 | 0.428 | 90.1 | 11.1 | 11.4 | 60.3 | 17.4 | 6.5 |
| trino_retry/memory_default_c1 | 0.421 | 89.9 | 11.1 | 11.7 | 60.7 | 16.9 | 6.3 |
| trino_retry/memory_default_c4 | 0.375 | 99.0 | 10.7 | 13.7 | 60.2 | 15.2 | 6.3 |
| trino_retry/tpch_sf1_c1 | 0.169 | 93.3 | 16.1 | 20.6 | 54.8 | 9.2 | 5.4 |

GitHub에는 [결과·추적·제외 사유 요약](../llvm_prefetchit/migration/evidence/class_a_jvm_recheck_20260924/)을 공개한다. 전체 raw counter·TID CPU snapshot·정확성 기록의 압축 묶음은 같은 경로의 로컬 전용 archive에 보존한다.

<!-- END_MEASURED_TABLE -->

## DaCapo 해석과 별도 PEBS/LBR 추적

CSV 없는 8종은 모두 validation/exit 0 및 100% PMU scheduling을 통과했다. L2 code MPKI
최대는 Cassandra 3.284, 다음은 Tomcat 2.914, Spring 2.056이다. 세 항목의 compiler 스레드
CPU 비중은 각각 약 1.0%, 8.4%, 4.4%였다. TID CPU snapshot의 근사치이며 종료된 TID와
GC pause의 완전한 분석을 대신하지 않는다. Cassandra의 source package에 해당하는 nmethod가
전체 trace 표본의 54.35%, Datastax driver가 17.87%여서 내부 client의 영향도 분명하다.
별도 서버 YCSB의 최대 1.772 MPKI와 동일한 운영점을 측정한 결과로 취급하지 않는다.

Cassandra·Spring을 새 JVM에서 다시 warmup하고, gate 해제 5초 후부터 18초간
`FRONTEND_RETIRED.L2_MISS` PEBS(period 2003)와 32-entry LBR을 수집했다. 두 실행 모두
검증·정상 종료했다. 추적 실행으로 speedup을 계산하지 않았다. 전후 `Compiler.codelist`의
compile ID/level/method/code interval이 일치하는 nmethod만 이름을 붙였다. level 0 native
wrapper는 별도 집계했으며, inline frame을 복원한 자료는 아니다. 원본 ELF가 사라진 Netty
JNI 등과 미해석 JIT/stub는 분모에 남겼다. perf/decode log에는 loss 경고가 없었다.

| 진단 workload | 전체 표본 | 안정적으로 매핑한 JIT % | 미해석 % | 간접 CALL 같은 line % | 간접 JMP 같은 line % | 둘의 합집합 같은 line % | 합집합 target +256 B % | 직접 CALL 같은 line % | 직접 CALL target +256 B % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cassandra | 8,566 | 93.24 | 3.04 | 0.55 | 6.15 | 6.70 | 9.28 | 13.80 | 24.52 |
| Spring | 23,015 | 86.47 | 4.38 | 1.33 | 8.20 | 9.53 | 12.74 | 25.59 | 39.42 |

이는 최근 32개 분기와 sampled miss instruction 사이의 **공간적 연관**이다. 같은 표본에
여러 분기 종류가 대응할 수 있으며, call stack·인과적 miss 비중·stall cycle 비중·speedup
상한이 아니다. JVM vtable/itable stub는 메서드 entry로 간접 JMP를 할 수 있으므로
`IND_CALL`만 보고 Java virtual 호출을 배제하면 안 된다.
[OpenJDK x86 vtable/itable stub](https://github.com/openjdk/jdk17u/blob/master/src/hotspot/cpu/x86/vtableStubs_x86_64.cpp),
[Compiler.codelist 설명](https://docs.oracle.com/en/java/javase/17/docs/specs/man/jcmd.html),
[출력 주소 범위 구현](https://github.com/openjdk/jdk17u/blob/master/src/hotspot/share/code/codeCache.cpp).

구체적으로 확인한 후보는 다음과 같다.

- **Spring A-3 보류 후보:** `WebRequestHandlerInterceptorAdapter.preHandle/postHandle/afterCompletion`,
  `RequestContextFilter`·`CharacterEncodingFilter.doFilterInternal`의 간접 JMP target 근처에도
  miss가 있다. 개별 target의 +256 B 연관은 전체 표본의 약 0.09–0.14%로 분산돼 있다.
  실제 번들은 PetClinic 2.7.3 / Spring 5.3.22 / Tomcat 9.0.65-PATCHED이며, DaCapo 원본에
  포함된 benchmark 패치를 사용한다. 원본 standalone 서비스라고 부르지 않는다.
  `HandlerExecutionChain`의 같은-thread interceptor list에서 다음 receiver를 확보하는
  가설은 타당하지만 preHandle 중단·역순 postHandle·예외 처리 순서를 유지해야 한다.
  [실제 Spring 버전에 맞춘 소스](https://github.com/spring-projects/spring-framework/blob/v5.3.22/spring-webmvc/src/main/java/org/springframework/web/servlet/HandlerExecutionChain.java).
- **Cassandra A-3 보류 후보:** `DuplicateRowChecker`·`DataLimits`·`Transformation`의 iterator
  경로와 Datastax `SegmentBuilder.operationComplete`에서 간접 JMP target 연관이 보인다.
  순서가 정해진 다음 transform/completion receiver를 활용할 여지가 있다. 그러나 queue의
  producer/consumer core와 driver/server 구분을 먼저 고정해야 한다.
- **A-2/G 우선 검토:** Spring은 FE 33.3%/BE 16.3%이고 직접 CALL 연관이 더 넓다.
  filter·MVC request matching·Thymeleaf 경로의 graph 기반 접근을 우선 검토할 근거가 있다.
  Cassandra도 `ModificationStatement.addUpdates`, `StorageProxy.fetchRows/performWrite`,
  `ReadCommand.executeLocally` 등으로 miss가 분산돼 있다. 단일 다음 handler hint만으로
  충분하다는 증거는 없다. A-2와 A-3의 최종 분류 및 이득은 새 삽입 실험 전에는 미확정이다.

네 묶음에서 이번에 **MPKI ≥5인 정상 설정을 새로 찾지는 못했다**. Spring/PetClinic은
낮은 backend와 실제 framework 코드 miss 때문에 소규모 G/F 검증의 후보로 남긴다.
이 결과만으로 1% 혹은 3–5% 향상을 약속하거나 aggressive predictor를 먼저 켤 이유는 없다.

## A-3/A-2 삽입 후보 — 소스 관찰이며 miss 기여는 미확정

- Solr `SearchHandler`는 `List<SearchComponent>`를 순회하며 prepare/process를 호출한다.
  다음 component의 실제 process target을 같은 consumer에서 일찍 확보할 가능성이 있다.
  같은 component들이 매 요청 반복되므로 entry 자체는 이미 hot할 수 있어 하위 호출
  graph와 실제 miss 위치를 함께 봐야 한다.
- Cassandra `Dispatcher`는 executor에 request 처리를 넘긴 뒤 request.execute를 호출한다.
  producer에서 target을 알아도 실행 core가 달라질 수 있다. 준비된 CQL 중심 부하는
  opcode/entry 종류가 적으므로 공통 lambda entry를 가져오는 것만으로는 부족할 수 있다.
- Trino `Driver`는 active operator list에서 current/next를 얻은 뒤 current.getOutput과
  next.addInput을 연결한다. 이전 operator 처리 시간을 lead time으로 쓰는 F와 operator
  graph 기반 G를 비교할 구조적 근거가 있다. JIT inlining/직접 호출 전환 여부는 별도 확인한다.
- Tomcat `ApplicationFilterChain`의 filter 배열과 최종 Servlet은 후보지만, filter가
  중간에 요청을 종료할 수 있으므로 무조건 후속 handler가 실행된다고 가정하지 않는다.

원문 URL과 SHA-256은 working root의 `source_manifest.json`에 기록했다.

## 일차 자료

- [DaCapo Chopin](https://www.dacapobench.org/)
- [Solr SearchHandler 9.1.1](https://github.com/apache/solr/blob/releases/solr/9.1.1/solr/core/src/java/org/apache/solr/handler/component/SearchHandler.java)
- [Cassandra Dispatcher 4.1.0](https://github.com/apache/cassandra/blob/cassandra-4.1.0/src/java/org/apache/cassandra/transport/Dispatcher.java)
- [Trino memory connector](https://trino.io/docs/current/connector/memory.html), [HTTP client protocol](https://trino.io/docs/current/client/client-protocol.html)
- [Trino Driver 483](https://github.com/trinodb/trino/blob/483/core/trino-main/src/main/java/io/trino/operator/Driver.java)
- [Tomcat ApplicationFilterChain 10.1.11](https://github.com/apache/tomcat/blob/10.1.11/java/org/apache/catalina/core/ApplicationFilterChain.java)

## 보존·정리

원본 배포 패키지 5개(1,277,052,394 B)를 먼저 NAS에 보관했고, 이후 Trino/JDK25 실행본과
두 원본 trace를 450,296,354 B archive로 추가 보관했다. 모두 단일 rsync 20 MiB/s와
순차·동일 속도 SHA-256 검증을 거친 뒤 로컬 bulk를 제거했다. TAR의 JDK hard link도
실제 member bytes/hash로 검증했다. 패키지 alias와 복원 명령·파일 hash를 보존했다.

실패/완료한 컨테이너의 파생 색인·데이터 및 모든 DaCapo scratch/요청별 CSV는 정리했다.
원래 Wikipedia·DaCapo 입력과 공유 Docker 이미지/JDK17은 유지했다. 결과·설정·명령·소스
기록·JIT 지도·검증·실패 사유는 compact evidence에 압축 보관한다. 재실행 시 NAS archive를
제한된 rsync로 로컬에 stage한 후 timing하며 NAS를 통해 benchmark를 실행하지 않는다.
