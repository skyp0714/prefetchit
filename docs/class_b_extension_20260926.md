# Class B 확장: 진행 중인 실험

MovieId의 trace 기반 wake-stream을 Media ComposeReview·Rating, SocialNetwork ComposePost·UserTimeline으로 확장한다. 같은 스택 내 서비스별 개선은 독립 애플리케이션 여러 개의 성공으로 세지 않는다. 아직 새롭게 확정된 성능 이득은 없다.

| 단계 | 방법 | 판정 |
|---|---|---|
| 정상 부하 선별 | Media 300/600/900 RPS, Social 150/300/600 RPS; 8코어 공유와 타깃별 2코어 단독 배치 | p99<100ms, 고정 50초 워밍업 이후 오류·drop 없음, 요청률 ±4%, 풀 활용률 ≥15%, shared MPKI≥5 및 단독 대비 ≥2배 |
| trace 학습 | 수정 없는 baseline의 Intel PT와 context-switch, 공유 부하에서 수집 | decode/loss 점검; run별 첫 접근 순서와 첫 executable 복귀 지점으로 문맥 구분 |
| 삽입 | 기존 LLVM cold-plan pass, service object의 함수 진입·post-call에서 T1 발행 | lead 8/16 first-touch lines, cap8/site·merge16·post-call12, baseline/PF/NOP 비교 |
| 탐색 | 각 정책 3개 fresh-process paired blocks, cyclic order | 원본과 동일 배치 NOP 모두 평균 ≥1% 개선이면 독립 확인 |
| 확인 | 새 seed의 7개 paired blocks, 탐색 표본과 분리; 동일50초 워밍업·30초 순수CPU 구간, 이후PMU 생략 | 양쪽 대조군 대비 평균 ≥1%, paired 95% CI 하한 >0 |

주 지표는 서비스 cgroup 전체 user+kernel CPU / 정확한 구간 내 완료 외부 요청 수다. 순수 CPU 구간과 PMU 구간을 분리하고, user CPU·L2 miss/요청·MPKI·context switch도 보존한다. 고정 요청률 CPU 절감은 최대 처리량 증가와 구분한다. 여러 후보·서비스의 확인 CI는 개별 구간이며 전체 계열 보정은 아직 하지 않는다.

확인 표본을 수집하기 전에 비용을 줄이도록 수집 일정을 조정했다. 탐색은155초 부하와 별도 PMU 측정을 유지한다. 독립 확인의 주요 구간(50~80초)은 그대로 유지하고 이후 PMU만 생략해95초에 종료한다. 확인7쌍은 줄이지 않으며, PMU 효과는 탐색3쌍의 결과로 명시한다. 확인 단계에서 수집하지 않은 카운터는 null로 남긴다.

완전한 스택·표준 request fields·정보 수준 로그·정상 MongoDB 설정·Redis의 캐시 역할·Jaeger 수집을 유지한다. cache flush나 인위적인 busy-spin 이웃을 넣지 않는다. 각 성능 arm은 새 스택과 동일 초기 데이터에서 시작하며, 결과·해시·소스·계획을 남기고 탈락 바이너리 및 생성 DB/decoded trace는 정리한다.

원본·PF·NOP 타깃은 모두 MovieId 실험과 같은 fat-static 재빌드 설정을 사용한다. 따라서 표의 차이는 동일 링크 설정에서의 삽입 효과다. 다른 서비스의 지원 바이너리와 설정도 arm 간 동일하다.

기존 MovieId 수치(+5.4%)는 user cycles/request 기준의 과거 결과다. 여기의 전체 CPU/request와 직접 같은 지표로 비교하지 않는다. 초기 확장은 기존 의존성 바이너리를 유지하고 service object에만 삽입하므로, 이전 MovieId에서 재컴파일한 static dependency 내부 사이트까지 포함한 결과와 coverage가 다를 수 있다.

PT branch reconstruction은 실제 miss oracle가 아니다. 이전 parser의 ±1µs 경계 확장은 제거하고 [switch-in,switch-out) 구간을 사용한다. 독립 경계 검사에서 이웃 run 사이 branch 중복이 없음을 확인했다. run-start 판단은 syscall tracepoint 없이 재개 후 첫 executable 복귀 프레임을 이용한다. 원래 함수 내부 offset을 새 링크의 burst 크기로 보정하는 기존 planner의 한계도 함께 보존한다.

