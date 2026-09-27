# Class B: five-service policy and selected-next-task emission study

모든 절감률은 `(1 - candidate cost / control cost) × 100`이며, 양수가 개선이다. 주 지표는 완료된 외부 요청당 user+kernel CPU 비용이다. 고정 RPS 결과를 throughput 향상이나 응답시간 개선으로 바꾸어 해석하지 않는다.

## 확인 결과

새 정책의 baseline 대비 타깃 CPU 절감: movie **+1.26% [+0.73, +1.78]**, compose **+1.31% [+0.96, +1.67]**, rating **+2.09% [-0.04, +4.18]**, composepost **+1.06% [+0.67, +1.45]**, usertimeline **+1.45% [+0.83, +2.06]**.

커널 확인 후보 `usertimeline/b16`의 off 대비 타깃 CPU 절감은 **-0.46% [-1.02, +0.10]**다. 타깃과 풀 비용을 함께 보는 승격 기준: **미통과**.

이번 확인 실험에서 95% 하한까지 10% 절감을 입증한 정책은 없다. 탐색 최고값이나 다른 지표의 과거 이득을 더해 목표 달성으로 보고하지 않는다.

## 운영점과 방법

| Family | Shared cores | RPS | Baseline target L2 code MPKI |
|---|---:|---:|---|
| media | 8 | 600 | movie: 63.94, compose: 44.11, rating: 56.15 |
| social | 4 | 600 | composepost: 29.55, usertimeline: 55.99 |

운영점은 후보 성능을 보기 전에 baseline의 가족 내 기하평균 MPKI로 선택했다. Media tracing 100%, Social tracing 10%를 각 가족 내 모든 arm에 동일하게 유지했다. CPU는 2 GHz와 C6 off로 측정하고 매 실행 뒤 기존 상태로 복원했다. 공식 입력과 초기화 검증, 정상 RPS/오류/지연시간 gate를 통과한 결과만 비교했다.

## 사용자 공간 새 정책: 7개 독립 seed block

각 block은 새 전체 스택을 사용한다. Media 3개 또는 Social 2개를 동시에 교체한 bundle의 효과다. 대괄호는 개별 95% paired-log t 신뢰구간이며 다중 비교 보정은 하지 않았다. 개별 적용 screen과 마지막 PMU 1회는 이 신뢰구간에 합치지 않았다.

| Service | New vs baseline | New vs retained reference | New vs layout NOP | Target promotion |
|---|---:|---:|---:|---|
| movie | +1.26% [+0.73, +1.78] | +4.81% [+4.17, +5.44] | +1.25% [+0.84, +1.66] | yes |
| compose | +1.31% [+0.96, +1.67] | +0.37% [-0.03, +0.77] | +1.69% [+1.39, +1.98] | no |
| rating | +2.09% [-0.04, +4.18] | +1.15% [-0.01, +2.30] | +1.25% [+0.35, +2.15] | no |
| composepost | +1.06% [+0.67, +1.45] | +0.25% [-0.16, +0.67] | +1.58% [+1.13, +2.03] | no |
| usertimeline | +1.45% [+0.83, +2.06] | +0.10% [-0.46, +0.65] | +1.49% [+0.84, +2.14] | no |

MovieId의 retained reference는 이전 p11a 빌드이므로 artifact 비교다. 동일 소스에서 하나의 설정만 바꾼 비교로 해석하지 않는다. Rating의 이전 후보는 실패 후 삭제됐으므로 retained reference는 baseline이다. 새 정책과 NOP 쌍은 동일 코드 배치를 유지한다.

