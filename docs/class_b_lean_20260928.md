# 10–20µs 중심 prefetch: 삽입 축소와 E2E 검증

2026-09-28의 약 7시간 캠페인에서 104회의 유효한 Media 전체 스택 성능 실행을 완료했다. MovieId·ComposeReview·Rating을 함께 변경했고, C4(약 85% util)와 C16(이전 처리량 plateau 부근)을 독립 비교했다. 별도 PMU/PEBS/gate 진단은 이 실행 수와 성능 판정에 섞지 않았다.

**10% E2E 개선은 확인하지 못했다.** 코드 팽창과 삽입 수는 크게 줄였지만, 미스 감소가 요청 지연·처리량 개선으로 이어졌다고 확정할 수 있는 결과는 아래 독립 기준으로 판단한다.

- v4 ungated C4: 전체 CPU/request 절감 +0.024% (95% CI -0.350~+0.396%), 평균 절감 -0.318%. 사전 승격 기준 불통과.
- v4 ungated C16: 전체 CPU/request 절감 -0.199% (95% CI -0.870~+0.467%), 평균 절감 -0.198%. 사전 승격 기준 불통과.
- v5 callee ungated: 별도 2-block 탐색에서 원본 대비 CPU 절감 -0.146%, 평균 절감 -0.482%. 원본/NOP 양쪽 점추정 기준 불통과. 독립 확인을 하지 않아 확정 개선으로 승격하지 않았다.

양수는 비용 절감/개선이다. C4/C16 독립 자료와 각 탐색 자료는 합치지 않았다.

![독립 확인의 효과와 95% 구간](figures/class_b_lean_confirmation_20260928.png)

## V4 ungated C4: 사전 기준 불통과

| arm | CPU µs/request | RPS | 평균 ms | 실행별 p99 평균 ms | util % |
|---|---:|---:|---:|---:|---:|
| base | 5928.93 | 1170.59 | 3.34782 | 5.87006 | 85.44 |
| matched_nop | 5895.70 | 1187.31 | 3.29889 | 5.84630 | 86.17 |
| selected_candidate | 5927.55 | 1166.74 | 3.35844 | 5.83772 | 85.19 |

| 비교 기준 | CPU 절감 [95% CI] | 평균 절감 [95% CI] | p99 절감 [95% CI] | 처리량 증가 [95% CI] |
|---|---:|---:|---:|---:|
| base | +0.024% [-0.350, +0.396] | -0.318% [-2.836, +2.139] | +0.554% [-1.174, +2.252] | -0.328% [-2.717, +2.120] |
| matched_nop | -0.541% [-0.877, -0.205] | -1.804% [-3.372, -0.260] | +0.148% [-1.640, +1.904] | -1.733% [-3.189, -0.256] |

양수는 개선. 개별 paired-log t95 구간이며 6개 새 seed block을 사용했다. 전체 CPU·평균은 원본/NOP 양쪽 CI 하한 >0, p99는 양쪽 하한 >-2%가 기준이다. closed-loop 처리량과 평균 지연은 연관된 지표다.

| 원본 변동 | 최소 | 최대 | 실행 간 CV % |
|---|---:|---:|---:|
| stack_cpu | 5906.33955 | 5957.71142 | 0.294 |
| mean_ms | 3.28274 | 3.39715 | 1.330 |
| p99_ms | 5.80430 | 5.93638 | 0.828 |

| 서비스 | 전체 CPU 절감 vs 원본 [95% CI] | user CPU 절감 vs 원본 [95% CI] |
|---|---:|---:|
| movie-id-service | -0.115% [-0.892, +0.657] | +0.227% [-2.335, +2.725] |
| compose-review-service | +0.113% [-0.529, +0.750] | -0.427% [-2.273, +1.386] |
| rating-service | +0.035% [-1.132, +1.188] | -0.163% [-2.931, +2.531] |

서비스별 수치는 보조 분해이며 전체 E2E 판정과 별개다. 개별 구간에는 다중 비교 보정이 없다.

## V4 ungated C16: 사전 기준 불통과

