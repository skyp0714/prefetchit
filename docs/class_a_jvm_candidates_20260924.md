# 추가 데이터센터 A-3 후보 5종 — 2026-09-24

Ceph RGW는 S3/Swift 객체 스토리지 게이트웨이다. 기존 결과는 로컬 3-OSD 구성에서
gateway CPU 경로를 측정한 것이며, 분산 스토리지 전체의 성능 결과는 아니다.
아래 5종은 기존 Solr/Cassandra/Trino/DaCapo 탐색과 중복되지 않는 **신규 후보**다.
소스에서 dispatch 경로를 확인했다는 의미이며, 높은 L2 code MPKI나 prefetch 이득이
확인되었다는 뜻은 아니다. JVM 허용 범위가 확대되어 탐색 목록에 추가한다.
추가 사용자 지시에 따라 Solr/Cassandra/Trino/DaCapo도 이번 작업에서 직접 재탐색한다.
과거 기록은 배경 자료일 뿐 새 측정을 생략하는 근거로 사용하지 않는다.

## Artemis 첫 예비 측정

stock OpenJDK 21.0.12.1, Artemis 2.42.0, broker 2 cores, 별도 client 4 cores,
1 KiB message, bounded in-flight 100. 각 80 s 부하의 40 s warmup 후 30 s server-JVM
counter window이며, 모든 TID affinity와 100% counter scheduling을 확인했다.

| 부하 | 목표 msg/s | CPU 활용률 | L2 code MPKI | FE / BE | non-warmup transfer p99 |
|---|---:|---:|---:|---:|---:|
| CORE queue, 1 destination, nonpersistent | 10,000 | 40.07% | 0.363 | 12.86 / 68.15% | 0.164 ms |
| CORE queue, 1 destination, nonpersistent | 30,000 | 75.37% | 0.368 | 15.79 / 56.04% | 0.735 ms |
| AMQP durable topic, 10 destinations, persistent | 1,000 | 15.49% | 3.542 | 21.41 / 59.61% | 0.367 ms |
| AMQP durable topic, 10 destinations, persistent | 5,000 | 69.21% | 2.410 | 21.30 / 58.85% | 0.931 ms |

공식 client는 각 실행을 success로 종료했고 sent=completed=received였다.
완료 수는 각각 800,993 / 2,403,439 / 80,073 / 400,529였다. 이는 delivery count 검증이며
메시지 본문 전체를 별도 oracle와 비교했다는 뜻은 아니다. 30k arm의 bounded-in-flight
blocked 누계는 18회였고 나머지는 0이었다. FE/BE는 raw top-down slot 비율이다.

단순 CORE 경로는 낮은 MPKI로 우선순위를 내린다. AMQP는 코드 miss가 더 많지만
BE 약 60%로 **frontend-dominant workload나 prefetch 성공 사례로 승격하지 않는다**.
1k arm은 활용률 경계에 가까워 fresh repeat와 JIT/GC 분리 확인이 필요하다.
아직 indirect-target PEBS 분석이나 F/G 삽입은 하지 않았다.

첫 시도는 공유 디스크 사용률이 기본 max-disk-usage 90%를 넘어 producer가 막혀 폐기했다.
private broker에 min-disk-free=10 GiB를 명시하고 재실행했다. 디스크 보호를 끄지 않았으며
persistent arm의 journal/fsync 기본값을 유지했다. 첫 실패의 생성 state 23,132,504 B는
해시와 제외 사유를 남긴 뒤 삭제했다. 측정 호스트에는 별도 사용자의 QEMU도 실행 중이었다.

## 후보와 정상 운영 조건

| 후보 | 데이터센터 역할 / 사용할 부하 | 초기 운영 설정과 검증 | A-3에서 볼 대상 | 주의할 병목 |
|---|---|---|---|---|
| Apache Artemis | 메시지 broker; 공식 JMS `perf client` | 1 KiB 메시지, CORE queue 및 AMQP durable topic, 1–10 destinations, bounded in-flight 100; producer/consumer와 broker CPU 분리, persistent arm은 journal/fsync 유지 | ordered executor의 다음 Runnable 및 protocol callback | I/O 대기, 큐가 비어 lookahead 불가, 같은 wrapper만 반복 |
| Keycloak | 인증·세션 서비스; 공식 Gatling benchmark | production 모드 + PostgreSQL + TLS; authorization-code/login, refresh, introspection을 각각 측정한 뒤 서비스 근거가 있는 mix; 우선 1 realm/10k users/10 clients | grant provider의 `process`, authenticator/provider 후속 호출 | password hashing·서명 연산 지배; 보안 비용을 낮춰 FE 비율을 만들지 않음 |
| Flink + Nexmark | 스트림 처리; 경매 이벤트 join/window/aggregation | q3/q5/q9/q11 우선; 2–4 task slots에 맞는 CPU, state backend와 30 s checkpoint 유지; warmup/evaluation 분리, bounded state와 완료된 checkpoint 확인 | mailbox에 있는 다음 Mail의 runnable, operator chain 후속 처리 | mailbox 자체가 차갑다는 보장 없음; 정상 record 경로는 default action으로 흐를 수 있음 |
| OpenSearch | 검색·로그 분석; 공식 Benchmark `http_logs`/`big5` | 처음엔 제한된 문서 수의 명시적 subset, 1–2 shards; term/range/aggregation/full-text query mix, 이후 정상 indexing 병행; cache와 보안 기본 의미 유지 | action별 request handler, worker가 실행할 다음 search task | Lucene 루프·메모리·merge 지배; coordinating thread에서 미리 가져와도 다른 core의 worker L2는 데워지지 않음 |
| Apache Pinot | 실시간 OLAP; broker/server를 통한 dashboard SQL | fact 1M rows + 소규모 dimension, 8–16 segments부터 시작; filter/group-by/top-k와 작은 fact-dimension join, MSE 활성화; 결과 oracle와 stage stats 확인 | `OpChain` root의 `nextBlock` 및 후속 operator | vectorized loop·hash join·메모리 대기; executor의 공통 Runnable 주소만 예열하면 효과 없음 |

