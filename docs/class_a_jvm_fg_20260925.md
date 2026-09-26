# JVM 후보 13종의 A-2 / A-3 비교

새 서비스 5종(Artemis, Pinot, OpenSearch, Keycloak, Flink), DaCapo 3종, Renaissance 5종의 기본65모드 비교를 완료했다. Pinot의 별도6모드 pilot과 후보별 독립 재검증 결과를 함께 기록한다.

## 구현과 비교 기준

- **G2 / A-2:** C2 최적화 뒤 남은 직접 Java 호출 중 root BCI 순서로 타깃을 선택하고, root 진입에서 현재 `Method::from_compiled_entry`의 첫 두 cache line에 `prefetcht1`을 넣는다. 현재는 깊이 1이다.
- **F2 / A-3:** 진입 시 존재하는 변경되지 않는 reference parameter 또는 final reference field로 receiver를 얻고, vtable/itable에서 실제 호출 주소를 읽는다. 원래 호출이 인라인되었거나 사라졌으면 제외한다. 임의의 다음 queue item이나 아직 계산되지 않은 receiver를 예측하는 구현은 아니다.
- **GF:** 두 방식을 조합한다. **NOP:** 같은 길이의 단일 NOP로 각 힌트를 대체하며 주소 조회 비용은 남긴다. 첫 matrix의 NOP는 GF에 대응한다. 독립 재검증에서는 선택된 G/F/GF 각각에 맞춘 NOP를 사용한다.
- 선택 규칙은 workload 이름이나 외부 trace를 쓰지 않는다. 기본값은 caller bytecode 최소64, G의 direct callee 최소64, call BCI16–192, G/F 각1개 타깃·2lines이다. F는 런타임 receiver의 callee 크기를 미리 알 수 없어 이 callee 크기 필터를 적용하지 않는다. 일반 HotSpot type profile과 인라이닝은 유지되므로 JVM 전체가 profile-free이거나 AOT 분석이라고 주장하지 않는다.
- 기존17u 개발 트리(17.0.21-internal, commit5ef54a04aa15)와21.0.8+9에 구현했다. G1/Parallel/Serial, 정상 non-OSR C2 진입을 지원한다. 정확한 release 정보는 `runtime_versions.json`에 보존한다. 30개 모드/GC 검사, 6개 인코딩 비교, dead/inlined-call 제외 검사를 통과했다. 바이너리 hash는 `smoke_g2.json`, 상대 패치는 `jvm_g2_17.patch`와 `jvm_g2_21.patch`에 있다.

동일 실험 JVM 바이너리에서 flag만 바꾸고 모드마다 새 JVM을 실행했다. CPU 2GHz/C6 off, 대상4cores(Artemis2cores), 별도 client cores, 정상 GC/cache/durability를 유지한다. 측정은 직렬이며 빌드·NAS 전송과 겹치지 않는다. 다른 사용자의 QEMU는 변경하지 않았다.

서비스는 **고정된 요청률에서 CPU/완료 요청 감소율**, suite는 **완료 operation 실행시간 speedup**을 주요 지표로 쓴다. 이는 서로 다른 지표이며 CPU 감소를 처리량 증가로 바꾸어 부르지 않는다. Flink는 내장 datagen source와 chained operator를 포함한 TaskManager 전체 CPU이며, 진행률을 별도 검사한 paced nominal event가 분모다. Artemis는 PMU 동반 예비 비교이고 offered message가 분모다. 나머지 primary는 PMU 없이 측정한다.

## 부하 선별

L2 code MPKI는 user-mode `L2_RQSTS.CODE_RD_MISS / instructions ×1000`이다. stock JVM qualification과 실험 JVM의 A/B baseline을 섞어 speedup을 계산하지 않는다. 아래 값의 원본·설정은 `qualification_comparison.json`에 명시했다. FE/BE 등은 raw slot 비율이며 합을 강제로100%로 정규화하지 않았다.