| arm | CPU µs/request | RPS | 평균 ms | 실행별 p99 평균 ms | util % |
|---|---:|---:|---:|---:|---:|
| base | 5579.26 | 1393.77 | 11.41007 | 20.88785 | 97.31 |
| matched_nop | 5562.55 | 1397.56 | 11.37831 | 20.89481 | 97.26 |
| selected_candidate | 5590.47 | 1391.02 | 11.43287 | 21.01278 | 97.28 |

| 비교 기준 | CPU 절감 [95% CI] | 평균 절감 [95% CI] | p99 절감 [95% CI] | 처리량 증가 [95% CI] |
|---|---:|---:|---:|---:|
| base | -0.199% [-0.870, +0.467] | -0.198% [-0.805, +0.405] | -0.598% [-1.016, -0.183] | -0.199% [-0.797, +0.403] |
| matched_nop | -0.501% [-1.154, +0.148] | -0.478% [-1.059, +0.099] | -0.566% [-1.324, +0.186] | -0.469% [-1.034, +0.099] |

양수는 개선. 개별 paired-log t95 구간이며 6개 새 seed block을 사용했다. 전체 CPU·평균은 원본/NOP 양쪽 CI 하한 >0, p99는 양쪽 하한 >-2%가 기준이다. closed-loop 처리량과 평균 지연은 연관된 지표다.

| 원본 변동 | 최소 | 최대 | 실행 간 CV % |
|---|---:|---:|---:|
| stack_cpu | 5568.82241 | 5591.93597 | 0.160 |
| mean_ms | 11.39171 | 11.43335 | 0.139 |
| p99_ms | 20.75005 | 21.01898 | 0.428 |

| 서비스 | 전체 CPU 절감 vs 원본 [95% CI] | user CPU 절감 vs 원본 [95% CI] |
|---|---:|---:|
| movie-id-service | -0.138% [-0.801, +0.521] | +0.158% [-0.582, +0.893] |
| compose-review-service | +0.143% [-0.050, +0.337] | +0.187% [-0.649, +1.016] |
| rating-service | -0.279% [-0.798, +0.238] | -0.509% [-1.695, +0.664] |

서비스별 수치는 보조 분해이며 전체 E2E 판정과 별개다. 개별 구간에는 다중 비교 보정이 없다.

## V5 gate-free callee: 2-block 탐색, 독립 확인 미실시

| arm | CPU µs/request | RPS | 평균 ms | 실행별 p99 평균 ms | util % |
|---|---:|---:|---:|---:|---:|
| base | 5934.60 | 1168.41 | 3.35374 | 5.90956 | 85.45 |
| callees_ungated_nop | 5933.09 | 1157.86 | 3.38428 | 5.82492 | 84.61 |
| callees_ungated_it0 | 5943.25 | 1162.62 | 3.36989 | 5.78141 | 85.12 |

| 비교 기준 | CPU 절감 % | 평균 절감 % | p99 절감 % | 처리량 증가 % |
|---|---:|---:|---:|---:|
| base | -0.146 | -0.482 | +2.167 | -0.494 |
| callees_ungated_nop | -0.172 | +0.427 | +0.747 | +0.409 |

현재 표는 탐색 점추정이다. V4 확인실험과 합치거나 승격 근거로 사용하지 않는다.

원본 대비 p99 절감의 개별 95% 구간은 [-10.815, +13.627]%로 0을 포함한다. 두 쌍으로 p99 개선을 확정할 수 없다.

## 별도 진단

| arm | 서비스 | period | 복귀 후 <20µs event 비중 % | 10–20µs 비중 % | 전체 추정 event/request | 10–20µs main 잔여 미스의 정적 타깃 중첩 % |
|---|---|---:|---:|---:|---:|---:|
| base_c4 | movie | 4093 | 63.365 | 41.663 | 448.038 | — |
| v5_c4 | movie | 4093 | 65.279 | 43.141 | 454.706 | 18.228 |