MovieId의 과거 p11a **약 5.1% 절감**은 당시 wsm baseline 대비 **user cycles/요청** (1.054× 효율, 5회 중앙값)이다. 이번의 baseline 대비 수치는 새 빌드의 **user+kernel CPU/요청** 7쌍 결과이며 분모와 baseline이 다르다. 이번 새 정책과 보존 p11a의 전체 CPU 비교는 위 retained-reference 열이다. 과거 5.1%와 이번 절감률을 합산하지 않는다. [기존 MovieId 결과](dsb_results_summary_20260926.md#movieid-별도-지표의-과거-결과).

| Family | Whole-stack CPU vs baseline | Whole-pool CPU vs baseline |
|---|---:|---:|
| media | +0.39% [-0.09, +0.86] | +0.50% [-0.16, +1.16] |
| social | +0.10% [-0.16, +0.35] | +0.19% [-0.11, +0.48] |

## 같은 7쌍의 user/kernel CPU 분해

MovieId의 과거 약 5% 결과에 대한 질문 후 동일 CPU 측정 구간을 사후 분해했다. 아래 user CPU는 cgroup의 사용자 CPU **시간/요청**이며 과거 PMU user **cycles/요청**과 구분한다. 승격 기준은 변경하지 않았고, 신뢰구간은 개별 95% 구간이다. 사용자 영역의 절감이 커도 전체 CPU에서 그 영역이 차지하는 비율과 커널 비용 변화에 따라 전체 절감률은 작아질 수 있다.

| Service | Baseline user CPU share | User CPU vs baseline | Kernel CPU vs baseline | User CPU vs retained artifact |
|---|---:|---:|---:|---:|
| movie | 35.29% | +4.88% [+3.31, +6.43] | -0.72% [-1.21, -0.23] | +11.34% [+9.30, +13.34] |
| compose | 33.66% | +4.24% [+2.67, +5.78] | -0.17% [-0.91, +0.57] | +1.30% [+0.33, +2.26] |
| rating | 40.25% | +3.03% [+1.20, +4.83] | +1.43% [-2.28, +5.00] | +2.53% [+1.46, +3.58] |
| composepost | 41.81% | +2.40% [+0.84, +3.93] | +0.10% [-1.04, +1.22] | +1.26% [-0.55, +3.03] |
| usertimeline | 65.37% | +3.22% [+1.25, +5.15] | -1.93% [-7.05, +2.94] | +0.77% [-1.16, +2.67] |

retained-artifact 열은 동일한 단일 설정만 바꾼 비교가 아니다. 특히 MovieId의 p11a는 다른 역사적 빌드다. 이 열의 큰 user CPU 절감을 정책 단독의 이득이나 전체 CPU 10% 목표 달성으로 해석하지 않는다.

## 트레이스의 시간 분리 검증

별도 시점의 검증 trace에서 다음 값을 계산했다. touch precision은 해당 전환 후 실제 실행된 코드 라인의 비율이며, cache miss 예측 정확도나 성공한 prefetch fill 비율이 아니다. 처음에는 오류가 하나라도 있는 capture batch를 전부 기각했다. 반복 오류를 진단한 뒤 서비스·시간 구간마다 3개 캡처 중 첫 무손실 캡처를 우선 선택했다. Rating에서 모두 실패할 때만 하나의 비동기 Redis I/O 스레드에 국한된 overflow를 ELF 심벌로 확인하고 해당 오류 캡처에서 그 스레드 전체를 제외하는 예외도 구현했다. __fdelt_chk와 __fdelt_warn의 동일 주소 별칭을 검증하며 다른 오류는 계속 기각한다. 이 변경은 후보 성능 측정 전에 고정했다. 아래 실제 선택 기록의 제외 목록이 비어 있으면 이 예외를 사용하지 않은 전체 스레드 캡처다. 실제 성능 측정은 항상 I/O 스레드를 포함한 전체 프로세스/스택/풀을 그대로 집계한다. [Linux 6.8 PT documentation](https://github.com/torvalds/linux/blob/v6.8/tools/perf/Documentation/perf-intel-pt.txt).

| Service | Policy | Matched / admitted validation runs | Touch precision | Admitted first-touch coverage |
|---|---|---:|---:|---:|
| movie | strict/32 | 976 / 1037 | 97.82% | 5.70% |
| movie | wide/64 | 976 / 1037 | 66.80% | 12.66% |
| compose | strict/32 | 3606 / 3660 | 99.35% | 3.73% |
| compose | wide/64 | 3606 / 3660 | 65.13% | 13.21% |
| rating | strict/32 | 1735 / 1789 | 96.39% | 10.71% |
| rating | wide/64 | 1735 / 1789 | 64.33% | 16.06% |
| composepost | strict/32 | 1389 / 1460 | 94.83% | 5.53% |
| composepost | wide/64 | 1399 / 1460 | 82.12% | 9.45% |
| usertimeline | strict/32 | 350 / 392 | 99.69% | 2.13% |
| usertimeline | wide/64 | 378 / 392 | 80.04% | 6.38% |

| Service | Phase | Selected capture | Excluded TIDs |
|---|---|---|---|
| movie | training | training_0 | [] |
| compose | training | training_0 | [] |
| rating | training | training_0 | [] |
| movie | validation | validation_0 | [] |
| compose | validation | validation_0 | [] |
| rating | validation | validation_0 | [] |
| composepost | training | training_1 | [] |
| usertimeline | training | training_0 | [] |
| composepost | validation | validation_0 | [] |
| usertimeline | validation | validation_1 | [] |

## 커널 발행 방식

`sched_switch`에서 next task를 선택한 뒤 발행한다. 앞단의 wakeup/enqueue로 이동하지 않았다. 분할 arm은 일부를 여기서 발행하고 나머지를 실제 전환 뒤 `finish_task_switch.isra.0` entry에서 발행한다. 총 발행 수는 64 이하이며, 간격은 4/16개의 NOP 명령으로 제한했다. `__switch_to`에는 probe를 넣지 않는다. [Linux x86 switch source](https://github.com/torvalds/linux/blob/v6.8/arch/x86/kernel/process_64.c), [kprobe restrictions](https://docs.kernel.org/6.8/trace/kprobes.html).

MovieId와 UserTimeline에서 13개 방식(8/16/32/64 budget, 간격/묶음, 전후 분할, 동일 대상의 첫 실행 순서, T0 hint, 넓은 경로 coverage)을 탐색했다. 각 NOP 모듈은 발행 함수의 프리패치 3개만 같은 길이 NOP로 바꾼 복사본이다. 파일 크기·전체 byte diff를 확인했고 양쪽 모두 config mode 1을 사용했다. 따라서 같은 분기, 주소 로드, 카운터, 간격과 completion probe 경로가 실행된다.

| Service | Pattern | Target CPU vs same-path NOP | Pool CPU vs module off | Code misses vs NOP |
|---|---|---:|---:|---:|
| movie | wide_split | +0.58% (n=1) | -1.82% (n=1) | +7.15% (n=1) |
| movie | first_space | +0.24% (n=1) | -2.18% (n=1) | +1.91% (n=1) |
| movie | group4_t0 | +0.04% (n=1) | -2.74% (n=1) | +1.84% (n=1) |
| movie | split8_t0 | +0.39% (n=1) | -3.88% (n=1) | +1.92% (n=1) |
| movie | space16 | +0.19% (n=1) | -5.76% (n=1) | +2.00% (n=1) |
| movie | split8 | +0.09% (n=1) | -6.63% (n=1) | +2.54% (n=1) |
| movie | b32 | +0.06% (n=1) | -6.96% (n=1) | +1.92% (n=1) |
| movie | b16 | +0.04% (n=1) | -8.10% (n=1) | +1.75% (n=1) |
| movie | b8 | -0.10% (n=1) | -8.34% (n=1) | +0.34% (n=1) |
| movie | group4 | +0.36% (n=1) | -8.57% (n=1) | +2.74% (n=1) |
| movie | split16_64 | +0.09% (n=1) | -9.90% (n=1) | +2.77% (n=1) |
| movie | space4 | +0.17% (n=1) | -10.41% (n=1) | +2.41% (n=1) |
| movie | b64 | +0.65% (n=1) | -12.97% (n=1) | +2.31% (n=1) |
| usertimeline | wide_split | +0.42% (n=1) | -1.97% (n=1) | +2.83% (n=1) |
| usertimeline | first_space | +0.46% (n=1) | -2.21% (n=1) | +1.71% (n=1) |
| usertimeline | group4_t0 | +0.12% (n=1) | -3.07% (n=1) | +0.91% (n=1) |
| usertimeline | split8_t0 | +0.21% (n=1) | -5.24% (n=1) | +0.74% (n=1) |
| usertimeline | space16 | -1.07% (n=1) | -6.59% (n=1) | +1.58% (n=1) |
| usertimeline | split8 | +0.63% (n=1) | -5.11% (n=1) | +1.09% (n=1) |
| usertimeline | b32 | -0.27% (n=1) | -6.61% (n=1) | +0.61% (n=1) |
| usertimeline | b16 | +1.83% (n=1) | -6.88% (n=1) | +0.70% (n=1) |
| usertimeline | b8 | +0.01% (n=1) | -8.44% (n=1) | +0.10% (n=1) |
| usertimeline | group4 | +0.92% (n=1) | -10.82% (n=1) | +1.04% (n=1) |
| usertimeline | split16_64 | -0.01% (n=1) | -13.03% (n=1) | +0.84% (n=1) |
| usertimeline | space4 | +0.67% (n=1) | -9.66% (n=1) | +0.75% (n=1) |
| usertimeline | b64 | -0.74% (n=1) | -11.57% (n=1) | +1.52% (n=1) |

위 표는 방법당 1개 exploratory block이다. off는 스택 초기의 한 구간이고 뒤의 정책은 순차 실행되므로 off 대비 차이에 시간에 따른 workload 변화가 섞일 수 있다. 인접한 NOP 쌍과 독립 확인을 함께 보며, 이 표만으로 hook 비용이나 최고 이득을 확정하지 않는다. MovieId의 첫 block은 마지막 PMU 전에 부하 시간이 끝나 통째로 제외했다. 종료 시간 검사를 추가하고 여유 시간을 늘려 같은 seed/순서의 새 스택으로 반복했다. 제외한 block의 compact 측정과 사유도 보존했다. 긴 탐색에서 NOP 비용도 구간에 따라 변하는 것을 확인해, 독립 확인 시작 전에 후보 순위 규칙을 초기 off/NOP 중 작은 이득에서 인접 NOP 대비 이득으로 수정했다. 원래 순위·후보·진단과 `selection_amendment.json`을 보존했다. off 대비 순이득 요건은 독립 확인에서 그대로 적용한다. 선택 후 별도의 7개 새 baseline 프로세스에서 off/NOP/candidate 순서를 교대했다. 각 arm은 10초 안정화, 30초 CPU 측정을 사용했고 PMU/진단은 이 구간에 실행하지 않았다.

확정 후보: **usertimeline / b16**. 커널 승격: **False**.

| Metric | vs module off | vs same-path NOP |
|---|---:|---:|
| usertimeline_cpu | -0.46% [-1.02, +0.10] | +0.21% [-0.19, +0.60] |
| stack_cpu | -0.28% [-1.34, +0.77] | -0.23% [-1.35, +0.88] |
| pool_cpu | -0.22% [-1.22, +0.76] | -0.29% [-1.33, +0.75] |

커널 승격은 타깃 CPU가 off와 NOP 대비 모두 개선되고, 풀 CPU도 off 대비 개선된다는 95% 하한이 양수일 때만 인정한다. 타깃 비용만 낮아져도 outgoing task나 다른 서비스에 발행 비용이 전가될 수 있어 풀 비용을 함께 본다.

이번 구현은 실행 중인 커널에 모듈과 probe를 추가한 것이다. 커널 이미지를 직접 패치해 재부팅한 결과는 아니므로 직접 삽입 시 줄어들 수 있는 hook 비용까지 배제하지 않는다.

## Cold/timeliness 진단

진단은 64번 match마다 첫 발행 구간의 한 라인을 순환 샘플링한다. pre와 post는 다른 실행 구간이므로 pre의 data load가 post 샘플을 데우지 않는다. 아래 수치는 pinned physical alias의 **data 접근 지연과 전환 완료까지 시간**이다. 실제 첫 명령어 fetch latency, L1I/ITLB 복구, 캐시 레벨 구분 또는 core cycle로 해석하지 않는다. 진단 정책은 표에 명시하며, 원래 탐색 순위의 후보로 수행한 진단을 최종 확인 후보의 진단으로 바꾸어 부르지 않는다.

| Service / diagnostic policy | Phase | Samples | Median TSC tick bin | >=256 ticks |
|---|---|---:|---|---:|
| movie / first_space | d1_nop/pre | 3110 | [192, 256] | 40.29% |
| movie / first_space | d2_nop/post | 3106 | [192, 256] | 39.89% |
| movie / first_space | d2_t1/post | 3134 | [0, 64] | 4.91% |
| movie / first_space | d2_t1/lead | 3134 | [1536, 2048] | 100.00% |
| usertimeline / first_space | d1_nop/pre | 860 | [256, 384] | 52.21% |
| usertimeline / first_space | d2_nop/post | 858 | [256, 384] | 56.41% |
| usertimeline / first_space | d2_t1/post | 859 | [0, 64] | 2.44% |
| usertimeline / first_space | d2_t1/lead | 859 | [1024, 1536] | 100.00% |

별도 flush/sleep 기능 검사의 평균 median TSC ticks: `{'kernel_nop': 320.6666666666667, 'kernel_t1': 80.0, 'user_t1_positive': 80.0}`. 이 검사는 애플리케이션 성능 측정에서 제외했다.

`L2_RQSTS.CODE_RD_MISS`는 speculative code-fetch miss 요청을 세고, 학습의 `FRONTEND_RETIRED.L2_MISS` PEBS는 retired instruction에 귀속된 이벤트를 샘플링한다. 서로 같은 모집단이 아니므로 두 카운트로 직접 miss coverage를 계산하지 않는다. [Intel Granite Rapids event definitions](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).

## 재현성과 보존

원본 코드/입력은 보존했다. 오류가 난 트레이스, 실패·기각 후보의 결과와 source/명령/해시는 남기고 더 이상 쓰지 않는 raw/decoded trace, ELF 복사본, 실행 파일과 object는 즉시 정리했다. 모든 플랫폼 복원과 제거 경로/바이트는 evidence에 기록했다.

- [실행 드라이버](../llvm_prefetchit/scripts/class_b/README.md)
- [공개 결과 요약](../llvm_prefetchit/migration/evidence/class_b_fullset_20260926/results.json)
- [로컬 재현 아카이브 위치·해시](../llvm_prefetchit/migration/evidence/class_b_fullset_20260926/archive_reference.json)
- [이전 DSB 결과](dsb_results_summary_20260926.md)