| workload | L2 code MPKI | 활용률 % | FE % | BE % | Retiring % | Bad spec % | Fetch latency % |
|---|---:|---:|---:|---:|---:|---:|---:|
| Artemis | 1.891 | 15.1 | 20.5 | 59.1 | 15.3 | 5.8 | 14.7 |
| Pinot | 5.443 | 35.0 | 31.6 | 22.1 | 37.5 | 10.3 | 25.2 |
| OpenSearch | 2.302 | 35.8 | 19.3 | 25.0 | 40.3 | 16.6 | 11.0 |
| Keycloak | 1.660 | 93.3 | 13.9 | 15.1 | 67.4 | 4.0 | 10.3 |
| Flink q3 | 0.069 | 44.8 | 16.6 | 16.2 | 56.7 | 10.5 | 7.5 |
| DaCapo tomcat | 2.914 | 16.1 | 34.2 | 29.3 | 22.7 | 14.4 | 24.7 |
| DaCapo spring | 2.056 | 70.3 | 33.3 | 16.3 | 36.6 | 16.0 | 18.2 |
| DaCapo cassandra | 3.284 | 46.1 | 34.9 | 37.5 | 18.1 | 11.8 | 26.0 |
| Renaissance finagle-chirper | 1.274 | 83.9 | 28.7 | 27.0 | 31.7 | 11.5 | 21.6 |
| Renaissance finagle-http | 0.557 | 88.8 | 46.3 | 24.2 | 15.7 | 14.8 | 34.9 |
| Renaissance dotty | 1.670 | 40.4 | 36.7 | 19.7 | 29.3 | 16.1 | 21.8 |
| Renaissance future-genetic | 0.031 | 55.1 | 12.0 | 32.2 | 42.0 | 14.8 | 6.9 |
| Renaissance db-shootout | 0.035 | 72.0 | 12.8 | 38.6 | 39.3 | 9.4 | 5.9 |

Pinot는1M fact/1k dimension·8segments의 MSE150query/s, OpenSearch는50k Wikipedia/2shards·정상 cache/TLS/auth300query/s이다. Keycloak은 production TLS·공식10k users/10clients·durable MySQL에서 client-credentials750flows/s를 사용한다. fresh JVM의 부하 급증을 피하기 위해 최종 비교는 ramp120s/warm180s로 통일했다. Flink/Nexmark q3는500k events/s·RocksDB·30s checkpoint·충분한 입력 budget을 사용한다. 입력 소진/과부하/측정 중 drop 사례는 제외했다.

Pinot의 선택된 부하가 이 후보군에서 가장 높은 MPKI를 보였다. 낮은 MPKI의 Flink·future-genetic·db-shootout도 L2 code-cache miss 가설의 대조 사례로 검사한다. 낮은 L2 code MPKI만으로 TLB 등 다른 frontend 원인을 배제하지 않으며, Flink 재검증에는 순수 CPU 측정 후 별도의 ITLB/코드 miss PMU 구간을 둔다. dotty는 컴파일러 workload이므로 데이터센터 서비스 대표값과 구별한다.

## 첫 비교: 모드당 독립 JVM 1개

양수는 개선, 음수는 악화다. 아직 독립 반복이 없는 수치를 유의미한 이득으로 판정하지 않는다. suite의 한 JVM 안 여러 operation은 독립 JVM 반복이 아니다.

| workload | 주요 지표 | A-2 G2 % | A-3 F2 % | GF % | GF NOP % |
|---|---|---:|---:|---:|---:|
| Artemis | CPU/offered message 감소 | -2.93 | -0.61 | -1.57 | -1.07 |
| Pinot | CPU/완료 요청 감소 | -2.16 | -0.23 | -0.62 | +0.34 |
| OpenSearch | CPU/완료 요청 감소 | -3.29 | -1.83 | -2.11 | +2.57 |
| Keycloak | CPU/완료 요청 감소 | +0.20 | +0.06 | +0.34 | +0.15 |
| Flink q3 | CPU/nominal event 감소 | +5.65 | +4.37 | -1.34 | +2.87 |
| DaCapo tomcat | operation 시간 speedup | -0.04 | +0.28 | +0.29 | +0.03 |
| DaCapo spring | operation 시간 speedup | -1.58 | +1.31 | +1.56 | +1.37 |
| DaCapo cassandra | operation 시간 speedup | -0.24 | -0.61 | -0.68 | -0.65 |
| Renaissance finagle-chirper | operation 시간 speedup | +0.12 | +0.58 | +2.50 | -0.14 |
| Renaissance finagle-http | operation 시간 speedup | -3.31 | -0.42 | -2.13 | -1.22 |
| Renaissance dotty | operation 시간 speedup | -2.97 | -1.61 | -0.93 | -3.62 |
| Renaissance future-genetic | operation 시간 speedup | -0.36 | +0.95 | +1.23 | +0.66 |
| Renaissance db-shootout | operation 시간 speedup | -7.18 | -9.60 | -9.17 | -5.09 |