PEBS retirement timestamp이며 fetch 시각이 아니다. 스케줄 나이는 kernel 복귀 시간도 포함한다. 정적 중첩은 남아 있는 sampled miss 중의 비율이며 원래 미스 커버리지·실제 발행·cache fill 성공률이 아니다. 현재 진단은 MovieId, 한 sample period이며 all3/C16 미스 분포 확인으로 일반화하지 않는다.

| gate 진단 서비스 | checks/s | early % | eligible % | expired % |
|---|---:|---:|---:|---:|
| movie | 239384.3 | 10.214 | 49.662 | 40.125 |
| compose | 504078.6 | 8.121 | 57.087 | 34.792 |
| rating | 169260.7 | 9.998 | 54.685 | 35.317 |

Gate 카운터는 별도 callee counter build의 논리 그룹 결과다. PEBS는 켜지 않았으며 atomic counter 자체의 교란은 남는다. 하드웨어 prefetch 명령 발행 수 또는 fill 성공 수가 아니다.


## v5 실제 코드 크기

| 서비스 | 정적 IT0 수 | executable bytes 증가 vs 원본 |
|---|---:|---:|
| movie | 751 | +0.225% |
| compose | 798 | +0.278% |
| rating | 718 | +0.206% |

최종 대상은 원본과 새 main executable에 모두 정의되는 함수 entry이며 RIP-relative IT0, instruction boundary, 동일 배치 NOP를 감사했다. Gate/clock/runtime 심볼이 없는지도 확인했다.

## 미스 위치: entry와 함수 내부

![복귀 후 미스 밀도](figures/class_b_lean_timeline_20260928.png)

| arm / main-image 표본 | entry cache line % | 그 뒤 cache line % | symbol 미매핑·중복 % | v5 대상 entry line % | v5 대상 함수 내부 뒤쪽 line % |
|---|---:|---:|---:|---:|---:|
| 01_base_c4 / all_mapped_main | 70.449 | 25.532 | 4.019 | 18.972 | 6.087 |
| 01_base_c4 / age10_20_mapped_main | 71.016 | 24.038 | 4.945 | 18.407 | 5.907 |
| 02_v5_c4 / all_mapped_main | 69.643 | 26.228 | 4.129 | 18.359 | 6.752 |
| 02_v5_c4 / age10_20_mapped_main | 69.873 | 24.304 | 5.823 | 18.228 | 5.696 |

분모는 각 행의 main-image 잔여 PEBS 이벤트다. entry는 함수 시작 주소가 속한 64B line이며, 함수 시작부터 64바이트 전체를 의미하지 않는다. 함수 alias는 합치고 겹치는 symbol 범위는 제외했다. v5 함수 집합은 실제 감사한 target 이름이며 원본과 v5의 각 symbol 주소에 따로 적용했다. 정적 연관성으로 실제 issue/fill 성공률을 추정하지 않는다.

## 이번 반복에서 확인한 변화

v5의 post-ROI PMU 한 창에서는 원본 대비 retired instructions/request 증가가 MovieId/ComposeReview/Rating에서 약 0.60/0.39/0.15%였다. 이전 gated callee의 약 3–5% 증가보다 작게 관측됐다. 서로 다른 단계의 단일 PMU 관측이므로 gate만의 정확한 비용 차이나 E2E 개선으로 해석하지 않는다.

| v5 서비스 | instructions 절감 vs 원본 | user cycles 절감 vs 원본 | L2I 절감 vs 원본 | retired FE_L2 절감 vs 원본 | retired FE_L2 절감 vs own NOP |
|---|---:|---:|---:|---:|---:|
| MovieId | -0.603% | +0.308% | +0.395% | -0.655% | +1.322% |
| ComposeReview | -0.393% | -0.015% | +1.088% | -1.375% | -1.830% |
| Rating | -0.149% | +0.195% | -3.197% | +4.351% | +4.217% |

양수는 감소다. 별도 8초 PMU 진단의 기술 통계이며 반복의 불확실성 구간이 없다. **삽입 비용은 줄였지만, 이전 callee 정책의 retired miss 감소가 세 서비스에 공통으로 유지되지는 않았다.** Gate 제거는 최종 코드 배치도 바꾸므로 이를 시간 제한 유무만의 인과 효과로 해석할 수 없다. 각 정책의 NOP 비교가 필요한 이유다.

