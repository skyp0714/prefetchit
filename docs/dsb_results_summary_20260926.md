# DSB prefetch 누적 결과와 커널 lead-time 해석

2026-09-26까지의 누적 결과에 같은 날 시작한 다섯 서비스 후속 실험을 추가했다.
MovieId의 과거 user-cycle 결과, 이후 전체 CPU/요청 결과, 탐색 결과를
서로 합산하지 않는다. Media와 SocialNetwork는 두 애플리케이션이며 서비스
개수를 독립 애플리케이션 성공 수로 세지 않는다.

## MovieId 포함 새 정책 풀셋 확인

Media는 공유 8코어·600 RPS·tracing 100%, Social은 공유 4코어·600 RPS·tracing 10%다.
아래는 새 전체 스택 7개 seed block에서 baseline, 기존 정책, 새 정책 NOP, 새 정책을
교대해 비교한 **user+kernel CPU/완료 요청 절감률**이다. 가족 내 타깃들을 동시에 바꾼
조합의 결과이며 서비스별 수치를 더하지 않는다. 구간은 개별 95% paired-log t CI다.

| 서비스 | 새 정책 vs baseline | 새 정책 vs 같은 배치 NOP | 기존 정책 대비 추가 이득 |
|---|---:|---:|---|
| MovieId | **1.26% [0.73, 1.78]** | **1.25% [0.84, 1.66]** | 보존 p11a artifact 대비 4.81% [4.17, 5.44]; 빌드 차이 포함 |
| ComposeReview | **1.31% [0.96, 1.67]** | **1.69% [1.39, 1.98]** | 0.37% [−0.03, 0.77], 미확정 |
| Rating | 2.09% [−0.04, 4.18] | **1.25% [0.35, 2.15]** | 1.15% [−0.01, 2.30], 미확정 |
| ComposePost | **1.06% [0.67, 1.45]** | **1.58% [1.13, 2.03]** | 0.25% [−0.16, 0.67], 미확정 |
| UserTimeline | **1.45% [0.83, 2.06]** | **1.49% [0.84, 2.14]** | 0.10% [−0.46, 0.65], 미확정 |

**MovieId의 기존 약 5% 결과는 유효한 별도 지표의 결과다.** 과거 p11a는 당시 wsm 대비
user cycles/요청 약 **5.1% 절감**이었다. 이번 동일 7쌍을 사용자 CPU 시간만 사후 분해하면
baseline 대비 **4.88% [3.31, 6.43]**, NOP 대비 **5.07% [3.34, 6.78]**다.
이번 baseline의 user CPU 비중은 약 35.3%이며 kernel CPU 비용은 약 0.72% 증가했다.
따라서 사용자 영역 약 5%와 전체 CPU 약 1.26%는 함께 성립한다.
과거 user cycles와 이번 user CPU 시간, 서로 다른 baseline의 절감률을 합산하지 않는다.

Media 전체 스택 절감은 0.39% [−0.09, 0.86], Social은 0.10% [−0.16, 0.35]로
확정 이득이 아니다. 전체 CPU 10% 목표에 도달한 정책은 없었다.

커널은 next task 선택 뒤 기존 `sched_switch` 위치를 유지했다. MovieId와 UserTimeline에서
각 13가지 예산·간격·묶음·전후 분할·T0/T1 방식을 탐색했다. 인접 NOP 대비로 고른
UserTimeline 16라인 후보의 별도 7쌍은 off 대비 **−0.46% [−1.02, 0.10]**,
NOP 대비 **0.21% [−0.19, 0.60]**여서 CPU 순이득을 확인하지 못했다.

별도 `first_space` 진단에서는 전환 완료 후 데이터 접근 지연 중앙 구간이 MovieId
192–256에서 64 미만, UserTimeline 256–384에서 64 미만 TSC tick으로 줄었다.
발행→전환 완료 중앙 구간은 각각 1,536–2,048와 1,024–1,536 tick이었다.
**페이지를 데우는 효과와 0이 아닌 전환 전 lead는 확인됐다.** 이 값은 pinned alias의
데이터 접근 진단이며 실제 첫 명령어 fetch 지연이나 첫 사용까지의 시간은 아니다.
커널 이미지 직접 패치의 hook 비용 절감은 측정하지 않았다.