첫 비교에서 실제 힌트가 삽입된 C2 코드를 측정 종료 후 확인한다. 이 정적 hint 수는 실행 빈도, lead time, 유효 miss coverage를 뜻하지 않는다. G2/F2가 불리해도 미래 타깃 prefetch 전체가 불가능하다는 결론은 아니다.

## 독립 재검증과 진단

screening 전에 확정한 재검증 규칙은 workload별 실제 힌트 방식 중 주요 지표가1% 이상 개선된 최선의 방식을 고르는 것이다. 새 JVM5블록에서 baseline/해당 방식/해당 NOP 순서를 섞어 비교한다. screening 수치는 재사용하지 않으며 paired log cost ratio의 t(4)95% 구간을 보고한다. 기본값 대비 이득과 NOP 대비 힌트 효과를 별도로 판정한다.


| workload | 방식 | baseline 대비 % (95% CI) | 맞춤 NOP 대비 % (95% CI) |
|---|---|---:|---:|
| flink | G | +3.95 [-13.51, +18.72] | +0.39 [-15.16, +13.85] |
| spring | GF | +0.47 [-3.88, +5.02] | +1.38 [-2.69, +5.62] |
| finagle-chirper | GF | -3.09 [-4.75, -1.41] | -1.74 [-2.72, -0.76] |
| future-genetic | GF | -0.52 [-1.41, +0.38] | -0.72 [-1.23, -0.22] |
| pinot | F16 (기본 BCI) | +3.75 [-1.82, +9.01] | +2.23 [-3.50, +7.64] |

**5후보·75실행을 모두 완료했다. baseline 대비와 맞춤 NOP 대비의 양의 효과를 함께 지지한 후보는 없다. 현재 G2/F2로 일반화 가능한1% 이상 순이득을 확인하지 못했으며, Flink·Pinot의3–4% 평균을 성공 수치로 채택하지 않는다.**

suite 재검증은 전 arm 최소180s 워밍업이다. Flink는 최소180s 뒤 compiler CPU≤1%인10s 구간3개를 요구하고, Pinot는 최대600s 안에 같은 quiet 조건을 요구했다. 일반 JIT/GC/cache 설정은 유지했다. 사전 quiet gate가 측정 중 재컴파일까지 막는 것은 아니다.

Pinot F16은 baseline 대비5블록 모두 양수였지만, block3의 baseline/NOP에서 측정 중 matched-thread compiler CPU가 약6.1%/7.3%로 증가했다. 그 블록의 큰 차이가 전체 평균을 끌어올렸다. 원래75실행과5블록 통계는 모두 유지한다. 사후 참고로 이 블록의 세 arm을 함께 빼면 남은4블록의 CPU 감소는 baseline 대비 +1.79%, NOP 대비 +0.22%다. 이것은 사전 제외 규칙이 아닌 민감도 확인이며 새로운 확정 이득으로 취급하지 않는다.

Flink의 큰 실행 간 변동은 내장 source task CPU에서도 관찰됐다. 이 thread에는 datagen과 chained operator가 함께 있으므로 순수 Flink engine 또는 generator 비용으로 분해해 부르지 않는다. `flink_thread_audit.json`에 구간별 값을 보존했다.

별도 Flink PMU 구간은15개 모두 입력률·scheduling 검사를 통과했다. L2 miss/event 감소는 baseline 대비 +7.37% (95% CI −0.76~+14.85%), NOP 대비 +4.25% (−3.84~+11.71%)로 양의 효과를 확정하지 못했다. ITLB walk 감소도 확인되지 않았다. 이 구간은 primary CPU 측정 뒤의 별도 구간이다.