현재 독립 원본 측정에서도 C4→C16으로 처리량은 1170.6→1393.8 RPS로 늘지만 평균은 3.348→11.410ms, p99는 5.870→20.888ms로 증가했다. util은 85.44→97.31%였다. 처리량을 높이는 operating point와 낮은 개별 요청 지연을 주는 operating point가 다르다.

별도 gated-callee 카운터 진단에서는 논리 그룹의 MovieId 49.7%, ComposeReview 57.1%, Rating 54.7%가 설정된 시간 구간에 도달했다. 설정한 구간이 실제 경로에서 상당히 열리는 것을 확인했다. Atomic counter와 gate 실행의 교란이 있으므로 무계측 실행의 발행 비율로 그대로 옮기지 않으며, eligible 그룹 수는 하드웨어 hint 수·fill 성공 수와 다르다.

**현재 MovieId에서는 함수 entry의 커버리지 부족이 구체적으로 드러났다.** 원본 main-image 미스의 70.45%는 함수 시작 cache line에 있었지만, v5가 대상으로 삼은 함수들의 entry line은 원본 미스의 18.97%에만 겹쳤다. 대상이 아닌 함수의 entry line에 52.01%가 있었다. 함수 내부의 뒤쪽 line은 전체 main 미스의 25.53%였다. 따라서 다음 타깃 선정에서는 누락한 함수 entry를 먼저 확인할 근거가 있다. v5에서도 target line의 잔여 중첩은 18.36%였다. 이 비율은 실제 발행·fill 성공률이나 개선 가능한 성능의 상한이 아니다.

10–20µs 원본 main 미스에서도 대상 entry line 중첩은 18.41%, 대상 밖 함수 entry는 53.16%였다. hot 함수 이름을 넓게 모아도 직접 call로 연결되는 위치·caller 크기·lead·삽입 예산 필터를 거친 **최종 타깃**이 실제 미스 지점을 충분히 덮는 것은 아니었다. 소수의 큰 함수로만 미스가 몰리지도 않았다. 원본 상위 함수 각각의 비중은 약 1.4–1.9%이며 future 결과 처리, Jaeger Reference 정리와 Span 쓰기, Thrift socket 읽기 등이 포함됐다.

새 trace의 원본/v5에서 20µs 이전 이벤트 비중은 63.36/65.28%, 10–20µs는 41.66/43.14%였다. 실행 시간으로 정규화한 밀도는 8–15µs 부근에서 높았다. 단일 기간의 추정 이벤트/request는 448.04→454.71이었고 이 profiling 차이를 성능 악화의 확정치로 사용하지 않는다. 현재 자료로는 시간 구간만 더 조정해 10% E2E 이득을 얻을 근거가 없다.

원본/v5의 2009/2114개 PEBS 표본은 모두 완전한 실행 구간에 연결됐고 LOST/THROTTLE은 없었다. 그중 TID가 -1인 289/320개는 같은 process PID와 CPU의 scheduler 구간으로 보완했다. 직접 TID 표본만 사용해도 20µs 이전 비중은 58.08/60.48%, 10–20µs는 38.31/40.86%였다. 정확한 비중은 이 보완 방법에 영향을 받지만 초반 집중은 유지됐다. 이 진단은 MovieId 한 sample period에 한정된다.

다음 반복의 우선순위는 현재의 정확한 미스 IP를 BB/call edge에 연결하고, 누락된 entry line을 선행 caller dominator의 작은 예산으로 덮는 것이다. indirect call로만 도달하거나 크기·lead 필터로 제외된 타깃을 별도로 식별해야 한다. 함수 내부 line은 다음 순위로 다룬다. 시간 검사 추가는 실제 타깃 커버리지와 원본/동일 배치 NOP 비교에서 이득이 남은 뒤 판단한다. BTB/FDIP 또는 ITLB가 주원인이라는 인과 판정은 이번 자료로 내리지 않았다.


## 실험 범위와 판단 기준

