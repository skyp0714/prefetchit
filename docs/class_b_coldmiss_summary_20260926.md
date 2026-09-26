# Class B: MovieId 외 cold-miss prefetch 적용 결과

두 애플리케이션의 네 서비스에 baseline Intel PT에서 학습한 wake-stream 계획을 정적으로 삽입했다. 같은 애플리케이션의 서비스들을 독립 애플리케이션 수로 세지 않는다. MovieId 전용 소스 지점 없이 각 서비스의 run 시작 프레임·함수 진입·post-call 위치와 prefetch 대상을 다시 선택했다.

**주 지표: 고정 요청률에서 타깃 서비스의 전체 user+kernel CPU/완료 요청 절감률.** 아래 구간은 paired log ratio의 개별95% t CI다. 최대 처리량 증가율이 아니다.

| 서비스 | tracing | RPS | 단독→공유 L2 code MPKI | 원본 대비 CPU 절감 [95% CI] | NOP 대비 [95% CI] | 단계 / 판정 |
|---|---:|---:|---:|---:|---:|---|
| Media ComposeReview | 100% | 600 | 2.48→43.35 | +1.35% [+1.04, +1.67] | +1.20% [+0.93, +1.46] | 독립 확인·채택, n=7 |
| Media Rating | 100% | 600 | 0.64→55.84 | +0.78% [-0.43, +1.97] | +1.75% [+0.84, +2.66] | 독립 확인·기준 미충족, n=7 |
| Social ComposePost | 10% | 600 | 1.20→28.35 | +1.07% [+0.81, +1.32] | +1.29% [+0.90, +1.68] | 독립 확인·채택, n=7 |
| Social UserTimeline | 10% | 600 | 0.07→51.81 | +1.41% [+1.04, +1.78] | +1.54% [+1.00, +2.07] | 독립 확인·채택, n=7 |
| Media ComposeReview | 10% | 300 | 2.35→49.14 | +0.97% [+0.35, +1.59] | +1.18% [+0.53, +1.82] | 탐색·승격 기준 미충족, n=3 |
| Media Rating | 10% | 300 | 0.60→65.05 | +0.67% [+0.14, +1.21] | +1.29% [+1.04, +1.53] | 독립 확인·기준 미충족, n=7 |

탐색은3쌍, 통과 후보는 새 seed의 독립7쌍으로 확인했다. 평균 CPU 절감≥1%를 원본과 NOP 양쪽에서 요구하고, 최종 채택에는 두 CI 하한>0도 요구했다. 탐색과 확인은 합치지 않았다. 평균이1% 미만이라도 CI가 양수인 결과를 “이득 없음”으로 바꾸지 않는다. 여러 서비스·후보 전체에 대한 다중비교 보정은 적용하지 않았다.

| 서비스 / tracing | 선택 lead | user cycles/요청 절감 | L2 code miss/요청 절감 | 전체 스택 CPU/요청 절감 |
|---|---:|---:|---:|---:|
| Media ComposeReview / 100% | wake8 | +4.04% | +8.13% | +0.47% |
| Media Rating / 100% | wake16 | +3.17% | +3.93% | +0.25% |
| Social ComposePost / 10% | wake16 | +3.09% | +8.74% | +0.24% |
| Social UserTimeline / 10% | wake16 | +2.08% | +3.17% | +0.13% |
| Media ComposeReview / 10% | wake8 | +4.14% | +7.20% | +0.16% |
| Media Rating / 10% | wake16 | +2.89% | +6.10% | -0.14% |

보조 지표: user cycles와 miss는 탐색3쌍의 별도 PMU 구간이다. 전체 스택 CPU는 위 주 결과와 같은 단계의 기술통계이며 별도의 성공 판정이나 최대 처리량 측정이 아니다.

핵심 결과는 같은 trace 기반 정적 삽입 절차가 다른 서비스와 SocialNetwork에도 적용된다는 점이다. 높은 공유 MPKI와 miss 감소만으로 전체 CPU 이득을 보장하지 않으므로 원본과 동일 배치 NOP를 모두 비교해야 한다. kernel CPU와 타깃 외 서비스 비용이 남기 때문에 user cycles 절감률을 애플리케이션 전체의 개선율로 보고하지 않는다.

운영 조건은8코어 공유, 고정2GHz/C6 off, 원본 데이터와 전체 서비스 스택, info 로그, tracing 유지다. 첫50초 워밍업 오류는 별도 기록하고 이후 오류·drop0건, 요청률±4%, p99<100ms를 요구했다. 각 arm은 새 프로세스·초기 데이터로 시작한다.

Media100%는600RPS, Media10%는 동일 선별 규칙으로 선택된300RPS다. 요청률이 달라 두 개선 폭의 차이를 tracing 비율만의 인과 효과로 해석하지 않는다. 기존에 제외한 qualification 표본은 재분류하지 않았다.

실패·탈락 실행 파일과 생성 DB/decoded trace는 결과·계획·해시를 남기고 정리했다. 확인된 바이너리와 참조본은 측정 종료 후20MiB/s 단일 rsync 및 제한된 순차 SHA-256 검증으로 NAS에 보관한다.

상세: [주 캠페인](class_b_extension_results_20260926.md), [Media10%](class_b_extension_results_20260926_sampling10.md), [방법과 운영 기록](class_b_extension_20260926.md).

[공개 스킴 소스](../llvm_prefetchit/migration/schemes/class_b_extension_20260926/README.md) · [기계 판독 요약](../llvm_prefetchit/migration/evidence/class_b_extension_20260926/consolidated.json).
