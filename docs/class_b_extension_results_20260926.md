# Class B 확장 결과

MovieId의 trace 기반 wake-stream을 다른 서비스에 적용한 결과다. Media와 SocialNetwork는 서로 다른 두 애플리케이션이며, 같은 애플리케이션 내 서비스 수를 독립 workload 성공 수로 세지 않는다. 표의 주 지표는 고정 요청률에서 타깃 서비스의 user+kernel CPU/완료 요청 절감률이다. 애플리케이션 전체의 최대 처리량 증가율은 측정하지 않았다.

Tracing 조건: Media native/nginx 100% (upstream const1); SocialNetwork native/nginx 10%. 100% Media 결과와 10%에서 새로 학습한 결과는 별도로 보고한다.

| 애플리케이션 / 서비스 | 정상 RPS | 단독→공유 L2 code MPKI | 비교 결과 |
|---|---:|---:|---|
| media / compose | 600 | 2.48 → 43.35 | 독립 확인 채택 기준 통과. wake8: base 대비 +1.35% [+1.04, +1.67] (n=7), wake8_nop 대비 +1.20% [+0.93, +1.46] (n=7) |
| media / rating | 600 | 0.64 → 55.84 | 독립 확인 채택 기준 미충족. wake16: base 대비 +0.78% [-0.43, +1.97] (n=7), wake16_nop 대비 +1.75% [+0.84, +2.66] (n=7) |
| social / composepost | 600 | 1.20 → 28.35 | 독립 확인 채택 기준 통과. wake16: base 대비 +1.07% [+0.81, +1.32] (n=7), wake16_nop 대비 +1.29% [+0.90, +1.68] (n=7) |
| social / usertimeline | 600 | 0.07 → 51.81 | 독립 확인 채택 기준 통과. wake16: base 대비 +1.41% [+1.04, +1.78] (n=7), wake16_nop 대비 +1.54% [+1.00, +2.07] (n=7) |

CPU 절감률은 paired log ratio와 개별95% t 신뢰구간으로 계산했다. 탐색3쌍과 독립 확인7쌍을 합치지 않으며, 여러 후보 전체에 대한 다중비교 보정은 적용하지 않았다. NOP는 삽입 명령을 동일 길이로 치환한다.

8코어 공유, 고정2GHz, C6 off, 완전한 서비스 스택 및 표준 입력을 사용했다. 매 arm은 새 프로세스·초기 데이터에서 시작한다. 첫50초 워밍업의 오류도 보존하고 보고하며, 그 이후 오류·drop은0건을 요구한다. 초기 Media qualification에서 제외한 표본은 재분류하지 않았다.

Intel PT의 run별 첫 접근 순서는 실제 miss oracle가 아니다. 이번 정책은 service object 진입 및 post-call 사이트에 삽입하며, dependency archive 내부까지 삽입했던 기존 MovieId 결과와 coverage가 다르다. 기존 MovieId +5.4%는 user cycles/request 기준이므로 여기의 전체 CPU/요청 절감률과 직접 비교하지 않는다.

방법·진행 기록: [class_b_extension_20260926.md](class_b_extension_20260926.md). 실패 바이너리·생성 DB·decoded trace는 결과·해시·소스·계획을 남기고 정리한다.

원본·PF·NOP 타깃 모두 동일한 fat-static 재빌드 및 info 로그 설정을 사용했다. 수치는 이 링크 설정에서의 삽입 효과다.

독립 확인은 탐색과 동일한 워밍업50초 및 순수 CPU 측정30초를 사용하고, 이후 PMU 수집만 생략하여 부하를95초에 종료한다. 확인은7쌍을 그대로 유지하며, user cycles·miss·top-down은 탐색3회의 별도 PMU 구간에서 보고한다. 확인 단계의 PMU 값은 추정하거나 보간하지 않는다.