MovieId·ComposeReview·Rating 세 바이너리와 그 정적 의존성을 동시에 바꾸고 **Media 전체 스택**을 실행했다. 이번 캠페인의 수치를 Social까지 검증한 전체 Type B 결과로 확대하지 않는다. 원본은 prefetch가 없는 기존 바이너리이며, 각 후보의 NOP 대조군은 같은 ELF의 prefetch opcode만 같은 길이 NOP로 바꾼 것이다. 따라서 후보와 NOP의 비교는 배치와 나머지 계측 코드의 영향을 통제하지만, 원본과 NOP 사이의 코드 생성·정렬 차이는 남는다.

서비스는 8개 CPU(32–39), 클라이언트는 별도 CPU(16–19), 관리 작업은 84–85에서 실행했다. SMT는 끄고 같은 NUMA node를 사용했으며 application tracing은 모든 arm에서 100%다. 모든 arm은 새 스택에서 50초 warmup 후 60초 clean ROI를 측정했다. PMU·PEBS·atomic gate counter는 clean ROI 밖의 진단이다. 빌드·disassembly·trace decode도 독립 성능 확인과 겹치지 않았다. 오류 요청, 부하와 CPU 범위, PMU scheduled ratio, module·scheduler·platform 복구를 확인했다.

C4는 과거 측정에서 util 약 85%였던 동시 요청 수다. C16은 과거 처리량 plateau에 가까웠던 조건이며, 이번에 가능한 모든 concurrency의 최대값을 다시 탐색한 것은 아니다. 서비스 인스턴스 수는 고정이다. **C1은 동시 요청 1개이며 서버가 single-thread라는 의미가 아니다.**

![동시 요청 수에 따른 처리량과 지연](figures/class_b_concurrency_20260927.png)

위 그래프는 [이전 별도 측정](class_b_dense_and_concurrency_20260927.md)이다. C1→C32에서 처리량은 약 434.5→1402.6 RPS, 평균은 2.241→22.744ms, p99는 2.809→46.850ms였다. C16의 약 1395.6 RPS에서 C32로 늘렸을 때 처리량 증가는 약 0.5%에 그쳤다. 높은 동시성에서 처리량과 개별 요청 지연이 서로 다른 방향으로 변할 수 있으므로 CPU/request·RPS·평균·p99를 함께 제시한다.

탐색은 새 seed 2개 block과 정확한 역순 실행을 사용했다. 원본 및 자신의 NOP 양쪽에 대해 CPU/request와 평균 지연의 paired-log 점추정이 개선되고 p99 악화가 2% 미만이어야 다음 후보 자격을 준다. v4에서 이 자격을 모두 충족한 후보가 없어 ungated를 진단적 절충안으로 선택했다. 그 선택을 승리로 해석하지 않았다.

독립 확인은 C4와 C16 각각 새 seed 6개 block × 3개 arm이며 탐색 자료를 합치지 않는다. 원본/NOP 양쪽에서 전체 CPU와 평균 절감의 개별 95% CI 하한이 0보다 크고 p99 절감 하한이 -2%보다 커야 승격한다. closed-loop RPS와 평균 지연은 서로 연관되므로 두 개의 독립 증거로 세지 않는다. 표의 p99는 실행별 p99의 평균이며 모든 요청을 합친 pooled p99가 아니다. 서비스별 분해와 PMU는 보조 분석이고 다중 비교 보정이 없는 개별 구간이다.

## 삽입을 줄인 과정

![정적 힌트 수와 executable section 증가](figures/class_b_lean_static_20260928.png)

그림의 크기는 실행 가능한 ELF section의 합이다. 비할당 debug metadata나 BSS를 코드 증가량에 넣지 않았다. v3 epoch memo는 별도로 4MiB BSS를 사용했으며, synthetic gate 비용이 낮아진 것을 E2E 개선으로 해석하지 않았다.

