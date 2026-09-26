# 타입 B: 10% 목표를 위한 추가 분석·구현

**상태: 새 운영점·trace 검증 완료, 성능 비교 진행 중.** 타깃 병합 정책과
커널 switch-in 버스트 모듈을 구현하고 실서비스 비교를 시작했다. 사용자 제공
실행 권한으로 PMU 접근과 커널 lifecycle 검증을 완료했다. 아래 기존 분석과
추가 측정은 구분하며, 10% 달성으로 보고하지 않는다.

10%는 우선 **고정 요청률에서 타깃 서비스 user+kernel CPU/완료 요청 절감률**로
해석한다. user cycles와 전체 스택 비용도 별도로 보고한다. 커널 후보는 비용이
다른 태스크에 잡힐 수 있어 공유 풀 전체 CPU의 순이득도 필수다. 이는 목표이며
달성한 결과가 아니다. 사용자에게 지표 확인을 요청했으며 아직 답변은 없다.

## 기존 결과에서 확인한 제약

최근 확장은 서비스 오브젝트에만 삽입했다. 과거 MovieId는 thrift/jaeger 등
재컴파일한 아카이브에도 삽입했으므로, 두 계열의 커버리지와 측정 지표가 다르다.
MovieId 약 1.054x는 user cycles 기준의 과거 결과이고, 최근 전체 CPU 절감
약 1~1.4%와 같은 지표가 아니다. `1.10x speedup`과 `10% cost reduction`도
구분한다. 후자는 비용이 0.90배라는 뜻이다.

기존 baseline 탐색 3회의 비용 비중으로 계산하면 다음과 같다. kernel 비용이
그대로이고 user 비용만 줄어든다는 가정의 산술이며, 달성 가능한 상한이 아니다.

| 서비스 | user CPU / 타깃 전체 CPU | 전체 10%를 위한 user 비용 절감 |
|---|---:|---:|
| Media ComposeReview / tracing 100% | 34.4% | 29.0% |
| Media Rating / tracing 100% | 41.4% | 24.2% |
| Social ComposePost / tracing 10% | 43.3% | 23.1% |
| Social UserTimeline / tracing 10% | 64.8% | 15.4% |

따라서 UserTimeline과, 동일 지표로 재검증할 MovieId를 우선 대상으로 삼는다.
Rating은 높은 MPKI만으로 우선 승격하지 않는다. 이전 문서의 “약 5% 상한”은
당시 시험한 설정의 포화 관측이다. L2 code miss 수와 PT first-touch 수의 차이만으로
wrong-path miss의 정확한 비중이나 새로운 정책의 절대 상한을 확정할 수 없다.

## 높은 MPKI 운영점

보존한 정상 부하 측정을 다시 추출했다. Media tracing 10%의 Rating은
300/600/900 RPS에서 공유 MPKI가 65.05/63.77/60.54로, 부하를 높이면 오히려
낮아졌다. Social UserTimeline은 150/300/600 RPS에서 43.65/47.10/51.81이었다.
따라서 높은 요청률을 높은 MPKI와 동일시하지 않는다. 이전에 제외된 표본은
재분류하지 않았다.

다음 운영점 탐색은 baseline만으로 공유 풀 8/6/4코어와 정상 요청률을 교차한다.
Media는 300/600/900, Social은 300/600/900/1200 RPS를 후보로 삼되 포화점은
즉시 제외한다. 고정 2GHz, C6 off, 전체 스택·원본 데이터·info 로그·tracing을
유지한다. 워밍업 이후 오류/drop 0, RPS ±4%, p99 <100ms, 풀 활용률 ≥15%의
기존 기준을 유지하며, saturation을 이용해 MPKI를 인위적으로 높이지 않는다.
이웃 busy-spin, cache flush, 로그/tracing 비활성화는 넣지 않는다.

운영점은 baseline에서 먼저 고정하고 PF 결과를 본 뒤 바꾸지 않는다. 단독 대조군과
동일 부하를 비교하며 MPKI 외에 cycles/request, miss/request, context switches,
user/kernel 비중을 보존한다. tracing 10%/100% 결과는 따로 유지한다.

## 보존 trace에서 본 문맥과 초반 버스트

`analyze_wake_headroom.py`로 실제 보존된 run 목록을 다시 계산했다. 아래는
예산 32라인, 출현 확률 ≥80%, 첫 접근 순위 범위 <64일 때다.

| 서비스 | 평균 first-touch/run | 공통 목록의 예상 사용 라인/run | 문맥별 목록의 예상 사용 라인/run |
|---|---:|---:|---:|
| ComposeReview / tracing 100% | 313.0 | 3.68 | 31.17 |
| Rating / tracing 100% | 245.8 | 5.43 | 19.00 |
| ComposePost / tracing 10% | 563.8 | 5.31 | 30.85 |
| UserTimeline / tracing 10% | 811.7 | 4.87 | 31.66 |