위95% 구간은 개별 비교의 구간이며 다중 비교에 대한 동시 보장은 아니다. 최종 결과에서는 baseline/NOP 비교 전체를 한 집합으로 둔 Holm 보정도 별도 참고 검사로 보고한다. 이 검사는 후보 선택·실행 횟수·종료 조건을 바꾸지 않는다.

Holm 보정 후 양의 효과를 지지한 비교: 없음 (전체 10개 비교).

### Pinot의 별도 trace

분모는 각 capture의 전체 샘플이며, 매핑되지 않은 샘플도 포함한다. 진입 line 비율은 두 snapshot에서 안정된 현재 normal C2 entry에 한정한다. 아래 indirect 비율은 최근32개 LBR의 indirect call/jump 도착 line과의 공간적 일치다.

| 프로세스·event | 샘플 | 진입 첫2line % | 첫8line % | indirect 도착 line % | 부하 검사 |
|---|---:|---:|---:|---:|---|
| broker | 14782 | 47.79 | 58.48 | 12.92 | 통과 |
| server | 9312 | 38.06 | 51.60 | 16.03 | 통과 |
| broker_fe64 | 10869 | 47.14 | 53.83 | 14.62 | 통과 |
| server_fe64 | 5894 | 35.05 | 43.01 | 21.34 | 통과 |

L2 miss의 함수 진입부 집중은 관찰되지만, 현재 G2/F2가 그 caller를 선택했는지·제때 실행되었는지는 이 비율로 알 수 없다. 단일 hottest root도 전체의1% 미만으로 miss가 여러 경로에 분산되어 있다. 첫2line을 첫8line으로 늘렸을 때의 공간적 차이는 실제 prefetch 실험이나 성능 이득이 아니다.

### Pinot BCI pilot

F16만 기본 BCI16, 나머지 힌트 방식은 최소BCI32다. 모드당1JVM의 예비 비교다. F16의 독립 재검증은 위 표에 별도로 보고했다.

| 모드 | CPU ms/query | CPU 감소 % | 별도 PMU MPKI | 별도 PMU 부하·scheduling |
|---|---:|---:|---:|---|
| f16 | 8.4000 | +1.23 | 5.690 | 통과 |
| gf | 8.4778 | +0.31 | 5.401 | 통과 |
| g | 8.6356 | -1.54 | 5.447 | 통과 |
| f | 8.7089 | -2.40 | 5.178 | 통과 |
| gf_nop | 8.5667 | -0.73 | 5.602 | 통과 |
| base | 8.5044 | +0.00 | 5.702 | 통과 |

MPKI는 명령 수 증가로도 낮아질 수 있으므로, 별도 PMU 구간의 요청당 miss·명령 수도 함께 확인한다. 다음 표에는 부하와 scheduling 검사를 통과한 구간만 넣는다.

| 모드 | L2 code miss/query | ITLB walk/query | 명령/query (백만) |
|---|---:|---:|---:|
| f16 | 197532.6 | 12335.8 | 34.717 |
| gf | 196112.9 | 11839.4 | 36.313 |
| g | 197761.1 | 12739.5 | 36.308 |
| f | 195941.9 | 12894.1 | 37.843 |
| gf_nop | 201133.6 | 12718.9 | 35.906 |
| base | 198594.0 | 12546.0 | 34.830 |

같은 JVM에서 root nmethod의 holder에 연결한 declared-class vtable과 삽입 코드의 대조 결과:

- `f16/code_1`의 `MultiStageOperator.nextBlock`: logger. 실제 receiver subclass별 실행 빈도는 측정하지 않았다.
- `f/code_1`의 `MultiStageOperator.nextBlock`: getNextBlock. 실제 receiver subclass별 실행 빈도는 측정하지 않았다.
- `gf/code_1`의 `MultiStageOperator.nextBlock`: getNextBlock. 실제 receiver subclass별 실행 빈도는 측정하지 않았다.

Pinot에서는 별도 PEBS/LBR의 L2 miss와 FE latency≥64cycles를 각각 수집해, 안정된 JIT 메타데이터로 진입 첫1/2/4/8line과의 공간적 연관을 분석했다. 서로 다른 event의 별도 capture이므로 stall 중첩 비율이나 성능 상한으로 해석하지 않는다. BCI 최소32 pilot과 기본 F16을 비교하여 선택된 vtable 메서드도 같은 JVM에서 확인했다. 이 임계값은 lead time의 대리값이며 cycle 수가 아니다. 원본은 `traces/pinot_g2_base/`, `pinot_lead32/`에 보존했다.

