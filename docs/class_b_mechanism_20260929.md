# Type B: 발행 동작, 선행 경로, 중복 힌트를 분리한 실험

후속 20회 fresh-stack 검증에서, 타깃을 바꾼 T1의 처리량은 원본 대비 **1.0055× [0.9893, 1.0219]**, 동일 배치 NOP 대비 **1.0026× [0.9889, 1.0165]**다. E2E 향상은 아직 확정하지 않는다. 원본 대비 retired L2 frontend event/request는 **28.84%**, I-cache data-stall/request는 **11.01%** 줄었다. 더 낮은 이득 문턱으로 타깃을 넓힌 정책은 retired L2를 **30.65%** 줄였지만 처리량은 **1.0032×**였다. 코드 미스 감소를 요청 성능 개선으로 대신 보고하지 않는다.

긴 동일 프로세스 교차 실험에서는 리뷰 데이터 누적으로 동일 NOP의 처리량이 12.7% 낮아졌다. 이 방식의 E2E 수치는 정책 효과 판정에서 제외하고, 초기 데이터 상태와 측정 시점을 맞춘 새 스택 비교로 전환했다. 아래 완료된 탐색과 후속 검증의 표본을 합치지 않는다.

**E2E 먼저: 후속 4-block 검증**

| 정책 / 원본 비교 | 처리량 speedup [개별 95% CI] | 평균 지연 절감 | p99 절감 | 전체 CPU/request 절감 |
|---|---:|---:|---:|---:|
| Retarget T1 | 1.0055× [0.9893, 1.0219] | +0.560% | +0.289% | +0.451% |
| 나이 구간 보존 thinning | 1.0032× [0.9852, 1.0215] | +0.321% | +0.400% | +0.609% |
| 최소 이득 2표본의 공격적 교체 | 1.0032× [0.9844, 1.0223] | +0.327% | +0.593% | +0.279% |

원본은 평균 1,163.77 RPS, 평균 3.367ms, p99 5.899ms, 전체 CPU/request 5,936.37µs, 풀 사용률 85.08%였다. Retarget는 각각 1,170.11 RPS, 3.348ms, 5.882ms, 5,909.61µs였다. 이 절대값은 실행별 산술평균이고, 표의 개선율은 seed별 paired-log 비율이다. 원본 RPS 범위는 1,154.18–1,183.04로 약 2.5% 폭이었다. 완료된 실행 20개 전부 정상이며 성능에 따라 제외한 실행은 없다.

모든 arm은 같은 초기 데이터와 warmup/ROI 시간으로 비교했다. 고정 시간의 closed-loop 실행이므로 실제 누적 요청 수까지 동일한 것은 아니다. 처리량·평균 지연도 독립적인 증거가 아니다.

![Fresh-stack 결과와 개별 95% 구간](figures/class_b_mechanism_20260929_fresh_confirmation.png)

| 정책 / 원본 비교 | retired L2/request 감소 [95% CI] | speculative L2 code miss 감소 | I-cache data stall 감소 | retired L1I 이벤트 변화 |
|---|---:|---:|---:|---:|
| Retarget T1 | 28.84% [26.58, 31.04] | 4.44% | 11.01% | 1.66% 증가 |
| 나이 구간 보존 thinning | 25.29% [24.24, 26.33] | 3.68% | 8.92% | 2.16% 증가 |
| 공격적 교체 | 30.65% [29.51, 31.76] | 6.45% | 10.75% | 2.20% 증가 |

같은 배치 NOP 대비 CPU/request 절감은 retarget −0.149%, thinning +0.010%, 공격적 교체 −0.321%였고, p99는 각각 1.40/1.29/1.09% 증가한 점 추정치였다. 셋 모두 고정한 후속 선택 조건(CPU 악화 없음, p99 증가 ≤1%, retired L2 감소 ≥20%)을 충족하지 않는다. Retarget는 기존 기전 대조 정책으로 유지하며 E2E 승자로 부르지 않는다. Thinning·공격적 교체의 결과·계획·패치·해시를 보존하고, 후속 측정에 쓰지 않는 ELF 6개 123,171,360바이트를 수집 구간 밖에서 정리했다. 다음 적용 범위는 별도 전체 스택 진단에서 확인한 MongoDB다.

