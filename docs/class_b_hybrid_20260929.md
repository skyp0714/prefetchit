# Type B: split-instruction 주소 수정과 switch 직후 IT0/T1 혼합

75% 경로 커버리지 정책의 **24회·4-block 비교를 완료**했다. 가장 작은 call256의 처리량은 원본 대비 **1.01473× [1.00592, 1.02362]**였다. 더 넓은 wide75는 MongoDB retired L2 이벤트를 약 절반 줄였지만, 처리량 개선은 아직 불확실하다. 아래 구간은 개별 paired-log t95이며 다중비교 보정은 없다. 성능에 따라 제외한 실행은 없다.

| 정책 / 원본 | 처리량 speedup [95% CI] | 평균 지연 절감 | p99 절감 | 전체 CPU/request 절감 |
|---|---:|---:|---:|---:|
| call256 | 1.01473× [1.00592, 1.02362] | 1.493% | 0.390% | 1.287% |
| wide75 | 1.01023× [0.96581, 1.05670] | 1.039% | 0.323% | 1.892% |
| cost75 | 1.00082× [0.99074, 1.01102] | 0.087% | 0.690% | 1.351% |

원본은 1,180.79 RPS, 평균 3.317ms, p99 5.829ms, 전체 CPU 5,901.79µs/request, CPU 풀 사용률 85.96%였다. Full Media compose-review C4, workload CPU 8개, MovieId를 포함한 전체 스택이다. 최대 처리량 측정이나 DSB 모든 API 검증은 아니다. 각 실행은 새 초기 데이터와 50초 warmup, 60초 clean ROI를 사용했고 PMU는 그 뒤에 측정했다. 같은 시간 동안의 누적 쓰기 요청 수까지 동일한 것은 아니다.

| 정책 / 원본, MongoDB 3개 | retired L2/request 감소 | speculative L2 code-read miss 감소 | I-cache data stall 감소 |
|---|---:|---:|---:|
| call256 | 33.10% | 5.52% | 11.39% |
| wide75 | 50.11% | 7.31% | 17.08% |
| cost75 | 48.90% | 7.17% | 16.38% |

서로 다른 PMU 모집단이다. Retired L2 이벤트 절반 감소를 speculative code-read miss 절반 감소로 표현하지 않는다. 서비스별 PMU 합계는 별도 창을 각각 완료 요청 수로 정규화한 값이다.

![CPU 비용과 처리량](figures/class_b_mechanism_20260929_coverage75_cpu_attribution.png)

cost75의 MongoDB CPU/request는 1,238.10→1,156.61µs로 약 6.58% 줄었다. 이 서비스들의 CPU 절감이 전체 요청의 같은 비율 절감을 뜻하지 않는다. 원본 Native-3와 Mongo-3 사용자 CPU 합계는 전체의 29.57%이며, 이 역시 모든 사용자 작업을 포함하므로 code-miss 대기 비중이나 달성 가능한 speedup 상한이 아니다.

wide75와 cost75는 자신의 NOP 배치 대비 각각 처리량 1.03511×, 1.02553×였다. NOP 배치 자체의 점프·코드 비용을 함께 봐야 한다. 초기 C4 클라이언트의 네 persistent connection이 Nginx worker에 3/1/0/0 등으로 배정되는 경우도 관측했다. 관측은 ROI 뒤의 스냅샷이므로 원인 전체를 입증하지 않는다. 후속 비교에서는 같은 네 worker에 한 연결씩 배정하고, 연결 재생성이 발생하면 운영 오류로 기록한다. 기존 결과와 합쳐 계산하지 않는다.

## 남은 미스의 주소가 가리키는 줄

cost75 잔여 표본을 명령어 길이와 대조했다. 두 review MongoDB의 main-image 표본 중 **52.82%, 53.19%**가 64바이트 경계를 넘는 명령어였다. 원본 heldout에서는 **23.16%, 23.46%**였다. ReviewStorage는 잔여 43.98%, 원본 23.41%였다. 비중 상승 자체는 이미 줄어든 다른 미스 때문일 수 있으므로 절대적인 증가로 부르지 않는다.

UserReview 잔여 split 표본 21,217개 중 15,276개는 시작 줄만 선택돼 있고 뒷줄은 선택되지 않았다. MovieReview는 21,074개 중 15,203개다. 선택한 주소 줄에 남은 미스를 전부 늦거나 무시된 힌트로 해석할 수 없다는 뜻이다. 전역 선택 목록에 있다는 사실이 해당 실행에서 힌트가 발행됐다는 증거도 아니다.

독립적인 native probe에서 길이 10바이트 MOVABS를 줄의 offset 61에 놓고 **뒷줄만 CLFLUSH**했다. NOP / 앞줄 T1 / 뒷줄 T1 / 둘 다 T1은 동일한 주소와 14바이트 슬롯을 사용한다. 두 힌트 슬롯 밖의 `.text`가 같은지 검증했고, 매 반복 반환 값도 검사했다.