이는 **학습 trace의 실행 경로 주변확률**이다. 실제 miss·fill·임계경로 지연·
성능이나 held-out 정확도가 아니다. 80% 기준을 통과하는 공통 후보가 적어,
공통 목록은 예산 32개를 모두 발행하지 않는다. 문맥별 값은 재개 뒤에 드러나는
method/return 문맥을 아는 비교 모델이며 커널에서 즉시 사용 가능한 예측기가 아니다.
희귀 run type의 목록이 없는 경우 분모에서 빼지 않고 예측 커버리지를 0으로 둔다.
입력 확률은 원래 소수 둘째 자리로 반올림되어 있다.

이 결과는 큰 공통 버스트 하나보다는 **문맥에 맞는 작은 초반 버스트 + 실행 진행에
따른 stream**을 시험할 근거다. run 전체는 수백 라인이어서 초반 32/64라인만으로
전체 커버리지가 충분하다고 볼 수 없다. 커널 버스트가 BTB/BPU나 사용자 ITLB를
복원한다고도 주장하지 않는다.

## 구현한 정책 변경

`flat_codegen/dsb_build/media/ws/ws_plan_pass.py`에 다음 옵션을 추가했다.

- `--merge-policy input-order`: 기존 선택 순서를 유지하는 대조 정책.
- `--merge-policy support`: 여러 run type의 후보를 `run 수 × target 출현 확률`로
  가중해 병합 cap 내 타깃을 선택한다. 파일 순서상 앞선 희귀 문맥의 독점을 줄인다.
- `--merge-policy byte-efficiency`: 위 점수를 직접/GOT 힌트의 예상 바이트 비용으로
  나눈다. 7/15바이트는 GOT 공유 전의 근사값이며 실제 비용으로 검증해야 한다.

기존 `p-min`, `k`, `kmerge`, `gap-k`, `post-call`, lead를 함께 바꿔 정확도와
커버리지를 차등화할 수 있다. 기본 정책은 기존과 동일하다. 새 metadata는
anchor 해석 및 최종 병합 cap **이후**의 entry 후보 커버리지를 기록한다. 기존
`assigned`는 그 이전 값이므로 실제 발행 커버리지로 읽으면 안 된다. post-call
커버리지와 runtime 정확도는 이 값과 별개다.

다음 비교는 정확도 우선(p=.8, cap8), 균형(p=.65, cap16), 커버리지 우선(p=.5,
cap32)과 서비스 오브젝트/재빌드 의존성 삽입 범위를 분리한다. lead 4/8/16은
first-touch 순위 단위로 명시한다. 우선 적은 후보를 탐색한 뒤 독립 확인한다.
새 원본 PT와 별도 PEBS/LBR 검증 자료가 필요하며, 이미 삭제한 raw branches를
주변확률 표로 복원했다고 가정하지 않는다. 기존 planner의 함수 내부 offset 보정도
최종 ELF에서 다시 확인해야 한다.

## 커널 버스트 프로토타입

소스와 사용법: [wake_prefetch](../llvm_prefetchit/kernel/wake_prefetch/README.md).
현재 Ubuntu 6.8.0-142 헤더로 빌드 성공했고 `prefetcht1` 인코딩도 확인했다.
**기본 runtime smoke 검증은 통과했고 실서비스 비교를 진행 중이다.**
별도 helper에서 실제 NOP/T1 발행, 중복 등록 거부, FD 종료 시 plan 해제,
exec 후 mm 불일치로 발행 중단을 확인했다. 검증 종료 후 모듈을 언로드했다.