현재 경로: `llvm_prefetchit/results/class_b_extension_20260926/` (드라이버), `/storage/prefetchit/class_b_extension_20260926/` (결과/작업 세트), `/trace/prefetchit/class_b_extension_20260926/` (일시 trace). 직렬 controller가 기존 Dgraph 비교를 마친 뒤 이 캠페인을 실행한다. TiDB와 JVM 100회 재검증은 뒤에 보존되어 있다.

Prefetch 결과를 보기 전 워밍업 검증 규칙을 명시했다. Media의 첫 부하에서 seed123의 username109 첫 접근(시작 약12.72초)에 HTTP500이 1건씩 발생했다. 이후 같은 스택의 부하에서는 재발하지 않았으나 원인은 미확정이다. 등록 응답 본문 및 MongoDB의 1,000개 사용자 이름·nonzero ID를 검증하고, 첫50초 오류와 이후 오류를 별도로 남긴다. 원래 제외한 baseline 표본은 계속 제외하며 재분류하지 않는다. 새 성능·trace 단계는 고정50초 이후부터 종료까지 오류·drop 0건을 요구한다. 결과에 워밍업 오류도 보고한다.

현재 정상600RPS에서 ComposeReview는 단독 MPKI2.48, 공유43.35이며 Rating은0.64→55.84다. 공유 풀 활용률45.9%, 요청 오류0건이다. 높은 miss 증가를 확인했다. ComposeReview lead8의 최초1쌍은 전체 CPU/요청−1.47%, user cycles/요청−3.43%, miss/요청−7.0%였으나 NOP 및 반복 확인 전의 단일 표본이다. Media의 삽입·비교를 먼저 완료한 뒤 SocialNetwork의 빌드·선별·삽입을 직렬 수행한다.

수집기 수정: 첫 Media qualification에서 짧은 수명의 스레드가 perf PID 부착 중 종료해 ESRCH가 발생했다. 해당 시도는 제외하고 v2에서 전체 지점을 새로 측정한다. PMU는 타깃 cgroup과 CPU32–43에 제한하며 서비스별로 별도30초 구간을 사용한다. 생성 직후/종료 직전 스레드도 cgroup 범위에 포함된다.

PT 수집 수정: `symfs`에서 vDSO가 누락되어 decoder 오류가7건씩 발생했다. 동일 build ID의 vDSO snapshot과 서비스 종료 후 오프라인 디코딩을 함께 적용하면 동일 trace의 오류가0건으로 사라졌다. live 디코딩은 snapshot만으로 해결되지 않았고, 종료 후에도 vDSO를 빼면19,466건의 오류가 발생했다. 실행 중 namespace와 snapshot 경로 해석의 상호작용 가능성이 있으며 구체적인 perf 내부 원인은 미확정이다. 새 수집은 타깃의 `/proc/PID/mem`에서 vDSO를 함께 snapshot하며 decoder 오류0건 및 AUX loss 없음 기준을 유지한다. 검토했던 whole-TID 제외 방식은 실제 계획 생성이나 성능 비교에 사용하지 않았다. 중단된 부하의 trace는 제외하고 새 부하를 수집한다. 실패 trace의 원인·오류·해시·정리 내역은 남겼다.

Tracing 설정을 추가 감사했다. upstream Media는 native/nginx 모두 const1(100%)이다. 진행 중인 Media 캠페인은 이 조건으로 고정해 보존한다. SocialNetwork는 원본 native10%·nginx20%였으며, 실험을 시작하기 전에 둘 모두10%인 private config를 사용하도록 정했다. 원본 설정은 수정하지 않는다. 추가 Media10% 캠페인은 별도 경로에서 qualification·PT·계획을 새로 만들고 lead8을 고정하여 3쌍 탐색 및 통과 시7쌍 독립 확인한다. tracing을 끄지 않으며, 100% 결과와 합산하지 않는다.

10% 캠페인에서 lead는 각 서비스의 완료된100% 탐색에서 승격된 설정을 고정한다(Compose8, Rating16). Rating 탐색 완료 후, 아직 어떤10% 표본도 수집하기 전에 지정했다. 따라서10%에서 각 설정의 이전 trace를 재사용하지 않고 새 계획을 만들며, 서비스별 이전 최선 설정의 재현성을 평가한다.

10% Media 선별 결과는300RPS(공유 활용률19.3%)였다. 100% 캠페인의600RPS와 요청률이 다르므로 개선 폭 차이를 sampling만의 인과 효과로 해석하지 않는다. 10%에서의 정상 운영점 재검증이며, 실패하더라도100% tracing 의존성을 증명하는 것은 아니다. 기존100%의 제외 표본은 재분류하지 않았다.