표의 수치는 초기 탐색 설정이지 production 대표값이나 최종 benchmark 점수가 아니다.
각 서비스에서 부하를 올려 **할당 CPU 활용률 ≥15%**, 오류 없이 달성 가능한 처리율,
사전에 정한 latency/lag 조건을 만족하는 범위에서 MPKI가 큰 지점을 고른다.
document/realm/operator 개수를 무작정 늘리거나 JIT/code cache를 억제해서 miss를 만들지 않는다.
Flink Nexmark의 공식 V2 예시는 대규모 클러스터 설정이므로 로컬 축소 실험을 공식 점수로
부르지 않는다. V2의 처리량 지표만으로 latency SLO 통과를 주장하지 않는다.

## 소스에서 확인한 지점과 lead-time 가설

버전은 소스 검토를 고정하기 위한 것으로 최신 버전이라는 주장이 아니다.
원문 URL, 파일 경로, SHA-256은 evidence의 `source_manifest.json`에 기록했다.

1. **Artemis 2.42.0:** `ProcessorBase.executePendingTasks`가 task queue를 poll한 뒤
   `doTask`를 호출하고 `OrderedExecutor.doTask`가 `Runnable.run`을 실행한다.
   현재 task를 처리하기 전에 같은 consumer가 안전하게 참조할 수 있는 다음 task의
   실제 target을 예열하는 방식이 후보다. premature dequeue로 순서/종료/yield 의미를
   바꾸지 않아야 한다. 공통 wrapper가 target이면 내부 captured callback까지 분석해야 한다.
2. **Keycloak 26.4.0:** `TokenEndpoint.checkGrantType`에서 grant provider를 얻고,
   client/parameter/DPoP 검사 및 context 구성을 거쳐 `grant.process`를 호출한다.
   검사 구간이 같은 thread에서 유효한 lead time을 줄 수 있다. provider의 다른 메서드는
   이미 앞서 호출되므로, 모든 provider 코드가 cold라고 가정하지 않는다.
3. **Flink 2.1.0:** `MailboxProcessor.processMailsNonBlocking`은 batch의 Mail을 순서대로
   처리한다. `Mail.run`은 `actionExecutor.runThrowing(runnable)`로 연결된다.
   Mail wrapper보다 내부 runnable이 후보다. batch의 priority, cancellation, suspension을
   보존해야 하며 record 처리의 `mailboxDefaultAction`과 miss 기여를 별도로 측정한다.
4. **OpenSearch 3.2.0:** `NativeMessageHandler`는 action으로 registry를 찾고 request를
   역직렬화한 뒤 같은 thread 또는 executor에서 처리한다. registry는 request reader와
   handler를 보유한다. 같은 thread 경로는 역직렬화 전후가 후보지만, 일반 worker 경로는
   consumer 쪽의 다음 작업에서 target을 가져오는 편이 L2 locality에 맞다.
5. **Pinot 1.3.0:** `OpChainSchedulerService.register`는 executor에 작업을 제출하고,
   작업 내부에서 root operator의 `nextBlock`을 반복 실행한다. 다음 chain의 실제 root와
   operator DAG가 각각 F와 G의 후보다. Java wrapper 메서드가 모든 query에서 같을 수
   있으므로 wrapper entry prefetch만으로 generalization을 주장하지 않는다.

이 중 구조적인 우선순위는 **Artemis의 다음 작업 → Keycloak의 이미 결정된 grant →
Flink의 mailbox/record 경로 분해 → OpenSearch → Pinot**다. 이는 높은 MPKI의 예측 순위가
아니라 target과 injection site를 구체적으로 검증하기 쉬운 순서다.

## JVM 구현과 측정