[새 풀셋 상세](class_b_fullset_20260926.md)와
[공개 결과](../llvm_prefetchit/migration/evidence/class_b_fullset_20260926/results.json)에
선정 규칙 변경, 부하 종료로 제외한 block, 신뢰구간, 코드 해시와 보존 기록을 정리했다.

## 이전 캠페인에서의 커널 lead 해석

아래는 후속 풀셋 실험 전의 기록이다. 당시의 앞당긴 발행 제안은 이번 실험에 적용하지
않았으며, 현재 측정 결과는 위 절을 따른다.

**lead 부족 가능성은 미검증으로 남아 있다.** 이번에는 커널 소스를 패치하고
재부팅한 것이 아니라, 커널 모듈이 `sched_switch` tracepoint 안에서
동기적으로 `prefetcht1`을 발행했다. 사용자 복귀 후 실행되는 훅은 아니다.

발행 순서는 다음과 같다.

`sched_switch의 PF → context_switch/switch_mm → 커널 복귀 경로 → 사용자 타깃 사용`

Linux의 [scheduler 소스](https://github.com/torvalds/linux/blob/v6.8/kernel/sched/core.c)에서도
tracepoint가 context switch보다 앞선다. 따라서 lead가 0이라고 할 수는 없지만,
**실서비스에서 발행부터 타깃 첫 사용까지의 시간 분포와 fill 적시성은 재지 않았다.**
지금까지 기각한 것은 이 발행 위치의 세 정책이며, 더 이른 커널 prefetch가 아니다.

합성 진단에서는 한 라인의 데이터 읽기 지연이 kernel NOP 299.67에서 T1
80.00 invariant-TSC tick으로 줄었다. 실제로 캐시를 데우는 동작은 확인했지만,
실서비스의 16/64라인 버스트가 제때 도착하는지, L1I/ITLB/BPU까지 준비되는지를
보인 결과가 아니다. 이 진단의 1ms sleep은 **커널 T1 발행 전**이다. kernel
T1에 1ms의 lead를 제공한 실험으로 읽으면 안 된다.

다음 원인 분리에는 동일 타깃·라인 예산으로 아래 세 가지 비교가 필요하다.

1. 현재 모듈의 `sched_switch` 발행.
2. 같은 위치에 커널 코드로 직접 삽입: 훅 경유 비용을 분리.
3. 더 이른 위치에 직접 삽입: 발행 시점의 효과를 분리.

3번은 wakeup/enqueue를 후보로 삼되, 실제 실행할 CPU에서의 발행과 migration을
검증해야 한다. Linux wakeup 경로에는 remote-CPU queueing도 있다. 더 이른
발행이 해당 CPU의 유효 cache lead로 연결되는지, 사용 전에 다시 퇴출되는지는
별도로 측정해야 한다. 각 발행 위치의 NOP 대조와 CPU 풀 전체 비용도 포함해야 한다.
이는 후속 실험 조건이며 아직 구현·측정한 결과가 아니다.

## 이전 캠페인의 전체 user+kernel CPU/완료 요청 결과

양수는 비용 절감이다. 고정 요청률에서의 타깃 서비스 비용이며, 처리량 증가나
애플리케이션 전체 CPU 절감이 아니다. 구간은 paired log-ratio의 개별 95% t CI다.
모두 전체 서비스 스택, info 로그, 2GHz/C6 off 조건이다. tracing 비율은
distributed tracing의 표본 비율이며 Intel PT 학습 trace 비율과 다르다.

| 서비스 / 정책 | tracing / 공유 코어 / RPS | baseline MPKI | baseline 대비 절감 [95% CI] | 동일 배치 NOP 대비 | 단계·판정 |
|---|---|---:|---:|---:|---|
| Media ComposeReview / wake8 | 100% / 8 / 600 | 43.35 | **1.35% [1.04, 1.67]** | 1.20% [0.93, 1.46] | 독립 7쌍·채택 |
| Media Rating / wake16 | 100% / 8 / 600 | 55.84 | 0.78% [−0.43, 1.97] | 1.75% [0.84, 2.66] | 독립 7쌍·이득 미확정 |
| Social ComposePost / wake16 | 10% / 8 / 600 | 28.35 | **1.07% [0.81, 1.32]** | 1.29% [0.90, 1.68] | 독립 7쌍·채택 |
| Social UserTimeline / wake16 | 10% / 8 / 600 | 51.81 | **1.41% [1.04, 1.78]** | 1.54% [1.00, 2.07] | 독립 7쌍·채택 |
| Media ComposeReview / wake8 | 10% / 8 / 300 | 49.14 | 0.97% [0.35, 1.59] | 1.18% [0.53, 1.82] | 탐색 3쌍·독립 확인 미수행 |
| Media Rating / wake16 | 10% / 8 / 300 | 65.05 | **0.67% [0.14, 1.21]** | 1.29% [1.04, 1.53] | 독립 7쌍·양수지만 ≥1% 채택 기준 미달 |
| Social UserTimeline / 새 coverage | 10% / 4 / 600 | 57.38 | **2.01% [1.61, 2.41]** | 1.74% [1.40, 2.07], 별도 3쌍 | baseline 대비 독립 7쌍·기존 정책 대비 추가 이득 미확정 |

마지막 캠페인의 같은 4코어 조건에서 기존 wake16은 baseline 대비
**1.40% [0.79, 2.00]**, 새 coverage의 기존 wake16 대비 추가 절감은
**0.62% [−0.09, 1.33]**였다. 따라서 새 후보의 baseline 대비 이득은
확인했지만 기존 정책 교체 기준은 통과하지 못했다. 서로 다른 8코어/4코어
결과를 빼서 운영점 효과나 정책 추가 이득으로 계산하지 않는다.

Media 100%는 600 RPS, 10%는 300 RPS에서 측정했으므로 결과 차이를 tracing
비율만의 효과로 해석하지 않는다. 탐색과 독립 확인을 합치지 않았고, 여러
서비스·후보 전체의 다중비교 보정은 적용하지 않았다.

## MovieId: 별도 지표의 과거 결과

2026-09-21, 공유 8코어·600 RPS·2GHz/C6 off에서의 **user cycles/요청**이다.
최종 표는 유효 반복의 중앙값 비율이며 위의 독립 7쌍 CI와 같은 검증 형식이 아니다.
baseline은 해당 실험의 fat-static/mark 설정이 같은 `wsm`이다.

| 구현 | user-cycle 효율 배율 | MPKI | 반복 / 해석 |
|---|---:|---:|---|
| baseline | 1.000× | 86.6 | 355.2k cycles/요청 |
| dense stream + 재컴파일한 정적 의존성 사이트 (`wsp3`) | 1.044× | 76.7 | 최종 5회 |
| 위 계열 + 라벨·gap (`p6c`) | 1.036× | 76.2 | 최종 유효 4회 |
| run 시작부 post-call 추가 (`p11a`) | **1.054×** | **76.9** | 최종 5회, 337.1k cycles/요청 |
| trace 없는 static graph plan | 1.006× | 82.6 | 최종 5회·힌트 자체의 이득 미확정 |

1.054×는 user-cycle 효율 +5.4%, 요청당 user cycles 약 **5.1% 절감**이다.
전체 user+kernel CPU나 스택 전체가 5.4% 개선됐다는 뜻은 아니다. 최근 확장은
서비스 오브젝트 위주여서 정적 의존성 내부도 재컴파일한 MovieId와 커버리지가 다르다.
과거 문서의 약 1.05×는 당시 시험한 계열의 관측 범위이며 이론적 상한이 아니다.

개발 중 관측은 LD_PRELOAD wake/mark 1.014×(3회), 서비스 inline stream
약 1.028~1.031×(3회), 의존성까지 넓힌 stream과 post-call의 최종 결과가
위 표와 같다. 서로 다른 라운드의 이득을 더하지 않는다.
같은 사이트의 `prefetchit1`은 0.982×, `prefetcht1`은 1.040×였던 별도
3회 비교도 보존되어 있다. `callee burst4`는 baseline 1.015×, NOP twin
1.011×의 탐색값으로 힌트 순이득을 확정하지 못했다.

근거: [MovieId 원기록 §7](prefetch_plan_classB_wakestream.md).

## 그 밖의 DSB 구현과 음성 결과

아래 옛 A-2/A-3/복귀 정책 수치는 원문의 **CPU 효율 증가율**을 유지했다.
위 비용 절감률과 같은 열에 합산하지 않는다. Media 2코어 전용·2500 RPS
조건이며 최근 B 공유 풀 결과와 운영점이 다르다.

| 방식 | 보존된 결과 | 판정 |
|---|---|---|
| Media static handler/자식/손자/NOP 공간, 각 서비스 5정책 | 단일 탐색 최고 MovieId +0.13%, ComposeReview +0.56%, Rating +1.18% | 사전 1.5% 승격 기준 미달·확인 이득 없음 |
| 블로킹 호출 전 사용자 복귀 주소 static T1 | 독립 5쌍: MovieId +0.27% [−0.37, 0.92], ComposeReview +0.02% [−0.23, 0.27], Rating +0.33% [−3.43, 4.23] | 모두 0 포함 |
| 동적 I/O 래퍼 return-PC T0, NOP 대비 | 독립 5쌍: MovieId −0.04%, ComposeReview −0.17%, Rating +0.01% | 모든 CI가 0 포함 |
| 실제 Thrift handler 주소를 인자 decode 전에 prefetch | 단일 탐색: MovieId +0.25% / NOP −0.34%, ComposeReview −0.29% / NOP +0.24% | 양 대조군 대비 순이득 미확정 |
| 호출 직전 Thrift handler prefetch | 단일 탐색: MovieId +0.87% / NOP −0.11%, ComposeReview −1.02% / NOP −0.64% | 순이득 미확정 |

Thrift early-handler의 별도 계측에서는 대부분의 lead가 1024~4096 TSC tick,
MovieId UploadMovieId 평균 약 1854 tick이었다. 이는 **사용자 공간 RPC
정책**의 진단이며 이번 커널 switch-in의 lead 측정이 아니다. 충분한 시간
간격만으로 타깃의 유용성·coverage·전체 CPU 이득이 보장되는 것도 아니다.

이전 headroom 캠페인의 UserTimeline 4코어/600 RPS 별도 구현 결과는 다음과 같다. 모두 단일
탐색이며 확인 실험으로 취급하지 않는다.

| 구현 | baseline 대비 타깃 CPU 절감 | 공유 풀 CPU 절감 | 판정 |
|---|---:|---:|---|
| kernel T1, 정확도 우선 cap16 | +0.32% | −0.35% | 순이득 없이 제외 |
| kernel T1, 정확도 우선 cap64 | −1.25% | −0.13% | 순이득 없이 제외 |
| kernel T1, 범위 확대 cap64 | +0.11% | −0.51% | 순이득 없이 제외 |
| 정적 라이브러리 포함 NOP 공간, 36지점 | −1.14% | — | 타깃 비용 악화·제외 |
| NOP 공간 119지점, 루프 허용 | −0.12% | +0.31% | 주 지표 이득 없어 제외 |

이전 headroom 캠페인의 전체 스택 CPU 절감은 새 coverage/baseline **0.13%
[−0.004, 0.259]**, 공유 풀은 **0.10% [−0.21, 0.40]**로 확정 이득이 아니다.
앞선 B 확장에서 채택된 세 서비스의 스택 기술통계도 약 0.13~0.47%였으며
별도 성공 판정은 아니었다.
서비스별 이득의 합을 전체 스택 이득으로 보고하거나 최대 처리량 10% 향상으로
보고할 근거는 없다.

최근 상세와 보존 증거는 [headroom 결과](class_b_headroom_20260926.md)에 있다.
누적 숫자의 원본 경로·SHA-256과 JSON 추출값은
[`summary.json`](../llvm_prefetchit/migration/evidence/dsb_summary_20260926/summary.json)에 보존했다.
