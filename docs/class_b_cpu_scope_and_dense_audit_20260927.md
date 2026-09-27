# CPU/request 범위와 고밀도 prefetch 근거 재검토

2026-09-27의 기존 결과 재분석이다. 새 성능 측정은 수행하지 않았다. 절감률은 양수가 개선이고, CI는 각 연구의 paired log-ratio에 대한 개별 95% 구간이다.

| 측정 범위·정책 | CPU/request 절감 | 95% CI |
|---|---:|---:|
| 이전 trace 정책, MovieId의 user+kernel CPU, 600 RPS | +1.26% | [+0.73, +1.78] |
| 이전 trace 정책, Media 3개 서비스 동시 변경, 전체 stack CPU, 600 RPS | +0.39% | [−0.09, +0.86] |
| 새 LBR 분산 배치, Media 3개 서비스 동시 변경, 전체 stack CPU, 1,000 RPS | +0.21% | [−0.35, +0.76] |

따라서 개별 서비스의 1–2%와 전체 stack의 1–2%를 혼용할 수 없다. 마지막 두 전체 stack 결과는 모두 개선 미확인이다. 정책·부하가 달라 세 행을 하나의 개선 추세로 해석하지 않는다. 원본은 [기존 fullset 결과](../llvm_prefetchit/migration/evidence/class_b_fullset_20260926/results.json)와 [새 확인 결과](../llvm_prefetchit/migration/evidence/class_b_e2e_20260927/placement_decision.json)에 있다.

## 높은 MPKI가 의미하는 것과 아직 모르는 것

과거 MovieId의 80대 MPKI는 `L2_RQSTS.CODE_RD_MISS / instructions:u × 1000`이다. 이 이벤트는 speculative instruction fetch의 L2 miss 요청을 센다. `FRONTEND_RETIRED.L2_MISS`는 miss를 경험한 retired instruction을 세므로 두 모집단을 빼거나 나누어 wrong-path 비중이나 실제 fill coverage를 만들 수 없다. [Intel Granite Rapids 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

MPKI가 높으면 미스가 많다는 증거지만, 매 미스가 동일한 길이로 실행을 멈춘다는 뜻은 아니다. 현재 코드 prefetch가 ITLB·분기 예측 상태·커널 작업까지 모두 개선한다고 가정할 수도 없다. 이전 MovieId 진단에서 user CPU는 그 서비스 CPU의 약 35.29%였고, user CPU 4.88% 절감에 비해 user+kernel CPU 절감은 1.26%였다. 전체 stack을 합치면 다른 서비스 비용도 포함된다. [기존 CPU·타임라인 분석](class_b_request_and_miss_timeline_20260927.md).

최신 LBR 배치는 서비스당 11–20개 사이트에 머물렀고 선택된 정책의 heldout 미스 주소·경로 coverage는 1.88–2.31%였다. 이 결과로 광범위한 코드 삽입의 한계를 판단할 수 없다. 커널 시간-bin 계획은 더 많은 주소를 겨냥했지만 실제 적중·fill 성공과 critical stall 제거율은 아직 모른다. [새 E2E 결과](class_b_e2e_distributed_20260927.md).

과거 문서가 first-touch 라인 수 4,540개를 실행 경로 miss의 최대치로 보고, 집계 miss와의 차이 5,900개를 모두 wrong-path로 배정한 것은 증명되지 않았다. 첫 접근 이후에도 같은 라인이 재미스할 수 있고, 이벤트와 trace의 모집단도 다르다. 높은 MPKI의 대부분이 제거 불가능하다는 확정 근거로 사용하지 않는다.

또한 80대 MPKI는 과거 바이너리·운영점의 값이다. 최근 600 RPS fullset 선정에서 MovieId baseline MPKI는 63.94였고, 최신 1,000 RPS 지연 확인 구간에는 PMU를 동시에 실행하지 않았다. 최신 지연 실험의 MPKI도 80이라고 가정하지 않는다.

## 과거 고밀도 삽입의 유효성

과거 Round 13은 서비스·아카이브의 직접 call마다 callee 진입 4/8라인을 prefetch했다. 각각 정적 prefetch 4,876개·9,752개로 기록됐다. 이는 Verilator의 함수 내부 sequential lookahead와 타깃 선택이 다른 방식이다.

원본 `flat_codegen/dsb_build/media/ws/ab13/ab.csv`를 다시 확인했다.

| Arm | 실행 수 | non-2xx 발생 실행 | p99 범위 |
|---|---:|---:|---:|
| baseline | 3 | 3 | 1,000–1,080 ms |
| callee 4라인 | 3 | 2 | 19.1–2,210 ms |
| callee 4라인 NOP | 3 | 2 | 25–1,160 ms |
| callee 8라인 | 3 | 3 | 990.2–2,310 ms |

오류 0, p99<100 ms, 600 RPS 대비 ±4%라는 운영 조건으로 보면 baseline–candidate 유효 쌍은 **0개**다. 따라서 당시의 1.015x·1.003x를 정상 부하의 개선율이나 고밀도 삽입 실패의 확정 증거로 재사용하지 않는다. 원본 행·SHA-256·제외 기준은 [감사 기록](../llvm_prefetchit/migration/evidence/class_b_dense_history_audit_20260927.json)에 보존했다.

Verilator의 sequential 방식은 긴 함수 내부에서 앞으로 실행될 코드와 앞으로 배치된 코드가 상당 부분 일치하는 조건에서 효과를 보였다. Media에서는 함수·가상 호출·콜백 전이가 많으므로 단순 주소 lookahead의 타깃 적중률은 별도 검증 대상이다. [기존 Verilator 분석](results_summary_20260924.md).

고밀도 방식을 판단하려면 NOP 공간 제한을 없앤 컴파일러 삽입으로 sequential lookahead와 callee burst를 분리하고, 각 정책을 원본 및 동일 배치 NOP와 비교해야 한다. 동일 시드 baseline–baseline으로 먼저 재현성을 확인한 뒤, 정상 부하에서 전체 stack CPU/request·평균·p99와 별도 PMU 구간의 절대 miss/request·instructions/request를 함께 측정해야 한다. 현재 결과로 1–2%를 prefetch 자체의 상한으로 정할 근거는 없다.
