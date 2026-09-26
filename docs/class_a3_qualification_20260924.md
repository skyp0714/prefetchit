# A-3 후보 선별: 높은 코드 MPKI와 미래 호출 대상의 miss를 먼저 확인

이번 작업은 **prefetch 삽입 전 qualification**이다. gem5·Envoy·μSuite SetAlgebra에서 새 고MPKI 후보를 확인하지 못했다. 이벤트 큐·함수 포인터·큰 실행 파일만으로 후보를 승격하지 않는다. 신규 성능 향상이나 speedup 결과가 아니다.

## sTLB 해석

소프트웨어 data prefetch가 코드 주소의 translation을 미리 준비해 이후 instruction page walk를 줄일 가능성을 포함하는 것이 맞다. 앞선 FeedSim staged 대 exact-NOP의 별도 2쌍 진단은 요청당 ITLB completed walks **−47.13%**, walk-active cycles **−72.10%**, ITLB miss 중 STLB hit **+31.63%**였다. 이는 translation 비용 감소와 일치한다. STLB hit 수가 감소해야 성공인 것은 아니다. 이 카운터만으로 L1 iTLB 직접 채움이나 특정 내부 TLB 동작을 증명하지는 않는다. BTB miss는 별도다.

근거는 [8시간 실험 기록](class_a_overnight_20260924.md)과 그 증거 묶음의 translation 진단이다. 성능 확인용 5쌍과 이 진단 2쌍을 합치지 않는다.

## 설정과 판단 규칙

- **활용률 ≥15%인 유효 부하 중 최대 baseline user L2 code MPKI**를 선택한다. 서비스는 오류 0, 제공 부하의 ≥95% 처리, 이번 로컬 gateway/RPC screen의 p99 ≤20 ms를 요구했다. 과부하 측정값도 기록하되 선택에서 제외한다.
- 새 후보는 ≥5 MPKI를 우선하며 ≥10이면 특히 유망하다. 2–5는 미래 callee 쪽의 높은 miss coverage가 확인되어야 다음 단계로 간다. 이는 탐색 우선순위이며, 기존 FeedSim 성공을 부정하는 보편적인 물리 한계가 아니다.
- 서버와 부하 생성기의 CPU를 분리하고 2 GHz/HWP 고정, turbo·C6 off, uncore 설정과 복원을 기록했다. 빌드와 측정은 직렬 실행했다. 바이너리·입력은 로컬 저장소에서 실행했다.
- `L2I`는 `event=0x24,umask=0x24:u`. MPKI는 `1000 × L2I / instructions:u`. `C4/80`은 **indirect branch**이며 indirect jump도 포함하므로 indirect-call 횟수라고 부르지 않는다. Top-down은 user slots 비율이다. [Intel GNR event 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).
- 각 설정 1회의 선별 측정이다. 구성 간 작은 수치 차이를 통계적으로 확인된 차이라고 주장하지 않는다.

## gem5: 구조는 맞지만 이번 정상 설정은 코드 miss가 적음

기존 SPEC 735 로그에도 O3 10-core full-system 설정이 있었다. 이번에는 설치된 SPEC gem5 실행 파일과 **그 패키지에 맞는** RISC-V Linux-boot 설정으로 CPU 모델/코어 수와 Ruby 경로를 재측정했다. 별도 최신 gem5 소스와 패키지 바이너리의 버전을 혼동하지 않는다.

| 설정 | user L2 code MPKI | 활용률 | Retiring | Bad spec | FE bound | BE bound | FE latency | Indirect branches/kI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| O3 1 core, 10¹⁰ ticks | 0.0575 | 97.5% | 42.0% | 13.3% | 28.6% | 16.5% | 12.9% | 17.78 |
| O3 4 cores, 10¹⁰ ticks | 0.0356 | 99.1% | 42.7% | 10.6% | 26.7% | 20.0% | 12.6% | 20.39 |
| O3 10 cores, reference | 0.00775 | 99.8% | 40.8% | 8.6% | 24.7% | 25.5% | 10.2% | 16.07 |
| Timing 4 cores, reference | 0.00341 | 99.9% | 47.5% | 7.5% | 24.7% | 20.0% | 9.4% | 27.87 |
| Ruby LinearGenerator, reference | 0.0163 | 99.9% | 42.7% | 10.6% | 34.9% | 9.0% | 14.5% | 9.87 |