별도 switch-age 진단 12개(원본/retarget × 서비스 3개 × 표본 주기 1,021/4,093)도 완료했다. loss/throttle 없이 모든 표본을 스케줄 구간에 연결했다. 원본의 retired L2 추정 이벤트 중 40.8–43.7%가 switch-in 후 10–20µs에 있었다. 이 구간의 이벤트/request 감소는 MovieId 약 36%, ComposeReview 24–26%, Rating 22–27%로 두 표본 주기에서 같은 방향이었다. 범위는 두 주기의 결과이며 신뢰구간이 아니다. 스케줄된 시간당 밀도 정점은 서비스·주기에 따라 8–10 또는 10–15µs였다. 따라서 모든 서비스가 정확히 같은 순간에 정점을 가진다고 보지 않는다.

이 나이는 커널 복귀·인터럽트 시간을 포함한 retirement 시각이다. 실제 fetch 시각이나 힌트 발행부터 fetch까지의 선행 시간으로 환산하지 않는다. 이 진단의 부하 지연도 E2E 표에 넣지 않는다.

![서비스별 switch-in 이후 미스 분포](figures/class_b_mechanism_20260929_wake_validation.png)

**앞선 2-block 탐색: 후속 검증과 합치지 않음**

| 단계 / 비교 | 처리량 speedup | 평균 지연 절감 | p99 절감 | 전체 CPU/request 절감 |
|---|---:|---:|---:|---:|
| 동일 타깃 T1 / 원본, opcode 탐색 | 1.0087× | +0.902% | +0.157% | +0.700% |
| 새 타깃 T1 / 원본, 별도 retarget 탐색 | 0.9938× | −0.638% | −1.075% | +0.606% |
| 새 타깃 T1 / 동일 배치 NOP | 1.0037× | +0.378% | −0.159% | +0.998% |
| 새 타깃 T1 / 기존 타깃 T1 | 1.0002× | +0.009% | −0.358% | +0.302% |

두 탐색은 각각 2개의 독립 seed block, 4개 arm, 총 8회의 fresh full-Media 실행이다. 개별 paired-log t95 구간이며 다중비교 보정은 없다. T1/원본 처리량 구간은 [0.9473, 1.0742]×, 새 타깃/원본은 [0.7692, 1.2839]×, 새 타깃/NOP는 [1.0002, 1.0071]×다. 두 반복만으로 좁은 구간 하나를 최종 승격 근거로 삼지 않는다. 원본 RPS도 1,194.4와 1,159.1로 달랐으며 어느 실행도 성능에 따라 제외하지 않았다.

원본은 계측되지 않은 기존 실행 파일이다. NOP는 힌트를 같은 길이의 NOP로 대체한 배치 대조군이다. T1, IT0 및 새 타깃은 이 배치에서 비교하므로 원본과 NOP 비교를 혼동하지 않는다. C4 closed-loop의 처리량과 평균 지연은 서로 연결되며, 이번 결과를 최대 처리량 측정으로 부르지 않는다.

**발행 종류가 실제 차이를 만들었다**

원래 위치와 타깃을 그대로 두고 한 바이트만 바꾼 T1은 원본 대비 retired L2 이벤트를 18.10%, I-cache data stall을 5.73% 줄였다. 같은 탐색의 IT0는 각각 3.74%, 1.04%였다. T1은 원본 T1 바이너리와 SHA-256이 완전히 일치하도록 역변환을 검사했다. 명령어 주소나 크기 변화로 설명되는 차이가 아니다.