| 구현 | 바꾼 점 | 확인한 결과 |
|---|---|---|
| 과거 Dense | BB·직접 call target을 많은 dominator에 삽입 | 98,661–136,557개 힌트, 코드 +90–131%; 미스 감소에도 전체 CPU +11.9%, 평균 +14.4% |
| v1 | 함수/그룹 예산, inline RDTSCP 시간 검사 | 12,649–15,311개; peak 정책 CPU +0.76%, 평균 -0.50% 탐색 결과로 탈락 |
| v2 | shared `preserve_all` gate, 실제 BB head, 불필요한 call-continuation 분리 제거 | 12,262–14,868개, 코드 +4.8–6.3%; IT0 탐색 CPU -1.07%, 평균 -1.52%였으나 후속에서 재현되지 않음 |
| v3 | RDPID/RDTSC, epoch memo, 실제 명령 삭제, miss 함수 profile | profile은 1,101–1,156개, 코드 +0.47–0.58%; 22회 탐색에서 전체 기준 통과 후보 없음 |
| v4 one-site | 함수당 최대 한 지점, 최소 64 IR lead | 305–324개, 코드 +0.160–0.197% |
| v4 ungated | 위 profile·예산에서 gate/outline/window/runtime 제거 | 325–349개, 코드 +0.100–0.123%; 독립 확인 대상 |
| v4 callee | hot 함수 entry를 다른 caller에서도 미리 가져오는 직접 callee allowlist | 671–751개, 모두 직접 IT0, 코드 +0.501–0.657% |
| v5 callee ungated | callee allowlist·예산을 유지하고 gate/outline/window/runtime 제거 | 별도 최종 탐색 표와 audit 참조; 독립 확인으로 승격하지 않음 |

v2의 약 1% 개선은 **두 block의 탐색 수치**다. v3 재측정에서 reference IT0의 CPU/평균 절감은 -0.412%/-0.335%였고, profile은 -1.072%/+0.029%였다. v2와 v3를 합쳐 이득을 주장하지 않는다. v4에서도 ungated의 탐색 CPU 절감 -0.227%, 평균 +0.462%, p99 +1.027%였으므로 모든 endpoint가 좋아졌다고 해석하지 않았다.

compact 구현은 단순히 NOP로 메우지 않고 실제 힌트를 삭제했다. 최종 주소가 바뀌면서 같은 그룹의 target cache line 커버리지가 깨지면 복원하여 재빌드했고 논리 힌트 2945개를 제거했다. LLVM 기계어 복제는 inline assembly UID로 구분한다. 실패한 배치·빌드는 원인과 해시를 남긴 뒤 제거했다.

profile은 과거 미스 라인에서 만든 416개 함수의 union이다. 함수 경계가 모호한 64B 라인이 많으므로 “미스 80%를 커버”한다고 해석하지 않는다. callee 정책은 프로파일에 있는 **main executable 정의**만 직접 주소로 바꿨고 원본에도 같은 정의가 있는지 검증했다. 이 선언 변경에 따른 일반 call 코드 생성도 NOP 대조군에 포함된다. Outlining 제거는 최종 배치도 바꿀 수 있어 v4/v5를 기계어가 동일한 gate-only 실험으로 부르지 않는다.

## 10–20µs에 맞춘 방식과 커널 역할

커널 모듈은 incoming task가 결정된 `sched_switch`에서 CPU별 TSC와 구간 경계를 기록한다. **실제 prefetch 명령은 실행 중인 사용자 코드의 CFG 지점에서 발행한다.** 디스크 swap-in/page-in 훅이나 주기적인 커널 prefetch 타이머를 새로 넣은 구현은 아니다. 과거의 커널 2/4µs 파형 실험은 [별도 보고](class_b_e2e_distributed_20260927.md)에 있다.

v1/v2에서는 [10,20)µs에 모든 정적 그룹이 eligible이고 앞뒤로 일부 그룹만 열리도록 했다. v4 gated 정책은 miss의 관측 시점보다 앞서 발행하도록 최대 그룹 구간을 [5,15), 나머지를 [3,17) 및 [1,20)으로 앞당겼다. 실행 경로가 해당 dominator를 지나야 발행하므로 고정 µs 간격으로 issue queue에 넣는 구현은 아니다. IR instruction 거리도 실제 µs fetch lead를 보장하지 않는다.