DaCapo는 내부 client/lifecycle을 포함한 전체 JVM이고 standalone 서버 결과가 아니다. Renaissance chirper/db-shootout과 Flink blackhole sink는 의미적 정답 validator가 없으므로 harness 성공·진행률 검사와 정답 검증을 구별한다. Tomcat V1 결과는 별도 보존하며 G2/F2 결과에 합치지 않는다. standalone Solr·Cassandra/JDK11·Trino/JDK25의 이전 qualification은 이번 G2/F2 실행 결과가 아니다.

F2는 아직 임의의 다음 queue item, getter chain, 계산 후 생기는 receiver, OSR 진입을 포괄하지 않는다. future-genetic 재검증의 GF snapshot에서도 F2 hint는0–2개에 불과했다. 이 결과는 현재 선택·삽입 규칙의 결과이며 미래 호출 prefetch 전체의 불가능성을 입증하지 않는다. Pinot에서 더 긴 BCI만으로 개선되지 않았으므로, 후속 구현의 가설은 주소 조회 비용을 줄이는 직접 타깃 표현, 제어흐름을 고려한 타깃 선택, receiver dataflow 확장이다. 이 후속 구현을 이번에 검증했다고 주장하지 않는다.

## 재현 및 보관

작업 결과: `llvm_prefetchit/results/class_a_jvm_fg_20260925/`. `PROTOCOL.md`, plan/command JSON, raw counters, compact logs, source patches, binary hashes, 제외 사유를 보존한다. 실패·완료 실행의 private scratch와 decoded trace 임시파일은 제거한다. 원본 소스·입력·현재 기준 바이너리는 보존한다. NAS 보관은 serial rsync20MiB/s와 rate-limited SHA256 검증을 사용했다. 오프로드한 원본 패키지와 구형 바이너리는 로컬 symlink로 접근 경로를 유지하고, 현재17/21 기준 이미지는 로컬에 보존했다. NAS 경유로 성능을 재지 않는다.

기존 [call-chain software instruction prefetching 연구(PACT2007)](https://research.ibm.com/publications/call-chain-software-instruction-prefetching-in-j2ee-server-applications)는 삽입 거리와 힌트 개수를 독립적인 조절 변수로 다룬다. 이번 BCI/line 진단의 참고이며 해당 Power5/WebSphere 결과를 현재 CPU의 speedup으로 사용하지 않는다.

근거: [Intel Granite Rapids PMU 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/), [Renaissance](https://github.com/renaissance-benchmarks/renaissance), [OpenJDK Method entry](https://github.com/openjdk/jdk17u/blob/master/src/hotspot/share/oops/method.hpp), [Pinot1.3 OpChain scheduler](https://github.com/apache/pinot/blob/release-1.3.0/pinot-query-runtime/src/main/java/org/apache/pinot/query/runtime/executor/OpChainSchedulerService.java).

추가 정리: JDK21 기준 이미지 358.7MB를 NAS에 검증 백업하고, 불필요한 중간 빌드 870.7MB를 제거했다. 전체 소스와 현재 기준 이미지는 유지했다. 앞선 패키지·구형 바이너리 오프로드는 총7.71GB이며 각 manifest에 검증 기록이 있다.

저장소에 남기는 근거는 `llvm_prefetchit/migration/evidence/class_a_jvm_fg_20260925/`의 약0.65MB이다. 반복되는 상세 예제·시작 구간 drop timestamp 목록은 원본에만 유지하고, 근거본에는 측정값·집계·원본 SHA256을 남겼다. 전체 원본 JSON은 로컬 결과 폴더에 보존한다. 최종 바이너리/소스 hash 확인, 두 마지막 단계의 CPU 제어값 복구, 실험 JVM 종료 확인은 `final_verification.json`에 기록했다.

[공개 G2 패치와 검증용 소스](../llvm_prefetchit/migration/schemes/jvm_fg_20260925/README.md). 빌드 산출물과 전체 raw 기록은 Git에 포함하지 않는다.