CPU는 Xeon 6787P이며 PREFETCHI CPUID 비트가 켜져 있다. 실행 파일의 IT0/IT1은 64-bit RIP-relative 실제 명령어 경계에 있다. 따라서 'ISA 미지원' 또는 '모든 IT0가 무조건 NOP'라는 설명은 배제한다. 이 조건은 Intel의 [ISA 확장 명세](https://cdrdv2-public.intel.com/819680/architecture-instruction-set-extensions-programming-reference.pdf)와 확인했다.

네 실행 파일에서 같은 주소의 7바이트 힌트만 다르게 한 통제 실험을 3회 반복했다. 각 회 100,000번, target CLFLUSH 후 CPUID 직렬화, 64개의 의존 IMUL을 거친 target-call을 측정했다. 측정 값은 TSC tick이며 서비스 속도 향상이 아니다.

| 조건 / 힌트 | call TSC 평균 | retired L2 / iteration | L2 code-read miss / iteration | I-cache data stall / iteration |
|---|---:|---:|---:|---:|
| target만 flush / NOP | 200.24 | 1.003 | 1.044 | 283.83 |
| target만 flush / IT0 | 169.61 | 1.003 | 1.043 | 253.33 |
| target만 flush / T1 | 99.20 | 0.003 | 0.044 | 183.13 |
| target flush + 64 KiB code pad / NOP | 193.53 | 0.967 | 1.058 | 270.66 |
| target flush + 64 KiB code pad / IT0 | 74.44 | 0.008 | 1.058 | 13.34 |
| target flush + 64 KiB code pad / IT1 | 74.43 | 0.008 | 1.056 | 13.38 |
| target flush + 64 KiB code pad / T1 | 158.95 | 0.006 | 0.057 | 236.73 |

힌트 줄도 flush하면 IT0/IT1의 대기 감소가 커졌고, 8 KiB code pad에서는 64 KiB만큼의 효과가 나오지 않았다. 이는 힌트 코드의 프런트엔드 상주/재인출 상태에 민감하다는 증거다. 이 실험만으로 내부 DSB 구조 하나를 원인으로 확정하지 않는다. IMUL 개수나 retired LBR 나이를 실제 hint issue→fetch 지연으로 환산하지 않는다.

64 KiB 조건의 IT0는 target의 retired miss와 대기를 거의 없앴지만 `L2_RQSTS.CODE_RD_MISS`는 그대로였다. 따라서 이 speculative 카운터 감소율만으로 선행 인출의 성공 여부를 판단할 수 없다. 데이터용 SWPF 카운터는 IT0/IT1의 총 발행 수가 아니며, `LATE_SWPF`는 진행 중인 instruction prefetch와 겹친 수요 미스를 세는 별도 조건이다. 이벤트 정의는 [Intel Granite Rapids PMU 목록](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)을 따른다. 서로 다른 모집단을 빼서 wrong-path 비중을 만들지 않는다.

**명령어를 추가하지 않고 타깃 교체**

정확히 같은 배치의 NOP 실행에서 새 FE_L2 PEBS/LBR 표본 71,547개를 수집했다. loss/throttle은 없었다. 관측한 선행 직선 경로에 있는 기존 힌트 사이트를 사용하고, miss의 실제 분기 도착점 또는 명령어 경계를 타깃으로 삼았다. 64..1024 retired-cycle 나이 범위에서 기존 커버리지 손실을 차감한 이득이 8표본 이상인 교체를 탐욕적으로 선택했다.

| 서비스 | 바꾼 사이트 / 기존 사이트 | 해당 나이 범위의 학습 표본 커버리지, 이전→이후 |
|---|---:|---:|
| MovieId | 165 / 4,161 | 1,907→7,548 / 15,242 |
| ComposeReview | 189 / 4,524 | 4,412→13,200 / 28,515 |
| Rating | 130 / 3,922 | 1,299→6,253 / 16,849 |

추가 명령어와 실행 코드 증가분은 0이다. RIP 변위와 비할당 debug metadata만 바꿨다. 원래 사이트는 dominator 정책으로 만들어졌지만, 새 타깃을 모든 실행 경로에서 지배한다고 주장하지 않는다. 유한한 retired LBR에서 관측한 경로에 대한 학습이다. 학습 커버리지는 실제 miss 감소율이 아니다.

별도 두 block에서 합산 retired L2 감소율은 원본 대비 **29.03% [27.04, 30.97]**, NOP 대비 **31.35% [27.58, 34.92]**였다. I-cache data stall은 원본 대비 **11.80% [5.38, 17.78]** 줄었다. Speculative L2I는 **2.82% [−9.10, 13.43]**여서 큰 감소를 확인하지 못했다.

| 서비스 | 원본 frontend-bound | 기존 타깃 T1 | 새 타깃 T1 |
|---|---:|---:|---:|
| MovieId | 77.32% | 76.34% | 75.77% |
| ComposeReview | 75.22% | 74.34% | 74.09% |
| Rating | 75.84% | 75.16% | 74.66% |

합산 FE_L1/request는 원본 8,611.4, 새 타깃 8,795.0이고, FE_ITLB는 1,826.0→1,780.7이다. L2 개선만큼 L1I·translation 문제가 줄어든 상태가 아니다. 이 이벤트들은 겹칠 수 있으므로 합산해 전체 손실의 원인 비중을 계산하지 않는다. 간접 분기 오예측과 BTB/FDIP 내부 상태 역시 같은 뜻이 아니다.

**전체 요청에서 어느 부분을 줄이고 있는가**

retarget 탐색의 clean ROI에서 세 수정 서비스의 사용자 CPU/request는 631.97→609.63µs, 커널 CPU는 1,188.16→1,187.87µs였다. 사용자 CPU 약 22.34µs 절감은 전체 원본 비용 5,918.19µs의 약 0.38%다. 전체 CPU 변화에는 다른 서비스의 변동도 포함되며, 이 비율을 임계 경로 지연의 상한으로 해석하지 않는다.

별도 원본 진단에서 clean CPU 비용의 99.80%를 차지하는 20개 서비스를 골라 각각 두 PMU 창을 수집했다. 40개 창 모두 counter multiplexing 없이 측정됐다.

| 서비스 | 사용자 CPU/request, µs | 커널 CPU/request, µs | retired L2/request | L2 code-read miss/request |
|---|---:|---:|---:|---:|
| ComposeReview | 319.70 | 666.24 | 1,008.67 | 11,113.14 |
| MovieId | 155.40 | 294.65 | 501.01 | 5,800.52 |
| Rating | 160.62 | 227.80 | 501.35 | 5,466.17 |
| UserReview MongoDB | 475.06 | 48.27 | 2,316.38 | 25,909.31 |
| MovieReview MongoDB | 476.20 | 48.86 | 2,324.57 | 25,579.62 |
| Nginx | 425.94 | 121.27 | 1,419.31 | 14,016.52 |

두 review MongoDB의 retired L2 이벤트 합계는 수정한 세 네이티브 서비스 합계의 약 2.31배다. 각 PMU 창의 시각·요청 분모가 다르므로 전체 미스의 동시 점유율로 환산하지 않는다. 그래도 프리패치 적용 범위를 넓힐 근거가 된다. MongoDB는 별도 두 seed의 PEBS/LBR에서 실제 실행된 선행 NOP를 고르고, 기존 7–15바이트 NOP를 같은 길이의 RIP-relative T1으로 바꾸는 실험을 준비했다. 원본 소프트웨어 프리패치와 명령어 경계, ELF 크기는 유지한다. 모든 MongoDB 컨테이너에 같은 선택 ELF를 장착해 코드 페이지 공유를 유지하며, 원본 이미지·원본 ELF 복사본 대조군을 포함한다. 이 문단은 구현 설명이며 MongoDB 성능 결과가 아니다.

![전체 스택의 CPU와 코드 미스](figures/class_b_mechanism_20260929_whole_stack.png)

**다음 수정과 독립 검증**

추가 NOP 학습 73,063개 표본에서 0..8192-cycle 관측을 남겼다. 새 두 정책은 최소 나이 128 또는 512인 타깃을 선택하되, 기존 힌트의 짧은 선행 거리 커버리지까지 손실 비용에 넣었다. 한 사이트가 최근과 과거에 모두 나왔을 때 오래된 발생을 버리지 않는다. 앞선 정책과는 학습 자료·보호 조건도 다르므로 단순히 나이 하나만 바꾼 비교라고 부르지 않는다.

힌트 축소는 새 타깃 정책이 관측한 covered miss의 98%를 보존하는 작은 사이트 집합을 선택했다. MovieId 177, ComposeReview 230, Rating 142개를 남겼다. 나머지를 같은 크기의 NOP로 바꿔 **발행량** 효과를 측정한다. 실행 파일 크기나 retired instruction 수를 줄였다는 주장은 하지 않는다. 관측하지 못한 경로의 힌트도 빠질 수 있으므로 독립 측정으로 판정한다.

교차 검증은 실험 전용 NOP 프로세스의 검증된 힌트 슬롯만 바꾼다. 프로세스·inode·시작 시각·원래 명령어를 확인하고, 모든 스레드를 정지한 뒤 쓰기/읽기 검증, 필요시 rollback, 재개, 20초 warmup을 거친다. 초기 NOP 쓰기로 모든 arm이 같은 private code page를 사용한다. 실행 파일 자체는 바꾸지 않는다. 10개의 native/알고리즘 검증을 통과했고 실제 세 서비스의 초기 COW 검증도 통과했다.

교차 방식은 여섯 arm을 정순·역순으로 측정하고 각 구간 clean ROI 40초 이후 같은 길이의 PMU 창을 배치했다. 4개 fresh stack을 계획했으나 첫 stack의 12개 구간에서 심한 비정상성을 확인해 두 번째 stack 도중 중단했다. 동일 NOP의 RPS는 1,159.3→1,012.2, CPU/request는 5,933.5→6,832.7µs로 달라졌다. UserReview/MovieReview MongoDB CPU/request는 536.0→944.9 및 538.2→950.3µs였고, 수정한 세 서비스는 거의 변하지 않았다. 해당 서비스의 `$push`로 리뷰 배열이 누적되는 소스 동작과 부합한다. 정순·역순만으로 이 상태 변화를 통제했다고 간주하지 않는다.

두 ReviewHandler는 앞쪽에 리뷰를 추가한 뒤 projection 없이 `_new=true`로 변경된 문서를 받아 폐기한다. 이는 사용 중인 [MongoDB C driver 1.15의 API 정의](https://raw.githubusercontent.com/mongodb/mongo-c-driver/1.15.0/src/libmongoc/doc/mongoc_collection_find_and_modify.rst)와 일치한다. 프리패치 효과를 평가하기 위해 이 요청 의미나 데이터 구조를 바꾸지는 않았다.

완료된 구간과 두 번째 stack의 부분 자료를 모두 보존했다. 교차 E2E를 승자 선택·성능 확인에 사용하지 않고, 이미 별도 fresh-stack 탐색에서 측정한 retarget를 기전 대조 정책으로 유지했다. 이후 원본/NOP/retarget와 두 수정안을 새 스택에서 4 block씩 비교했다. 같은 입력, C4, warmup 50초 뒤 clean ROI 60초를 유지했다. 타깃 밖 CPU·PMU 진단도 별도로 수집했다.

후속 수정은 두 가지다. 첫째, 같은 miss에 대한 늦은 힌트가 이른 힌트를 대신하지 못하도록 0–63/64–127/128–511/512–2047/2048–8192 나이 구간마다 학습 커버리지 98%를 보존한다. 둘째, 기존 타깃 커버리지 손실은 계속 차감하면서 최소 교체 이득을 8→2표본으로 낮춰 더 많은 miss 타깃을 시험한다. 추가 명령어와 코드 증가는 없다. 두 정책은 별도 탐색 가설이며, 단순 thinning의 악화가 선행 거리 하나로 설명된다고 미리 확정하지 않는다.

**커널 위치 확인과 자료 보존**

기존 커널 코드는 `sched_switch`에서 선택된 next task의 mm에 속하는 실행 페이지를 등록 시 pin하고, 그 페이지의 kernel direct-map 별칭으로 prefetch한다. 전환 전 현재 CR3 때문에 다른 프로세스의 같은 사용자 VA를 읽는 구조가 아니다. optional `finish_task_switch` 및 주기 timer도 current tid/tgid/mm를 확인한다. 사용자 ITLB를 직접 데우거나 유효 타깃·충분한 선행 시간을 보장한다는 뜻은 아니다. 이번에는 소스·해시를 점검했으며 새 커널 성능 측정을 했다고 주장하지 않는다.

학습에 사용한 decoded trace와 임시 DSO 복사본은 compact 관측·품질·명령·해시·계획을 남긴 후 즉시 정리했다. native test 실행 파일과 대체된 초기 calibration 파일도 정리했다. 원본, 활성 정책, 대조군은 보존했다. NAS 전송은 하지 않았다.

교차 실험의 첫 준비 실행은 clean ROI 전에 PMU 순서 보정을 위해 중단했다. 이후 재시작 1회는 기존 wrapper의 10초 종료 유예가 컨테이너 정리를 끊어 시작 검사에서 차단됐다. 두 시도 모두 완료 clean ROI는 0이며 성능 자료를 보고 제외한 것이 아니다. 정확한 private compose manifest로 정리하고 72개 복구 비교를 확인했으며, 종료 유예를 90초로 고쳤다.

원자료는 `/storage/prefetchit/class_b_mechanism_20260928`에 있다. 구현은 opcode 교정, 타깃 교체, 기존 커버리지 보호/힌트 축소, 동일 프로세스 비교로 나누어 Git에 기록했다.

그림: [동일 주소 opcode 검증](figures/class_b_mechanism_20260929_calibration.png), [초기 탐색](figures/class_b_mechanism_20260929_service_effects.png), [교차 실험의 데이터 누적](figures/class_b_mechanism_20260929_write_state_drift.png). 각 PNG와 같은 이름의 SVG도 보존한다.

완료된 네이티브 검증의 [원자료 요약](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/confirmation_evaluation.json)과 [파일 해시 목록](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/completed_native_manifest.json)을 저장했다.

이후 native wake 12개까지 포함한 [완료 단계 압축 기록](../llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/completed_records/manifest.json)을 추가했다. 28개 묶음/파일의 해시와 7,988개 compact 기록을 검증했다. 진행 중인 backend/call-path 결과는 이 native-only 묶음에서 제외한다.