이는 **host CPU** 카운터이며 guest cache miss가 아니다. guest core 수를 늘려도 host 실행은 1코어다. O3/Timing은 지정 tick 상한까지의 boot prefix이며, Linux 완전 부팅이나 SPEC 점수를 주장하지 않는다. 가장 짧은 실행은 약 1.9초이고 O3 10-core/Timing/Ruby는 약 42/67/81초다. Ruby는 합성 메모리 traffic이며 실제 애플리케이션 실행 결과가 아니다.

EventQueue의 virtual `process()`는 A-3 형태에 맞지만, 이번 설정들은 L2 코드 miss가 너무 적다. **gem5 전체 설정에 대한 부정은 아니다.** 재개한다면 작은 hot loop의 반복 횟수만 늘리기보다, 실애플리케이션 ROI에서 CPU·coherence·device 처리가 함께 활성화되는 설정을 확인한다. [gem5 EventQueue API](https://doxygen.gem5.org/develop/group__api__eventq.html), [Ruby](https://www.gem5.org/documentation/general_docs/ruby/).

SPEC 런타임은 호스트 `/lib` symlink와 SPEC에서 비활성화한 `os.readlink`의 조합 때문에 시작되지 않았다. **실험용 복사본만** Python `_safe_realpath`가 `SystemError`도 처리하도록 고쳤다. 원본 입력·native binary·CPU 설정은 바꾸지 않았다. 차이와 전후 hash를 저장하고, 탈락 후 63,360,644 bytes의 실험용 런타임 복사본을 삭제했다.

## Envoy: 인증·권한·TLS·압축 추가 후에도 낮은 MPKI

Envoy 1.31.0, 2 workers/2 cores, 64 keepalive connections, 별도 코어의 wrk2와 nginx를 사용했다. 세 API path에서 3,351 B JSON을 반환하는 **gateway microbenchmark**이며 완전한 업무 서비스는 아니다. JWT는 RS256/local JWKS이고 RBAC는 검증된 role을 검사한다. 정상 200, token 누락 401, 금지 role 403, gzip 복원 후 body hash를 확인했다. 계측 구간의 JWT/RBAC 허용 수와 압축 수도 대조했다.

각 구성을 2k/10k/20k RPS에서 측정했다. TLS+gzip의 10k가 과부하였으므로 같은 구성의 5k도 추가했다. 12초 warmup 후 25초의 perf를 수집했고, wrk2의 corrected p99는 40초 client 실행 전체에서 얻었다.

| 구성·선택점 | L2 code MPKI | 활용률 | FE bound | BE bound | p99 |
|---|---:|---:|---:|---:|---:|
| Proxy, 20k RPS | 0.1968 | 67.5% | 32.7% | 24.6% | 1.86 ms |
| JWT+RBAC, 10k RPS | 0.2289 | 72.1% | 35.3% | 18.0% | 2.83 ms |
| JWT+RBAC+TLS+gzip, 2k RPS | 0.3640 | 21.3% | 38.6% | 15.5% | 1.53 ms |
| 같은 구성, 5k RPS 추가 확인 | 0.3000 | 52.0% | 38.8% | 14.3% | 1.55 ms |

Proxy 2k는 활용률 8.4%로 제외했다. JWT 20k, TLS+gzip 10k/20k는 요구 rate·지연 조건으로 제외했다. **과부하 상태의 0.55 MPKI를 후보 값으로 채택하지 않는다.** 전체 sweep, miss/request, indirect branch 빈도, top-down 전체 항목은 증거의 `qualification.tsv`에 남긴다.

JWT/RBAC 설정은 [Envoy 1.31 JWT 명세](https://github.com/envoyproxy/envoy/blob/v1.31.0/docs/root/configuration/http/http_filters/jwt_authn_filter.rst)와 [RBAC 명세](https://github.com/envoyproxy/envoy/blob/v1.31.0/docs/root/configuration/http/http_filters/rbac_filter.rst)를 따른다. FilterManager의 다음 filter callback은 live target 후보지만, 이번 세 구성은 MPKI 단계에서 탈락했다. [해당 소스](https://github.com/envoyproxy/envoy/blob/v1.31.0/source/common/http/filter_manager.cc).

## μSuite SetAlgebra: 먼저 정답 검증을 복구

예전 실행 스크립트는 mid-tier에 필요한 인자를 누락했고, 서버 내부의 perf/BCC 진단도 함께 실행했다. 실험용 소스 복사본에서 진단을 제외하고 정상 인자를 사용했다. 별도 rate-limited 비동기 gRPC client는 고정 seed, 최대 256 outstanding requests, 2초 deadline을 사용한다. 원본 서버 소스·dataset·의존성은 보존했다.

초기 실행의 RPC는 성공했지만 최종 문서 목록이 항상 비었다. query mix 문제만으로 단정할 수 없어 독립 정답 검사를 추가했고 두 버그를 확인했다.

1. mid-tier의 `UnpackIntersectionServiceResponse`가 출력 포인터를 새 vector로 바꿔 호출자에게 결과를 전달하지 않았다. 실험용 helper에서 전달받은 vector를 채우도록 수정했다.
2. leaf는 중간 교집합이 비었을 때 기존 결과를 지우지 않고 반복문을 끝냈다. 해당 경로에서 결과를 비우도록 수정했다.

첫 정답 검사에서는 35,000건 중 17,637건이 틀렸고, 첫 버그만 수정한 실행에서는 17,363건이 틀렸다. 이 실행들과 정답을 검증하지 않은 initial/refine 결과는 **전부 선별에서 제외**한다. 수정 전후의 throughput 차이는 prefetch 이득이 아니다.

최종 입력은 원래 로컬 1 GiB Wikipedia posting-list prefix에서 만든 **702개 합성 query**다. 서로 다른 문서의 공통 검색어로 만든 351개와 무작위 검색어 351개를 섞고, query당 서로 다른 2–4개 term을 사용했다. 예상 결과의 50%가 비어 있지 않으며 모든 응답을 offline set intersection과 비교했다. 숫자가 아니거나 정렬되지 않은 입력 행과 잘린 마지막 행은 query 생성에서 제외했다. 기존 서버가 길이 >1,000 posting list를 건너뛰므로 그 제한도 반영했다. 전체 upstream dataset 또는 production query 분포라고 주장하지 않는다.

| 최종 수정본 | 전체 활용률(4코어) | 전체 L2 code MPKI | mid / leaf MPKI | 정답·요청 검증 | 채택 |
|---|---:|---:|---:|---|---|
| 1,000 QPS | 6.01% | 0.0863 | 0.1029 / 0.0514 | 35,000건, 오류·오답 0 | 활용률 미달 |
| 3,000 QPS | 17.49% | 0.0444 | 0.0552 / 0.0217 | 105,000건, 오류·오답 0 | 정상 설정이나 MPKI 미달 |
| 6,000 QPS | 37.32% | 0.1016 | 0.1326 / 0.0236 | 210,000건 중 요청 오류 1; 완료 209,999건 오답 0 | 오류 조건으로 제외 |

3,000 QPS의 전체 FE bound는 38.86%, BE bound는 34.74%, indirect branches/kI는 15.76이다. mid-tier 자체 활용률도 24.82%로 기준을 통과하지만 MPKI는 0.0552뿐이다. 이 설정에서 간접 분기가 많다는 사실은 코드 miss가 많다는 뜻이 아니다. 두 tier는 서로 다른 2코어씩을 사용하며, 전체 값은 동일 길이 구간의 서로 겹치지 않는 카운터를 합산했다. idle CPU는 각 tier 0.004% 미만로 별도 확인했다.

## 신규·재검증 후보

아래는 **구조를 근거로 한 후보**이며, 높은 MPKI나 성능 향상을 측정한 목록이 아니다.

| 후보 | 일찍 읽을 수 있는 미래 target | reasonable한 설정 탐색 | 현재 제약 |
|---|---|---|---|
| **신규 우선: Ceph RGW** | request의 `RGWOp`, 권한 검사·초기화 후 `execute`/`complete` | 실제 RADOS backend, 정상 replication·인증, 4–64 KiB GET/PUT/HEAD/LIST 혼합, 동시성 1/4/8/16 | 미설치·미측정. 빈 backend나 인증 생략으로 MPKI를 만들지 않음. IO 대기와 gateway CPU 효율 분리 |
| **신규 우선: Apache Traffic Server** | Event/Continuation의 현재 member-function handler | TLS cache proxy, 정상 cache hit/miss 혼합, 4–64 KiB object, 정상 동시성·필수 plugin만 사용 | 미측정. handler가 바뀔 수 있어 과거 target을 그대로 다음 target으로 가정할 수 없음 |
| PostgreSQL mixed query | `PlanState::ExecProcNode`, 식 평가/AM 함수 포인터, plan의 자식 node | durable OLTP 및 작은 join/aggregate/JSON query mix, prepared/unprepared 구분, 4/8/16 clients | 단순 pgbench는 C6 off 후 ≤0.3. README의 옛 25–108을 현재 값으로 쓰지 않음. 기존 소스에 prefetch macro가 있어 baseline 재구축 필요 |
| ClickHouse mixed query | ready processor의 virtual `work()`, 다음 pipeline operator | TPC-H/TPC-DS 등의 서로 다른 operator mix, concurrency 1/4, CPU 할당에 맞춘 max_threads 1/2/4 | 기존 server 약 0.25. 행 수 증가만으로 코드 경로가 넓어지지 않음. vector loop의 backend 지배 여부 확인 |
| MongoDB SBE | plan-stage의 virtual `getNext()`와 자식 stage | indexed lookup 외 정상 lookup/group/sort/aggregation mix, working set·durability 유지 | 기존 mixed screen 약 0.48. 새 query mix는 미측정. 실제 실행 plan으로 SBE stage 확인 |
| μSuite HDSearch | gRPC completion tag, 다음 request 처리·DSO callback | 의미 있는 query mix, tier별 활용률·정답 대조, 정상 fanout/worker 수 | 옛 고MPKI를 재사용하지 않음. 이번 SetAlgebra 수정본은 정상 3k QPS에서 낮은 MPKI로 제외 |

구현 근거: [Ceph RGW request 처리](https://github.com/ceph/ceph/blob/v19.2.0/src/rgw/rgw_process.cc), [ATS Continuation](https://github.com/apache/trafficserver/blob/10.0.x/include/iocore/eventsystem/Continuation.h), [PostgreSQL executor](https://github.com/postgres/postgres/blob/master/src/include/executor/executor.h), [ClickHouse IProcessor](https://github.com/ClickHouse/ClickHouse/blob/master/src/Processors/IProcessor.h), [MongoDB PlanStage](https://github.com/mongodb/mongo/blob/master/src/mongo/db/exec/sbe/stages/stages.h). Ceph는 `retarget`에서 op를 교체할 수 있으므로 그 이후의 live op를 사용하는 삽입 지점이 필요하다. ATS도 lock과 handler 변경을 고려해야 한다.

## 높은 MPKI 설정을 찾은 뒤의 순서

1. 무개조 baseline의 `FRONTEND_RETIRED.L2_MISS` PEBS(C6/03, config1=0x13)와 user LBR을 별도 실행으로 수집한다. 실제 **indirect CALL**을 판별하고 target entry line/첫 256 B/같은 함수 내부, 제한된 후속 callee의 miss를 나눠 집계한다. DSO·미해결 symbol·lost sample도 분모에 남긴다. LBR에서 가깝다는 사실만으로 인과적 miss 기여나 상한이라고 부르지 않는다.
2. cold target coverage가 충분하면 정적 def-use·지배 관계·alias/lifetime 분석으로 **runtime target을 읽을 위치와 삽입 위치**를 결정한다. target 주소 자체는 실행 중 함수 포인터/vtable에서 읽으므로 DSO 함수도 가능하다. 그 시점에 live object를 안전하게 읽을 수 있어야 한다.
3. address availability, queue depth, target 일치율, 독립적인 작업이 있는 lead time을 진단한다. 바로 다음 call뿐 아니라 cold body와 정적 callee도 후보로 삼는다. 읽을 수 있는 depth/lead가 부족할 때만 aggressive 예측을 추가한다.
4. 같은 정상 설정에서 원본/F/G/F+G와 각각의 exact NOP를 비교하고, 선택 후 새 paired 5회로 CPU/request·wall/throughput·latency를 확인한다. F+G의 추가분도 따로 보고한다.

기존 Scylla의 약 12 MPKI는 MySQL과 코어를 공유하는 B miss regime이다. 새 standalone A 후보로 세지 않는다. 기존 FeedSim은 F의 긍정적인 reference이며 이번 탐색 결과와 합치지 않는다.

이번 신규 설정은 모두 MPKI 단계에서 탈락했으므로 PEBS/LBR cold-target coverage나 prefetch 삽입까지 진행하지 않았다. 따라서 이들 workload의 **indirect-call miss 기여율을 새로 측정했다는 주장은 없다**. 다음 적격 후보에서는 ITLB walk-active/completed/STLB-hit도 별도 수집해 translation 효과를 분리한다.

## 증거·재현·보관

`llvm_prefetchit/migration/evidence/class_a3_qualification_20260924/`에 전체 표, 독립 검증 결과, 압축 raw 증거와 재현 script를 보존한다. raw perf 33개에서 42행(합산행 포함)을 재계산했고 플랫폼 설정·HWP 복원 73개 context를 검사했다. `raw_evidence.tar.gz`에는 운영 설정·명령·binary hash·수정 patch·client 정답 검사·부정 결과를 넣고, 생성한 실행 파일과 object는 제거한다. 원본 benchmark source/input 및 기존 winning/reference binary는 건드리지 않는다.