| Probe 조건 | retired L2 / 반복, 3회 평균 | PEBS split 시작 IP 표본, 별도 250k 반복 |
|---|---:|---:|
| NOP | 1.00328 | 972 |
| 앞줄 T1 | 1.00329 | 972 |
| 뒷줄 T1 | 0.00348 | 0 |
| 두 줄 T1 | 0.00400 | 0 |

**뒷줄이 빠져도 PEBS IP는 앞줄의 명령어 시작을 기록할 수 있음**을 확인했다. 시작 주소만 줄로 내림해 학습하면 잘못된 줄을 가져올 수 있다. 이 probe는 서비스 속도 향상이 아니며, 모든 서비스 split 표본에서 뒷줄만 미스였다는 증거도 아니다. 실제 대기와 E2E는 후속 비교로 검증한다. Raw trace와 임시 실행 파일은 표본 히스토그램·명령·소스·해시를 남긴 뒤 정리했다.

## 주소만 바꾼 후보

`cost75_split`은 기존 747개 call 위치, 1,528개 힌트, 원래 코드·stub 주소를 고정한다. Train 표본에서 split 명령어는 뒷줄의 다음 실제 명령어 시작을 타깃으로 삼고, 기존 stub의 슬롯 수 안에서 타깃을 다시 배정했다. **783개 힌트의 변위만 변경, 추가 명령어 0바이트**다. 모든 변경을 되돌리면 원래 cost75와 byte-for-byte 일치하며, 힌트를 NOP로 바꾸면 이미 측정한 NOP twin의 SHA-256과 일치한다.

같은 heldout을 뒷줄 기준으로 다시 평가하면 기존의 74.35% 커버리지는 **58.85%**였다. 주소만 교체한 후보는 **60.91%**다. 이는 뒷줄 모델에 따른 관측 경로 커버리지이며 실제 미스 감소율은 아니다. 기존 위치를 유지하는 제한 때문에 재배치 여지도 남아 있다. Heldout·E2E로 타깃을 선택하지 않았다. 바이너리 검증은 통과했으며 서비스 측정은 별도로 진행한다.

## Switch 직후 IT0, 그 뒤 T1

커널의 기존 scheduler-clock 모듈이 **다음 CPU 실행 태스크가 선택된 시각**을 공유한다. 사용자 코드가 새 epoch를 0–10µs 안에 처음 관측한 계측 call에서 최대 8개 IT0를 발행하고, 나머지 호출에는 T1을 사용한다. 커널에서 physical alias에 IT0를 실행하는 구현이 아니다. IT0는 사용자 주소의 RIP-relative 명령으로 실행한다. 첫 계측 call이 첫 사용자 명령어와 같지는 않으며, migration/preemption에 따른 누락·중복 가능성이 있다.

후속 hybrid는 위의 corrected T1 주소를 기준으로 한다. Burst 확장 타깃도 train-only이며 split 명령어의 뒷줄을 반영한다. 초반도 T1인 같은 배치 대조군, all-NOP 대조군, 무조건 T1 기준을 함께 비교한다. 별도 진단에서 초기 burst를 담당하는 최대 64개 stub group만 골라 gate 검사를 줄인 정책도 검증한다. 진단용 카운터가 들어간 실행 파일을 E2E에 사용하지 않는다.

PIE/일반 ELF, full/sparse gate의 인자·플래그·반환 주소, 예외 unwind, opcode 검사 **8개가 통과**했다. LD_PRELOAD 매핑 shim은 경고 없는 빌드와 일반 실행 파일 passthrough를 통과했다. 실제 서비스의 모듈 매핑·burst 시각과 E2E 결과는 진행 중이며, 이 native 검사만으로 구현의 성능을 주장하지 않는다.

"Fetch queue가 완전히 비어야 IT0가 동작한다"는 조건은 아직 가설이다. Intel [ISA 명세](https://cdrdv2-public.intel.com/819680/architecture-instruction-set-extensions-programming-reference.pdf)는 이를 보장하지 않는다. Queue 점유도를 직접 측정한 상태도 아니다. [Granite Rapids PMU 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)의 LATE_SWPF로 진행 중 instruction prefetch와 수요 미스가 겹친 경우를 보조 진단하되, 값이 0이라고 성공·무시·빈 queue 중 하나로 단정하지 않는다.

자료: [24회 전체 E2E·PMU 표](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/coverage75_completed/screen_report.md), [잔여 표본·명령어 경계 분석](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/coverage75_completed/residual_analysis.json), [자료·그림 해시](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/coverage75_completed/manifest.json), [compact 원자료 manifest](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/coverage75_completed/artifacts/manifest.json).