이전 10–20µs peak는 600 RPS 부하에서 **PEBS retirement timestamp**로 관찰한 값이다. fetch가 실제로 시작된 시각과 다르고, scheduler 잔여 경로·kernel 복귀 시간도 나이에 포함된다. 새로운 C4 진단은 별도 표에 제시하며 부하가 다른 과거 분포를 그대로 현재 분포로 간주하지 않는다. RDPID/RDTSC gate는 migration/preemption 경계에서 best-effort이므로 정확한 wall-clock 발행 보장은 없다.

## MPKI가 높아도 E2E 개선이 작은 이유

1. **삽입 자체의 비용이 관찰됐다.** v2 NOP 대조군만으로 대상 서비스 instruction/request가 약 11–17%, user cycles/request가 약 10–14% 증가했다. v4 callee는 이를 줄였지만 원본 대비 명령어가 여전히 약 3–5% 많았다. v5는 이 관측에 따라 시간 검사 비용까지 제거하는 후속 실험이다.
2. **미스 이벤트마다 모집단이 다르다.** v4 callee IT0에서 retired L2-miss instructions/request는 원본보다 약 6–8% 적었지만 speculative L2 instruction-fetch miss/request가 일관되게 감소하지 않았다. 자신의 NOP 대비 retired 이벤트 감소는 서비스별 약 0.6–3.6%였다. 코드 배치만으로 생긴 차이도 있으므로 모두 prefetch의 효과로 돌리지 않는다.
3. **현재 MPKI는 항상 80 이상이 아니다.** v4 C4 원본 MovieId/ComposeReview/Rating의 L2I MPKI는 약 61.2/39.6/53.7이고, 독립 C16 원본의 별도 PMU 창에서는 약 52.2/35.9/43.1이었다. 높은 MPKI는 miss penalty가 직렬로 모두 critical path에 노출된다는 뜻이 아니다. 메모리 수준 병렬성이나 추측 fetch 기여분을 이 실험만으로 분리하지 않았다.
4. **전체 요청 CPU의 구성도 다르다.** v4 첫 원본 실행에서 세 대상 서비스의 전체 CPU는 전체 스택의 약 30.9%, user CPU는 약 10.6%였다. 나머지 서비스·커널·통신 비용도 존재한다. 이 비중은 지연 개선의 엄격한 상한이 아니지만, 수정한 사용자 코드의 미스 감소를 전체 CPU 절감과 동일시할 수 없는 이유다.
5. **TLB와 branch는 단일 원인으로 확정되지 않았다.** 별도 PMU에서 ITLB walk-active는 약 9–12% user cycles였다. 이것이 전부 노출된 stall이거나 code miss의 원인이라는 뜻은 아니다. 과거 LBR에서는 miss IP 자체가 branch인 비율이 약 3–7%였지만, taken target 뒤 64B 이내인 비율은 94–97%였다(ordinary 표본도 86–89%). nearest-target 분류에는 direct call 46–48%, indirect call 19–24%가 많았다. **BTB 부재나 FDIP 실패를 직접 측정한 결과는 아니다.**

`L2I`는 speculative instruction fetch도 포함할 수 있는 L2 miss 이벤트, `FE_L2`는 retired instruction에 연결된 frontend 이벤트다. 둘을 합해 원인 비율로 만들지 않는다. `ITLB_WALK`는 완료된 page walk 수이며 `ITLB_WALK_ACTIVE`는 walker가 바쁜 cycle이다. 일반 `SWPF_HIT/MISS`와 `T1_T2_ISSUED`는 IT0 발행 수가 아니다. `FE_LATE_SWPF`는 prefetch가 진행 중일 때 demand I-cache miss가 발생한 경우이며 전체 발행 수나 성공률이 아니다. 공유 selector MSR을 사용하는 이벤트는 별도 창에서 측정했다. PMU는 8초 창, 요청 수는 startup/teardown을 둘러싼 약 8.14초 구간이므로 작은 차이에 과도한 정밀도를 부여하지 않는다.

