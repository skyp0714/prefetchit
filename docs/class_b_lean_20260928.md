# 10–20µs 중심 저밀도 prefetch 캠페인

진행 중인 7시간 실험의 첫 체크포인트다. 목표 종료 시각은 2026-09-28 12:52:38 UTC이며, 아래 v1/v2 탐색 결과는 독립 확인 전 수치다. 10% 개선을 달성했다고 주장하지 않는다.

## 첫 비교 결과

동일한 Media 전체 스택에서 MovieId·ComposeReview·Rating 및 정적 의존성의 코드를 바꿨다. 8 CPU, C4, tracing 100%, 50초 warmup + 60초 clean ROI. v2는 7개 arm × 2개 seed block이며 두 번째 순서는 첫 번째의 정확한 역순이다. 모두 유효했고 플랫폼·scheduler·module 복구를 확인했다.

| 구현 | RPS | 평균 ms | p99 ms | 전체 CPU µs/request | util % |
|---|---:|---:|---:|---:|---:|
| base | 1139.8 | 3.4396 | 5.8961 | 6025.8 | 84.59 |
| outline_nop | 1141.6 | 3.4336 | 5.9514 | 6020.0 | 84.69 |
| outline_t1 | 1142.5 | 3.4313 | 5.9299 | 6016.3 | 84.72 |
| outline_it0 | 1156.8 | 3.3874 | 5.8587 | 5961.4 | 84.87 |
| dedup_it0 | 1150.0 | 3.4083 | 5.8675 | 6000.2 | 84.98 |
| tail_nop | 1157.3 | 3.3864 | 5.9757 | 6015.4 | 85.77 |
| tail_it0 | 1144.0 | 3.4261 | 5.8930 | 6014.1 | 84.84 |

Peak IT0의 paired log 비용 절감률은 원본 대비 CPU 1.07%, 평균 1.52%, p99 0.64%다. 같은 배치 NOP 대비 CPU 0.98%, 평균 1.35%다. 두 쌍의 탐색 결과이므로 확정 개선으로 승격하지 않았고 독립 확인 대상으로 유지했다. T1·중복 NOP thinning·40µs tail은 점추정 순위에서 뒤져 후속 후보에서 제외했다. 통계적으로 열등함을 증명한 것은 아니다.

## 코드와 발행

- Dense 과거 구현의 98,661–136,557개 힌트를 v2에서 12,262–14,868개로 줄였다. 실행 가능 section 증가는 원본 대비 약 4.8–6.3%다.
- 실제 CFG와 직접 호출 entry를 dominator에 배치한다. 함수당 최대 2곳, 그룹당 최대 8개, 최소 64 IR instruction 함수, shortest-path lead 24–600을 사용하며 짧은 lead는 건너뛴다. 일반 call continuation을 강제로 쪼개지 않는다.
- 커널은 incoming task가 결정된 sched_switch에서 CPU별 시각·구간 경계를 기록한다. 프리패치는 실행 중인 사용자 코드에서 발행한다. 실제 swap/memory page-in 훅이 아니다.
- `[5,8)` 일부, `[8,10)` 추가 그룹, `[10,20)` 전체 그룹, `[20,22)` 일부, `[22,24)` 더 적은 그룹이 eligible이다. 실제 빈도는 실행 경로에 따라 다르다. 시각은 scheduler 잔여 경로와 syscall 복귀를 포함한다.
- T1→IT0는 RIP-relative 명령의 한 바이트만 바꾼다. register 형태는 T1을 유지한다. CPUID 지원과 모든 직접 대상의 instruction boundary를 검증했다.
- 중복 NOP thinning은 크기를 줄이지 않는다. v3에서 실제 명령 삭제와 최종 주소 커버리지 확인을 구현했다. 복제된 기계어 위치는 LLVM asm uid로 구분한다.

## 미스 감소가 전체 성능으로 바로 이어지지 않는 이유

첫 v2 block의 NOP 대조군은 원본보다 대상 서비스의 retired instruction/request가 약 11–17%, user cycles/request가 약 10–14% 늘었다. IT0의 L2 code miss/request는 NOP 대비 약 1–3% 감소했지만 user cycles는 원본보다 여전히 높았다. 전체 CPU 점추정 개선만으로 이 비용이 해결됐다고 해석하지 않는다.

FE retired miss, L2 code request miss, ITLB walk, BACLEARS는 서로 다른 사건이며 합해서 원인 비율을 만들지 않는다. L1/L2/late SWPF selector는 공유 MSR 때문에 별도 PMU 창에서 측정했다. SWPF_HIT/MISS와 T1_T2_ISSUED는 IT0 발행 수가 아니다. FE_LATE_SWPF 역시 전체 IT0 수가 아니다. 각 PMU는 clean ROI 이후 별도 8초 진단이고 약 8.14초의 bracketing 요청 수로 정규화했다. 단일 PMU 반복의 작은 차이에 인과를 부여하지 않는다.

v1 inline RDTSCP peak는 원본 대비 평균 -0.50%였지만 CPU +0.76%로 탈락했다. v2는 shared preserve_all gate로 크기를 더 줄였다. v3는 RDPID/RDTSC와 epoch별 재발행 억제를 추가했고, hot 단일 지점의 synthetic gate 비용은 약 23→15–16→9 TSC ticks였다. 이는 E2E 개선 수치가 아니며 실제 스케줄/충돌/경로는 다르다.

## 검증과 보존

v2의 14회 복구를 검증했다. v3 초기 단위 검사 15개는 통과했지만 YAML 실제 빌드에서 asm 복제 라벨 충돌이 드러났다. 이를 수정하고 복제 회귀 검사까지 16개를 통과했다. 실패 빌드 트리와 plugin/test 생성물을 정리하고 원인·소스·로그·해시를 보존했다. v2의 superseded ELF 6개, 123,110,640 bytes를 삭제하고 원본·IT0 후보·NOP 대조군을 유지했다.

원본 결과: `/storage/prefetchit/class_b_lean_20260928`. Git의 compact evidence에는 설정·행별 결과·비교 통계·PMU·복구·정리 기록이 있다. 진행 중인 빌드와 후속 확인 결과는 다음 체크포인트에 추가한다.

명령 의미: [Intel ISA reference](https://cdrdv2-public.intel.com/774990/architecture-instruction-set-extensions-programming-reference.pdf). 호출 규약: [Clang preserve_all](https://clang.llvm.org/docs/AttributeReference.html#preserve-all). 복제 라벨: [LLVM inline assembly](https://www.llvm.org/docs/LangRef.html#inline-assembler-expressions). PMU 의미: [Intel Granite Rapids events](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).