Java 객체 참조나 `jmethodID`는 실행 코드 주소가 아니다. 소스의 `invokevirtual`/
`invokeinterface`도 C2가 inline/devirtualize할 수 있다. 먼저 stock JVM의 안정된 부하에서
user-mode L2 code MPKI와 top-down을 측정하고, 높은 경우만 PEBS/LBR 및 시간 정보가 있는
JIT code map으로 실제 miss와 native indirect call의 연관을 확인한다.

GC/compiler/interpreter/runtime stub/native DSO/compiled application 비중을 구분한다.
기존의 C6·affinity 통제가 없는 JVM 10+ MPKI 기록을 새 후보의 근거로 재사용하지 않는다.
코어별 C6 off, 고정 2 GHz, 모든 worker TID의 affinity, counter scheduling을 확인한다.
warmup 시간만 채웠다고 steady state로 확정하지 않고 compilation/GC/code-cache 변화와
시간 구간별 수치를 확인한다. 프로파일링 실행과 최종 시간 측정 실행은 구분한다.

구현은 기존 `jit_prefetch`의 C2 prefetch emit 기반을 조사하되, 이번 F는 함수 entry에서
자기 몸체를 가져오는 기존 방식과 달리 **미래 receiver의 실제 compiled target**을 대상으로 한다.
기존 V2 패치는 현재 call 바로 앞에서 callee entry를 예열하고 call rebind 때 함께 수정하는
방식이다. emitter 참고는 가능하지만 다음 queued task를 미리 resolve하거나 충분한 lead
time을 확보하는 구현은 아니며, 최신 JVM 이식과 patching protocol 재검토도 필요하다.
정적 분석으로 call site/receiver 관계/삽입 위치를 정하고 런타임에 안전하게 target을 얻는
intrinsic을 우선 검토한다. unresolved target에는 힌트를 생략하고, JIT 재컴파일·unload·
deoptimization과 moving GC를 처리해야 한다. JVMTI load/unload map은 진단 수단이며
그 자체로 수명 안전한 prefetch API가 되지는 않는다.

확정된 미래 target F부터 평가하고, 동적 target/lead time이 부족하다는 측정 근거가 있을 때
history predictor를 추가한다. baseline/NOP/F/G/F+G를 동일 설정에서 비교하고, screening 후
새 5-pair 확인으로 CPU/request와 throughput·latency를 함께 보고한다.
일반 JVM의 이득이나 3–5% 향상을 아직 약속할 근거는 없다.

## 일차 자료

- [Ceph Object Gateway](https://docs.ceph.com/en/latest/radosgw/)
- [Artemis 공식 perf 도구](https://activemq.apache.org/components/artemis/documentation/2.21.0/perf-tools.html) — 실제 CLI 옵션은 로컬 2.42.0 `help perf client`로 재확인.
- [Artemis ordered task processor](https://github.com/apache/artemis/blob/2.42.0/artemis-commons/src/main/java/org/apache/activemq/artemis/utils/actors/ProcessorBase.java)
- [Keycloak Benchmark](https://www.keycloak.org/keycloak-benchmark/), [AuthorizationCode/refresh 시나리오](https://www.keycloak.org/keycloak-benchmark/benchmark-guide/latest/scenario/authorization-code)
- [Keycloak TokenEndpoint](https://github.com/keycloak/keycloak/blob/26.4.0/services/src/main/java/org/keycloak/protocol/oidc/endpoints/TokenEndpoint.java)
- [Nexmark queries와 실행 모드](https://github.com/nexmark/nexmark/blob/master/README.md), [V2 운영 설정](https://github.com/nexmark/nexmark/blob/master/GUIDE_V2.md)
- [Flink MailboxProcessor](https://github.com/apache/flink/blob/release-2.1.0/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/mailbox/MailboxProcessor.java)
- [OpenSearch 공식 workload 종류](https://docs.opensearch.org/latest/benchmark/workload-types/), [request dispatch](https://github.com/opensearch-project/OpenSearch/blob/3.2.0/server/src/main/java/org/opensearch/transport/NativeMessageHandler.java)
- [Pinot MSE의 지원 범위와 운영 제약](https://docs.pinot.apache.org/release-1.3.0/reference/multi-stage-engine), [OpChain scheduler](https://github.com/apache/pinot/blob/release-1.3.0/pinot-query-runtime/src/main/java/org/apache/pinot/query/runtime/executor/OpChainSchedulerService.java)
- [JVMTI CompiledMethodLoad/Unload](https://docs.oracle.com/en/java/javase/21/docs/specs/jvmti.html#CompiledMethodLoad)

Artemis 원본 배포 archive는 단일 rsync 20 MiB/s 및 순차 SHA-256 검증 후 NAS로 보관했고
기존 경로에 alias를 유지했다. 실제 측정은 로컬 실행본을 사용했다. 기존 4묶음의 새 실측과
추적 결과는 [Solr·Cassandra·Trino·DaCapo 재탐색](class_a_jvm_recheck_20260924.md)에 별도로 정리했다.
