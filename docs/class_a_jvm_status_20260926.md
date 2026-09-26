# JVM 스킴 결과와 takeaway — 2026-09-26

**확인된 ≥1% 성능 이득은 아직 없다.** 기존 13종 G/F/GF 탐색과 후보 재검증에서 채택할 결과가 없었고, 요청한 100회 재검증은 아래처럼 미완료다. 과거 5블록 탐색과 새 표본을 합치지 않는다.

G는 C2에 남은 직접 호출을 이용한 A-2, F는 미리 읽을 수 있는 receiver의 실제 vtable/itable 호출 주소를 이용한 A-3, GF는 조합이다. 구현 범위와 이전 13종 결과는 [기존 결과](class_a_jvm_fg_20260925.md)에 있다.

| 100회 재검증 후보 | 완료 블록 / 목표 | baseline 대비 개선 | 동일 정책 NOP 대비 | baseline 대비 95% CI |
|---|---:|---:|---:|---:|
| pinot / lead32_f16 | 2 / 100 | -4.65% | -4.92% | [-32.08, +17.08]% |
| spring / gf | 2 / 100 | +0.16% | -1.43% | [-60.97, +157.00]% |
| flink / g | 2 / 100 | -16.11% | -17.33% | [-81.50, +25.72]% |

각 블록은 baseline/PF/NOP의 독립 fresh JVM 3개다. 지금은 각 2블록으로 유의성 판정을 하지 않는다. Pinot는 CPU/완료 query 감소율, Spring은 operation 시간 비율의 speedup, Flink는 CPU/nominal event 감소율이다. 양수는 개선이다. Flink는 REST 진행률을 검사했지만 분모가 정확한 완료 event 수인 지표는 아니고 datagen CPU도 포함한다.

최종 판정은 사전 고정한 100블록·paired log CI·6비교 Holm 보정을 사용하고 baseline과 NOP 모두에 대한 개선을 요구한다. 중간 결과로 조기 성공/실패를 선언하지 않는다.

| CloudSuite Solr 9.1.1 | baseline 대비 CPU/query 감소 | NOP 대비 CPU/query 감소 | L2 code MPKI |
|---|---:|---:|---:|
| G | -4.13% | -4.26% | 1.442 |
| F | -3.87% | -4.26% | 1.456 |
| GF | -1.55% | -0.40% | 1.372 |

공식 165,255문서/14GB index, 4 cores, 14GB heap, 600 QPS. 모든 arm은 응답 oracle·요청률 검사를 통과했다. **arm당 1회 탐색**이므로 CI나 유의성 결론은 없다. 같은 grid의 baseline CPU/query 1.7659ms, MPKI 1.439를 사용했다. 이전 qualification baseline과 섞지 않았다. GF는 MPKI가 1.439→1.372로 낮아졌지만 CPU 비용은 증가했다.

| CloudSuite Cassandra 4.1 부하 선별 | 서버 활용률 | L2 code MPKI | FE / BE | 상태 |
|---|---:|---:|---:|---|
| A:1000 | — | — | — | warmup JIT gate 실패, 제외 |
| A:3000 | — | — | — | warmup JIT gate 실패, 제외 |
| A:6000 | 24.98% | 1.915 | 28.1% / 38.3% | baseline 선별만 완료 |
| B:3000 | 16.21% | 0.987 | 24.1% / 37.6% | baseline 선별만 완료 |
| B:6000 | 26.55% | 1.058 | 25.1% / 38.5% | baseline 선별만 완료 |

공식 Cassandra+YCSB, 1M records × 10 × 100B, RF1, 4 cores, 4GB heap, 16 client threads, 정상 durability와 데이터 검증 유지. A:6000은 목표 6,000 ops/s에서 실측 5,823 ops/s로 사전 ±3% 기준을 통과했다. 정상 활용률 후보 중 MPKI 최대는 A:6000의 1.915다. **G/F 삽입 비교는 아직 수행하지 않았다.**

Takeaway:

- 현재 일반적인 G/F 규칙에서 JVM 성능 이득이 검증됐다고 말할 근거가 없다. 100회 재검증도 아직 끝나지 않았다.
- Solr에서는 code MPKI 감소가 CPU 비용 감소로 이어지지 않았다. 다음 실험에서는 타깃 조회·추가 명령의 비용과 lead time·병목 중첩을 분리해서 측정해야 한다.
- Cassandra의 정상 부하에서는 L2 code MPKI가 1~2 수준이고 BE 비중도 높다. 이 수치만으로 큰 이득을 예상하기 어렵다.

[기계 판독 결과](../llvm_prefetchit/migration/evidence/jvm_status_20260926/results.json)에는 원 측정값·설정·제외 이유를 남겼다. 위 표는 고정 시점의 결과이며 실행 상태를 실시간으로 표시하지 않는다.