`sched_switch`는 다음 주소 공간으로 바뀌기 전에 호출된다. 따라서 등록된
실행 파일 페이지를 process context에서 pin한 뒤, callback에서는 커널 direct-map
주소로 T1을 발행한다. 실제 saved user IP/syscall에 조건화한 최대 8개 profile을
등록할 수 있고 첫 일치 profile에서 최대 64라인만 발행한다. 명시적 대상 thread
group/mm에만 적용하며, 컨트롤러 FD를 닫으면 해제한다. NOP 모드도 구현했다.
커널 주소 공간과 페이지 pinning의 근거는
[Linux 6.8 scheduler](https://github.com/torvalds/linux/blob/v6.8/kernel/sched/core.c)와
[page pinning API](https://docs.kernel.org/6.8/core-api/pin_user_pages.html)다.

기존 parser의 `recv` 분류는 재개 이후 첫 branch들의 심볼을 보고 추정한다.
실제로 poll에서 재개하고 나중에 recv를 부를 수도 있어 이 문자열을 커널 syscall
번호로 바로 바꾸면 안 된다. 새 수집에서는 실제 switch-in 문맥과 PT run을 연결하고
학습/검증을 분리해야 한다. 후속 실행에서 생성한 문맥별 등록 plan과 검증은 아래에 기록했다.

비교군은 module off, loaded/no-plan, NOP, T1, 최선 user stream,
stream+NOP, stream+T1이다. 버스트 8/16/32/64를 각각 비교한다. module-on probe와
카운터 비용은 NOP/무등록 대조군으로 분리한다. 초반 실측의 판단 조건은 실제
matched switch >0, 정확한 데이터/요청 결과, miss 및 cycles/요청, 그리고 순 CPU 비용이다.

특히 callback은 **outgoing task context**에서 돈다. 타깃 cgroup CPU만 낮아져도
다른 서비스/idle에 비용을 넘겼을 수 있다. 풀 전체 non-idle CPU/완료 요청과 전체
스택 cgroup CPU를 함께 수집해 이를 배제해야 한다. 이 계측이 없는 커널 결과는
성능 향상으로 승격하지 않는다.

## 검증과 보존

실제 PIE 프로세스의 주소 매핑·ELF 해시 검사, C/Python ioctl ABI, alignment·중복·
burst 제한, 희귀 문맥 분모, 가중 병합, planner CLI 통합 경로 등 **11개 테스트 통과**.
추가 root smoke는 5개 lifecycle 확인을 통과했다. 동시 실행·실서비스 안정성 및
성능 확인을 대신하지 않는다. 빌드는
GCC 13.3/13.4 버전 차이 경고와 vmlinux 부재에 따른 BTF 생략을 기록했다.

근거는 `llvm_prefetchit/migration/evidence/class_b_headroom_20260926/`에 저장했다.
초기 분석 단계에는 benchmark 실행 파일·raw trace·서비스 DB를 만들지 않았다. 후속 생성과 정리는 아래에 기록했다. 교체한 초기 모듈
빌드의 해시·재구성 소스 기록을 남기고 888,723바이트를 정리했다. 현재 커널 후보
중간 object는 별도로 정리했고, `.ko`도 아래 커널 탐색 탈락 후 제거했다.
초기 분석 단계에는 NAS 전송을 수행하지 않았다. 독립 성능 확인은 기존처럼 새 seed의 7쌍을 사용하고
탐색과 합치지 않는다. 실패·탈락 후보는 측정·설정·소스·해시·제외 이유를 남긴 뒤
즉시 생성 bulk 산출물을 정리한다.

## 추가 실행: 운영점과 학습 검증

원본 SocialNetwork 전체 스택, Reed98 graph, info 로그, tracing 10%,
2 GHz/C6 off에서 UserTimeline baseline을 다시 실행했다. 아래 CPU는 타깃
user+kernel µs/완료 요청이다. 운영점 선택은 PF 결과를 보기 전에 고정했다.

| 공유 코어 | 요청률 | MPKI | 타깃 CPU | p99 ms | 판정 |
|---:|---:|---:|---:|---:|---|
| 8 | 600 | 52.41 | 159.67 | 4.76 | 정상 |
| 6 | 600 | 54.64 | 160.43 | 5.63 | 정상 |
| 4 | 600 | 57.38 | 162.87 | 10.37 | 선택 |
| 8 | 1200 | 55.89 | 167.94 | 8.65 | 정상 |
| 6 | 1200 | 56.86 | 166.16 | 27.19 | 정상 |
| 4 | 1200 | 55.61 | 159.00 | 262.04 | 포화, 제외 |

선택한 4코어/600 RPS는 풀 활용률 56.9%였다. 타깃만 코어 42–43으로
분리한 대조군은 MPKI 0.0733, 타깃 CPU 71.01 µs/요청이다. 이는 간섭이
큰 운영점이라는 근거이며, 차이 전체를 prefetch로 회복할 수 있다는 뜻은 아니다.
운영점·trace 수집 후 platform/HWP 원상복구 256개 비교를 모두 통과했다.

같은 baseline 프로세스의 분리된 두 PT 구간을 학습/검증으로 사용했다. decoder
error는 0이다. syscall-exit의 saved user IP를 별도로 수집했다. 독립 recorder의
시간을 직접 연결하는 최초 접근은 427개 학습 run 중 2개만 연결돼 기각했다.
허용 시간 폭을 늘리지 않고, **첫 PT trace-start 복귀 주소**와 관측된 유일한
syscall 번호를 연결한 뒤 ELF에서 직전 2바이트가 실제 `SYSCALL`인지 검증했다.
미래 method 이름을 classifier로 쓰지 않는다. 이 조건에 해당하지 않는 run은
예측하지 않으며, 실제 커널 match counter로 적용 여부를 다시 확인한다.

표본 순위에는 별도 10초 구간의 retired L2 miss PEBS 표본 11,043개를 사용했다.
이 CPU의 이벤트 정의는 [Intel Granite Rapids PMU 문서](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)의
`FRONTEND_RETIRED.L2_MISS` (`C6/03`, frontend `13`)다. speculative demand
code MPKI와 다른 지표이며, 표본 수를 타깃별 정확한 miss 확률로 해석하지 않는다.

검증 423개 run 중 학습된 4개 문맥에 394개가 일치했다. 정확도 우선 정책은
Wilson 하한 ≥0.8, first-touch 순위 <128을 쓰며, 넓은 정책은 하한 ≥0.3,
순위 <512를 쓴다. 모두 관측 sample 수로 순위를 가중한다.

| 커널 후보 | 경로 적중률 | 전체 first-touch 커버리지 |
|---|---:|---:|
| 정확도 우선, 최대 16라인 | 99.33% | 1.54% |
| 정확도 우선, 최대 64라인 | 99.21% | 3.47% |
| 범위 확대, 최대 64라인 | 82.88% | 6.42% |

이는 held-out **경로** 적중률이다. cache fill, 실제 miss 감소, timeliness나
speedup은 별도로 측정한다. poll 문맥은 높은 확률 기준에서 11라인만 남아
64라인 cap을 항상 채우지 않는다. 8/32라인 plan도 생성했지만 아직 timing
비교에 모두 사용하지 않았다.

서비스 스트림은 정확도/균형/커버리지 차등의 3종을 생성했다. 최종 ELF의
T1 명령 수는 각각 248/444/633개로, 계획상 타깃 수 256/460/657과 구분한다.
각각 NOP twin을 생성했다. 커버리지 빌드는 strong-symbol anchor 하나의
PIE link 오류로 실패했으며, 실패 로그·plan·정리 기록을 남기고 해당 1개
타깃을 제외해 재빌드했다. 의존성 내부까지 재컴파일한 확장은 아니다.
기존 planner의 함수 내부 offset 이동은 근사이므로 semantic alignment를
입증한 결과로 주장하지 않는다.

새 학습기/계측기의 관련 테스트는 총 15개 통과했다. 추출을 마친 generated
raw/decoded trace와 ELF 사본 399,991,150바이트는 해시·경로·정리 전후
공간 기록을 남긴 후 삭제했다. 원본 입력과 baseline/reference는 보존했다.
기존 기준 실행 파일은 NAS에서 필요한 경우 직렬·20 MiB/s rsync로 로컬에
staging한 뒤 manifest SHA-256과 대조하며, NAS 경로에서 timing하지 않는다.

## 커널 초기 버스트: 첫 실서비스 탐색 결과

같은 4코어/600 RPS, seed 8101의 새 프로세스 1회씩이다. **단일 블록 탐색값**이며
신뢰구간 또는 확정 이득으로 제시하지 않는다. 모두 오류/drop 0, 정상 RPS/p99,
PMU fully-scheduled 기준을 통과했다.

| 조건 | 타깃 CPU µs/요청 | baseline 대비 절감 | 풀 CPU 절감 |
|---|---:|---:|---:|
| module off | 164.47 | 기준 | 기준 |
| module loaded, no plan | 164.22 | 0.15% | −0.29% |
| 등록 NOP, 정확도 우선 cap64 | 165.73 | −0.77% | −0.06% |
| T1 정확도 우선 cap16 | 163.94 | 0.32% | −0.35% |
| T1 정확도 우선 cap64 | 166.53 | −1.25% | −0.13% |
| T1 범위 확대 cap64 | 164.28 | 0.11% | −0.51% |

T1 후보의 실제 match는 30초에 약 59,000회, 요청당 약 3.24–3.25회였다.
cap16은 약 42라인/요청, 정확도 우선 cap64는 약 96라인/요청, 범위 확대
cap64는 약 207라인/요청을 발행했다. 이는 시도 횟수이며 cache fill 수가 아니다.

**이번 세 커널 정책은 전체 풀 CPU의 순이득이 없어 승격하지 않았다.** 단일
탐색으로 모든 kernel prefetch 방식의 효과가 없다고 일반화하지 않는다. 특히
정확도 우선 cap64는 matching NOP보다도 타깃 비용이 높았다. 타깃 지표에서
작은 양수만 골라 kernel 개선으로 보고하지 않는다. 모듈을 언로드한 후 소스,
plan, 해시, 빌드·runtime 근거를 보존하고 사용하지 않는 `.ko` 391,160바이트를
즉시 삭제했다. 다시 실행할 경우 현재 커널 헤더로 빌드해야 한다.