baseline 변동은 지표별로 다르다. v3 원본 CPU CV는 1.63%, v4의 두 원본 실행에서는 0.242%였고 v4 평균 지연 CV는 1.878%였다. v4 전체 16회의 관측에서는 Nginx 네 worker의 CPU 편중 정도와 Nginx CPU/request가 연관됐으나, 여러 arm이 섞였고 worker ticks는 시작·warmup도 포함한다. 이를 인과관계나 성능 보정에 사용하지 않았으며 불리한 실행을 제외하지 않았다.

명령·PMU 의미는 [Intel ISA reference](https://cdrdv2-public.intel.com/774990/architecture-instruction-set-extensions-programming-reference.pdf), [Granite Rapids events](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)를 따랐다. 코드 생성 관련 문서는 [Clang preserve_all](https://clang.llvm.org/docs/AttributeReference.html#preserve-all), [LLVM inline assembly](https://www.llvm.org/docs/LangRef.html#inline-assembler-expressions)다.

## 재현 자료와 검증

| 구현 | Git 기록 |
|---|---|
| 삽입 예산·짧은 lead 제거, 커널 시간 구간 | [75846fb](https://github.com/skyp0714/prefetchit/commit/75846fb), [d572d39](https://github.com/skyp0714/prefetchit/commit/d572d39) |
| 공용 gate와 원래 BB target 보존 | [4b08dc7](https://github.com/skyp0714/prefetchit/commit/4b08dc7) |
| 낮은 비용의 시각 확인·epoch memo | [e7092b9](https://github.com/skyp0714/prefetchit/commit/e7092b9) |
| 실제 중복 삭제·최종 line 커버리지, 복제 위치 식별 | [7e70342](https://github.com/skyp0714/prefetchit/commit/7e70342), [f3a1d30](https://github.com/skyp0714/prefetchit/commit/f3a1d30) |
| miss 함수 profile, sparse·static callee | [c487afa](https://github.com/skyp0714/prefetchit/commit/c487afa), [594e63a](https://github.com/skyp0714/prefetchit/commit/594e63a) |
| gate 없는 callee 후속 정책 | [bce566b](https://github.com/skyp0714/prefetchit/commit/bce566b) |
| gate 카운터·분리 진단·IP 집계 보존 | [e6320b3](https://github.com/skyp0714/prefetchit/commit/e6320b3), [213f6f0](https://github.com/skyp0714/prefetchit/commit/213f6f0), [febd959](https://github.com/skyp0714/prefetchit/commit/febd959) |

로컬 결과는 `/storage/prefetchit/class_b_lean_20260928`, Git의 compact 결과는 [`llvm_prefetchit/migration/evidence/class_b_lean_20260928`](../llvm_prefetchit/migration/evidence/class_b_lean_20260928)다. 원본 결과, seed/순서/arm 설정, 빌드 소스 해시, 명령, 최종 주소 patch map, 실패 이유, 바이너리 해시, 정리 내역을 보존했다. ELF와 원본 trace는 Git에 넣지 않는다. 계측한 raw trace는 전체 IP/나이별 compact 집계와 symbol 범위를 추출·보존한 뒤 정리했다.

compiler/runtime 관련 37개 검사와 실제 Media ELF의 instruction boundary·main binding·동일 배치 NOP/IT0 검증을 통과했다. 이후 timeline/정규화/보존 관련 18개 검사를 통과했다. 두 검사 집합은 일부 겹치므로 55개의 독립 검사를 수행했다고 세지 않는다. profiling 결과를 E2E timing에 섞지 않았고, 각 완료 실행에서 platform/module/scheduler 복구를 검증했다.

실패·탈락·대체된 ELF, object, build tree는 필요한 기록을 남긴 후 즉시 정리했다. 최종 보존 목록과 삭제 bytes는 `artifact_retention.json` 및 각 `*_cleanup.json`에 있다. 원본 benchmark/input/package/shared dependency는 유지했으며 이번 캠페인에서는 NAS 전송을 사용하지 않았다.


최종 보존 상태: v4 독립 확인 reference 없음, v5 미확인 탐색 reference 없음. 원본 세 바이너리와 현재 compiler plugin·ABI2 module은 재현용으로 보존했다. 서비스는 정지했고 module은 해제했다.
