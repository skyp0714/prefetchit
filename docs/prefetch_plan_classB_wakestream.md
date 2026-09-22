# B 부류(interleaving) L2I miss를 위한 prefetcht1 삽입 계획 — "wake-stream" (2026-09-21)

`docs/prefetch_plan_by_miss_class.md` §3의 B-1/B-2를 대체·구체화하는 설계 문서다. 세팅은 그 문서 §0(코어 고정, C6 off,
interleaved = 스택 전체가 8코어 pool 공유, `:u` 카운터, NOP twin, 같은 라운드 인터리브 ≥3회, MODE=2ghz)을 그대로 따른다.
핵심 질문 두 가지 — **타깃을 무엇으로 잡는가**, **어디에 주입하는가** — 에 대한 답과 그 근거, 검증 순서를 적는다.

## 0. 한 문단 요약

B 부류의 miss는 "깨어난 스레드가 요청 경로를 처음부터 끝까지 cold L2로 달리는" 현상이다. 그래서 A 부류(capacity)와 정반대의
조건이 성립한다: (1) run(깨어남→다시 잠듦) 안에서 첫 접근하는 라인은 **거의 전부** miss다(P(absent | site 실행) ≈ 1, capacity에서는
0.1–1%였다). (2) run 안에서는 이웃이 끼어들지 못하므로 **너무 이른 prefetch가 없다** — 상한은 "깨어난 시점"이다(capacity의 4,000 cycle
창이 여기서는 run 전체로 넓어진다). (3) 대신 두 가지가 묶는다: 리드타임(cold IPC 0.34에서 코드가 늦게 도달하므로 사이트도 늦게 실행된다)과
**L2 fill queue(32–48 outstanding)** — 한 번에 뿌리는 burst는 버려진다(w64 43% fill vs 1,024라인 pacing −2%).
따라서 계획은 **"run 종류별 첫 접근 순서(temporal first-touch sequence)를 타깃 목록으로 삼고, 그 순서를 run의 코드 자신이 d 라인 앞서
k 라인씩 흘려보내는 software temporal stream"**이다. 타깃은 Intel PT로 run 단위로 기록한 첫 접근 순서(방법·hook·sub-RPC 인덱스로 조건화),
사이트는 (a) 깨어나는 지점(syscall 복귀 직후, rdtsc 게이트) = stage 0, (b) 이후 경로 위에서 run당 1회 실행되는 call 경계(handler·thrift
generated 코드·정적 링크된 라이브러리의 post-call 지점)에 d ≈ 24–48 라인(≈ 300–600 명령) 앞 타깃을 k ≤ 8 라인씩 배정한다.
Verilator의 exact-spacing stream이 이긴 이유(균일한 리드, 사이트 = 타깃 − D)를 레이아웃 순서 대신 **실행 순서**에 적용하는 것이다.

## 1. 확정된 사실 (이 계획이 딛고 선 숫자)

측정치는 `flat_codegen/dsb_build/postlink/RESULTS.md`, `results/target_analysis_cold*.txt`, `flat_codegen/dsb_build/media/logs/chain_media_hi.log`,
`llvm_prefetchit/results/capacity_media_20260920/ab_hi/ab.csv`에서 가져왔다.

| 항목 | 값 | 출처·비고 |
|---|---|---|
| media movie-id, interleaved(pool 0–7, C6 off, R=900 검증점: p99 15 ms) | **MPKI 85.5, IPC 0.34**, 요청당 명령 ≈118 k, 요청당 L2I miss ≈10.1 k, 요청당 사이클 ≈348 k | ab_hi rep 1. alone은 MPKI 3.25 / IPC 1.0 → cold-start 손실이 사이클 기준 ~3배 |
| 요청당 context switch / wake당 miss | 5.6회 / recv 434, poll 2,086 (cond 값은 로그 `cut -c1-200`에 잘림) | user-timeline, `wake_lines.py`(`results/wake_cold8/events.txt`에서 재생성 가능) |
| wake 이후 miss 분포 (16,159 run) | 1 µs 0.2% · 2 µs 1.4% · 5 µs 5.8% · 10 µs 13% · 20 µs 27% · 40 µs 52% · 100 µs 92%; run 중앙값 65 µs | 앞에 몰려 있지 않다 → 단발 burst로는 안 된다 |
| miss 위치 | **84%가 taken-branch 타깃 64 B 안** | fall-through는 HW next-line이 이미 처리 → 타깃은 "불연속의 첫 라인" |
| 기존 in-code plan의 실효 | SWPF 실제 fill 0.24–1.04% (99%가 L2 hit) | alone/shared trace로 고른 사이트가 cold run에서는 엉뚱한 곳 |
| wake 직후 LD_PRELOAD burst | 64라인: **43% 실제 fill**, 1.019x; paced 1,024라인: MPKI −16%, 명령 +6%, **0.982x** | 훅은 맞고, queue 한계와 pacing stall이 문제 |
| 타깃 라인 위 잔여 miss | 37–44% ("too late / evicted / dropped" 단일 버킷) | 사이트가 있어도 리드 부족·drop. 세 원인은 분리 측정된 적 없음 |
| 잔여 miss 상위 | TSocket::read, TFramedTransport::readFrame, ConnectionPool::fetch = wake 직후 소켓 읽기 경로 | "유일한 사이트가 직전 요청의 꼬리" → stage 0의 몫 |
| cold-start 손실 분해 (shared vs isolated, /kI) | 코드 miss 15.2→2.6, 분기 예측 실패 7.6→2.7, 데이터 5.2→2.5, TLB <10% | 코드 miss ≈ 절반. BTB/CBP cold는 prefetcht로 못 고친다 |
| 라인당 명령 수 (cold run) | 118 k / 10.1 k ≈ **12 명령마다 새 라인** | stream의 필요 처리량: IPC 1 목표면 12 cycle당 1 라인 |
| fill queue 한계 | 32–48 (스펙 추정, **미측정**) | §5-0에서 microbench로 확정 |
| L3 hit latency (이 호스트) | **미측정** (AsmDB Haswell 27 ns/76 cycle; GNR mesh는 더 길 것) | `icache_microbenchmark/microbench/src/latency.c`로 측정 |
| 현재 돌고 있는 ab_hi 체인 | `effhi` arm의 plan이 `{"sites": {}}`(13 B) → gs와 동일 바이너리, 비교 무효 | 심볼화 실패(`MovieIdService=0 (0.0%)`)가 원인. 체인은 끝에 MODE=restore를 하므로 그대로 둔다 |

리드타임 산수(2 GHz 서비스 클럭): L3 hit를 40 ns ≈ 80 cycle로 잡으면, prefetch가 성공해 IPC가 alone 수준(≈1.0)으로 회복된 뒤에도 늦지 않으려면
사이트–타깃 명령 거리 ≥ 2×80 ≈ 160 명령, 여유를 두어 **≥ 300 명령 ≈ 24 라인 앞**. Little's law로 IPC 1에서 12 cycle당 1 라인을 80 cycle
latency로 대려면 평균 7개 in-flight면 되고, queue 32–48의 절반 이하다. 즉 **드립(drip)은 가능하고 burst는 불가능**하다는 것이 숫자로 닫힌다.

## 2. 문헌에서 가져오는 규칙 (각 논문에서 무엇을 취하고 무엇을 버리는지)

| 논문 | 취하는 것 | 우리 맥락에서 바뀌는 것 |
|---|---|---|
| **AsmDB** (Ayers+, ISCA'19) | 거리 d = L3 latency(cycle) × IPC(명령 단위), 창 w 안의 후보 중 fan-in 최소·fan-out 최대 지점 선택, fan-out 임계로 가지치기. 측정 L3 76 cycle. 실측 end-to-end 0.5–1% | 그들의 상한 "w ≤ 200 명령"은 L1I(32 KB) self-eviction 때문. 우리는 L2 타깃 + run 안 self-eviction 없음 → 상한은 wake 시점. IPC는 alone IPC(성공 후 상태)로 계산 |
| **I-SPY** (Khan+, MICRO'20) | 주입 창 27–200 cycle 앞(L1I 기준); **context 조건부** prefetch(직전 32 basic block의 해시)로 accuracy↑; **coalescing**(8라인 창의 비연속 라인 묶기, 비연속 8이 연속 8보다 7.6% 우세); AsmDB식 무조건 삽입은 코드 footprint +13.7% | 새 ISA 없이 context를 얻는 방법 = **사이트를 handler/generated 코드의 call 경계에 둔다**(호출 문맥이 곧 context). coalescing은 128 B 페어(L2 adjacent-line prefetcher) + 표 방식 burst로 대신 |
| **PDIP** (Godala+, ASPLOS'24) | FDIP가 못 가리는 miss = resteer(분기 예측 실패·BTB miss) 직후의 라인; trigger = 마지막 taken branch; prefetch queue는 demand용 MSHR이 모자라면 **drop** | cold run에서는 BTB도 cold라 사실상 모든 불연속이 resteer → "84% taken-branch 타깃" 관측과 일치. 타깃 = 불연속의 첫 라인, 그 뒤 순차 라인은 HW에 맡긴다 |
| **RDIP** (Kolli+, MICRO'13) | 호출 스택 서명(RAS 상위 4개 XOR)이 다음 miss 집합을 강하게 예측; 서명 전이 시 다음 서명의 miss 집합을 prefetch | 소프트웨어 판: **call 복귀 지점**(스택 서명이 바뀌는 곳)을 사이트로, "그 지점 이후 d 라인 뒤에 처음 닿는 라인들"을 타깃으로 |
| **EIP** (Ros & Jimborean, ISCA'21) | 목적지 miss와 "latency만큼 앞서 실행된 source"를 entangle, source당 소수의 destination | 우리 (site, target) 쌍의 정의 그대로; 단 우리는 source를 명령 오프셋으로 정적으로 고른다 |
| **Jukebox** (Schall+, ISCA'22) | interleaving이 µarch 상태를 지워 CPI +31–114%, 추가 stall의 56%가 fetch latency; 호출당 명령 footprint 300–800 KB, 호출 간 공통성 90%+; **L2 instruction miss를 순서대로 기록**해 재호출 시 **L2로** replay, 메타데이터 32 KB, prefetch queue 상태에 맞춰 64 B씩 소비 | 우리에겐 replay 엔진이 없다 → "프로그램 진행에 묶인 replay"(§4)가 소프트웨어 대체물. pacing을 spin(pause)으로 하면 실패한다는 것은 이미 측정됨 |
| **Ignite** (Schall+, MICRO'23) | cold BTB/CBP가 남으면 Jukebox+Boomerang도 이상적 61% 중 20%만 회복; 따뜻한 BTB만으로 +4.2%; 첫 실행 분기의 mispredict가 33% | **기대치 상한의 근거**: 코드 miss(손실의 ~절반)만 건드리므로 cold-start 손실의 절반 이상은 못 돌려받는다 |
| Cache restoration (Daly & Cain, HPCA'12), Brown & Tullsen (HPCA'11) | 스위치-인/이주 시 working-set 요약을 HW가 prefetch | B-3(커널 모듈)·§4-4 ISA 제안의 계보. 이 문서의 프로세스 안 방식과 비교군 |
| Luk & Mowry (MICRO'98) | 컴파일러 next-N-line + 분기·호출 타깃 prefetch, HW 필터로 중복 제거 | 우리의 stage 사이트가 "타깃 prefetch"에 해당; HW 필터 없음 → 표 방식으로 중복을 정적으로 제거 |

## 3. 타깃 선정

### 3-1. 단위: run 종류 (hook × method × sub-RPC 인덱스)
- run = 스레드가 깨어난 시점(syscall 복귀)부터 다시 잠들 때까지. 한 요청은 평균 5.6개의 run이고, 각 run이 별개의 cold start다.
- run 종류 R = (깨운 hook: recv/poll/cond, thrift method 이름, method 안에서 몇 번째 sub-RPC 복귀인지). thread-per-connection(TThreadedServer)이라
  한 스레드의 run 열이 곧 한 요청의 진행이다.
- **데이터 소스는 Intel PT**(이 호스트에 `intel_pt` PMU 있음, `perf_event_paranoid=-1`, perf 6.8): `perf record -e intel_pt//u -e sched:sched_switch
  -e raw_syscalls:sys_exit -a -C 0-7 -- sleep 0.3` 정도면 수천 run이 잡힌다. PT는 run 안의 **모든** 명령 흐름을 주므로 (a) 첫 접근 순서를 정확히,
  (b) 각 라인의 wake 기준 **명령 오프셋**을, (c) 사이트 후보의 run당 실행 횟수와 fan-out을 표본 없이 준다. LBR 32개 창(100–300 명령)은 여기서
  필요한 300–600 명령 리드를 못 본다 — 이것이 기존 cold_plan의 근본 한계였다. PEBS L2I miss 샘플은 검증용(§3-4)으로만 쓴다.
- 도구: `run_paths.py` (PT decode → run 분할 → 종류별 첫 접근 열). 심볼은 호스트의 `active/` 바이너리 사본으로 `--symfs`를 주어 푼다
  (현재 `MovieIdService=0 (0.0%)` 실패의 원인이 컨테이너 경로 심볼화이므로 이것을 먼저 고친다).

### 3-2. 타깃 목록 T_R
1. 종류 R의 run들에서 라인 ℓ의 첫 접근 명령 오프셋 중앙값 o(ℓ)와 등장 확률 p(ℓ)를 구한다. **p(ℓ) ≥ 0.5**인 라인만 남긴다(fan-out 규칙의 타깃 쪽 판).
2. 순차 연속 라인 제거: 직전 라인이 같은 run에서 바로 앞에 접근되고 그 사이에 taken branch가 없으면(=fall-through) 제외 → HW next-line 몫.
   84% 규칙상 목록은 크게 줄지 않지만, 남은 것이 모두 "불연속의 첫 라인"임을 보장한다.
3. **128 B 페어로 병합**: L2 adjacent-line prefetcher가 켜져 있으면(MSR 0x1a4 bit 1 확인) 페어의 한 라인만 prefetch한다. Verilator에서 128 B 간격이
   64 B보다 좋았던 이유가 이것이다. 요청당 10 k miss → 목록 5–8 k로 준다.
4. 라이브러리 라인도 전부 포함한다(과거 trace: libc 27%, 서비스 24%, libstdc++ 16%, jaeger 12%, pthread 7%, mongoc 5%). fat-static 빌드에서
   libstdc++/thrift/jaeger/mongoc은 `PREFETCHIT_COLD_DIRECT_SYMS`로 pc-relative 한 명령이고, glibc만 GOT 앵커 형태(`mov sym@GOTPCREL,%r11; prefetcht1 off(%r11)`)로 남는다.
5. 예산: run당 prefetch 수 B_R = |T_R| (초기값), 요청당 합계 ≤ 8 k. 비용은 두 갈래로 따로 센다 — 명령 수(+5–7%)와 **코드 바이트**(inline 7 B ×
   8 k = 56 KB ≈ 요청 경로의 +9% 라인). 코드 바이트가 늘면 miss도 는다. 그래서 큰 burst(k ≥ 16)는 **표 방식**으로 낸다(§4-5).

### 3-3. 왜 "miss한 라인"이 아니라 "첫 접근 라인"인가
capacity 계획은 miss 샘플에서 타깃을 골랐고 benefit = min(사이트 실행, 타깃 miss)였다. B 부류에서는 run 안 첫 접근이 곧 miss이므로 타깃 집합은
trace의 miss 여부와 무관하게 **첫 접근 열 그 자체**다. 이 단순화가 주는 것: (a) 타깃마다 P(absent)를 추정할 필요가 없다(≈1), (b) 커버리지가
"몇 %의 라인을 어떤 순서로 낼 수 있는가"라는 스케줄링 문제로 바뀐다, (c) alone trace로 만든 plan을 interleaved에 쓰는 실수를 원천 차단한다.

### 3-4. 타깃 목록의 검증(빌드 전)
- PEBS L2I miss 샘플(기존 `cold_trace_lbr.sh` 이벤트)로: miss 샘플 중 "그 run의 첫 접근 라인"인 비율 ≥ 80%, T_R(p ≥ 0.5)이 miss 가중치의 ≥ 70%를 덮는지.
- 미달이면 run 종류가 너무 다양한 것이다 → p 임계를 낮추기 전에 R의 정의를 세분(예: 응답 크기 구간)하거나, 그래도 안 되면 프로세스 밖(B-3)으로 넘긴다.

## 4. 주입 위치

### 4-0. 원칙
- 사이트는 **run당 정확히 1회 실행되는 프로그램 지점**만 쓴다(비용 = 실행 수 / 절약 miss ≈ 1). 함수 진입보다 **call 경계**를 우선한다: flags·r10/r11이
  죽어 있어 표 방식 루프를 넣을 수 있고, 호출 문맥이 context 조건이 된다(I-SPY의 Cprefetch를 배치로 대신).
- 사이트 s와 타깃 ℓ의 거리는 **명령 오프셋** o(ℓ) − o(s)로 정의하고 D_min ≤ 거리 ≤ D_max, D_min ≈ 300 명령(§1 산수), D_max = D_min + 창.
- 사이트당 k ≤ 8(inline) / ≤ 32(표 방식, stage 0). in-flight 상한을 넘지 않도록 "현재 위치 기준 D_max 안의 미도착 타깃 수 ≤ Q(초기 24)"를 유지한다.

### 4-1. Stage 0 — 깨어나는 지점
- 위치: 블로킹 호출이 복귀한 직후. movie-id에서는 `TSocket::read` 안 `recv` 복귀(새 요청), handler 안 client stub `recv_<Method>`의 `recv`/`poll` 복귀(sub-RPC),
  `pthread_cond_wait` 복귀(ClientPool 등). 모두 fat-static으로 우리가 컴파일하는 코드다 → pass의 post-call 사이트로 넣는다(LD_PRELOAD 불필요;
  LD_PRELOAD의 cond 래퍼는 thrift를 깨뜨렸다).
- 게이트: `rdtsc` 전후 차 > 20 k cycle(잠들었음)일 때만 발행. 게이트는 사이트 1–3곳이라 epoch 게이트(339곳, −2.5%)와 달리 비용이 없다.
- 내용: R의 **method 무관 접두**(frame 읽기 → 프로토콜 파싱 → `processMap_` 조회)의 첫 24–32 페어. 이것이 43% fill을 보인 w64의 정확한 후계이며,
  기존 plan의 잔여 상위(TSocket::read/readFrame/ConnectionPool::fetch)를 정확히 겨눈다.

### 4-2. Stage 1 — method 분기
- `MovieIdServiceProcessor::dispatchCall`이 `processMap_.find(fname)` 뒤 `process_<Method>`로 들어가는 지점(`gen-cpp/MovieIdService.cpp:665–740`).
  `process_<Method>` 진입이 method별 사이트다(B-2). 여기서 handler 진입까지의 역직렬화 구간 + handler 앞부분 타깃을 낸다.

### 4-3. Stage 2… — 경로 위 stream
- 후보 사이트: run R의 경로 위 call 경계와 함수 진입 중 (i) run당 실행 1회(중앙값 ≤ 1.5), (ii) R의 run 중 ≥ 90%에 등장(fan-out), (iii) 서비스 코드 ·
  thrift generated · 정적 링크 라이브러리 안(libc 내부는 사이트로 못 씀).
- 배정(그리디, 경로 순): 사이트 s_i를 오프셋 순으로 돌며 아직 배정 안 된 타깃 중 o(ℓ) ∈ [o(s_i)+D_min, o(s_i)+D_max]인 것을 k개까지 준다.
  사이트가 촘촘하면(이런 코드는 20–50 명령마다 call이 있다) k는 2–8에 머문다. 어떤 사이트도 못 닿는 타깃은 (a) 더 이른 사이트로 올려 리드를 키우거나
  (b) 버리고 커버리지 손실로 기록한다.
- sub-RPC 복귀 지점은 stage 0과 같은 성격이지만 method 문맥을 이미 안다 → 가장 좋은 사이트다.

### 4-4. 두 매개변수 d, k와 스윕
- d(라인) ∈ {16, 32, 64} ↔ D_min ≈ {200, 400, 800} 명령(12 명령/라인 환산), k ∈ {4, 8}, Q ∈ {16, 24, 32}. 총 arm 수는 빌드 전 시뮬레이터(§5-2)로 3–4개로 줄인다.
- 판정 카운터: `L2_RQSTS.SWPF_MISS`(0x24/0x28, 실제 fill) / `SWPF_HIT`(0x24/0xc8) 비율(현재 in-code plan 1%, w64 43%; 목표 ≥ 30%), L2I MPKI, 요청당 사이클, 명령 수, p99.

### 4-5. 주입 기구
- **주 경로: pass plan 모드 확장** — 현재 사이트는 함수 진입(또는 dominator)뿐이다. 사이트 종류를 추가한다:
  `{"fn": ..., "kind": "post_call", "callee": ..., "nth": n, "gate": "rdtsc"|null, "k": bytes, "t": [...]}`. 함수 안 사이트 뒤쪽 타깃 오프셋은
  사이트의 K만큼 보정(지금의 "≥16이면 +K" 규칙의 일반화). DSB deps 이미지는 96코어에서 ~40 s, 서비스 빌드도 분 단위라 재컴파일 비용은 문제가 아니다.
- 인코딩 두 가지: (a) inline `prefetcht1 sym+off(%rip)` 7 B/라인 — k ≤ 8; (b) **표 방식** — `lea tbl(%rip),%r11; mov $n,%r10d; 1: prefetcht1 (%r11); add $8,%r11; dec %r10d; jnz 1b`
  + 8 B/항목의 rodata 표(연속이라 HW L2 streamer가 덮음). 코드 바이트를 안 늘리고(명령 수만 4배) k=32까지 낸다. stage 0/1 전용.
- 보조 경로: `tools/asm_seq_inject.py`는 4명령마다·call마다 `pfm_<n>` 라벨을 찍으므로 `--plan` 모드(라벨→prefetch 목록)를 추가하면 어셈블리 수준에서
  같은 사이트를 2–3분에 만들 수 있다 — 스윕 arm 양산용.
- glibc 라인은 GOT 앵커 형태를 유지한다(정적 glibc는 NSS/getaddrinfo 때문에 보류).
- twin: 같은 레이아웃의 NOP twin(필수) + ablation arm 두 개 — stage 0만 / stream만 — 로 어디서 이득이 오는지 분리한다.
- **prefetchit1 arm**: 같은 plan을 `-prefetchit-mnemonic=prefetchit1`로 한 번 더 만든다. 사용자 지침대로 이 명령은 frontend starvation에서 작동한다고 보며,
  IPC 0.34의 interleaved run이 정확히 그 조건이다(RIP-relative 사이트만; GOT 형태 타깃은 prefetcht1 유지).

### 4-6. 기존 in-process 시도와 무엇이 다른가
| | 기존(cold plan v4/v10, timeline, wake burst) | 이 계획 |
|---|---|---|
| 타깃 | alone/shared trace에서 miss한 라인 | interleaved PT trace의 run 종류별 첫 접근 열(p ≥ 0.5), 128 B 페어 |
| 사이트 | miss 60–4,000 cycle 앞의 가장 드문 함수 진입 | run당 1회 실행되는 call 경계, 명령 거리 D_min 이상, 리드 상한 = wake |
| 발행 형태 | 함수 진입 burst ≤ 32라인 / wake에 64–1,024라인 | stage 0 ≤ 32(표) + 경로 위 k ≤ 8 드립, in-flight ≤ Q |
| 문맥 | 없음(공유 라이브러리 함수가 사이트) | handler/generated/sub-RPC 복귀 = 호출 문맥 내장 |
| 측정된 실효 | fill 1% / 43%(wake만) | 목표 fill ≥ 30% 전 구간 |

## 5. 실험 프로그램 (순서·게이트·시간)

0. **준비 (0.5일)** — (a) `run_paths.py`용 심볼화 수정(`--symfs` + `active/` 사본; 현재 ab_hi의 무효 원인). (b) fill-queue microbench:
   `icache_microbenchmark`에 cold 코드 라인 N ∈ {8,16,32,48,64,128}개를 연속 `prefetcht1`한 뒤 SWPF_MISS와 실제 L2 상주(타이밍)로 **몇 개까지 안 버려지는지** 측정
   → Q. (c) `lat_bench`로 L3 hit latency 측정 → D_min. (d) MSR 0x1a4로 adjacent-line prefetcher 상태 확인 → 페어 병합 여부.
1. **trace (1일)** — interleaved(pool 0–7, C6 off, R=900) PT + sched_switch + sys_exit 0.3 s × 3회, 같은 조건의 PEBS L2I miss 30 s 1회. `run_paths.py`로
   run 종류별 T_R, 사이트 후보, o(·), p(·). **게이트 G1**: miss 샘플의 ≥ 80%가 run 첫 접근, T_R 커버 ≥ 70%.
2. **planner + 시뮬레이터 (1일)** — `wakestream_plan.py`(§4-3 그리디) + PT run 위에서 (d, k, Q, L3 latency, IPC 모델)로 "제때 도착하는 타깃 비율"을 예측.
   **게이트 G2**: Q=24에서 예측 커버리지 ≥ 50%. 미달이면 표 방식 비중을 올리거나 R을 세분한다.
3. **빌드 (1일)** — pass post-call 사이트·rdtsc 게이트·표 방식 구현, movie-id fat-static 위에 arm: ws_d32_k8, ws_d16_k8, ws_d64_k8(+twin), stage0-only, stream-only, prefetchit1.
   `objdump`로 사이트 수·prefetch 수·표 크기 검증, 레이아웃 drift는 twin 대비 라인 일치율(과거 757/881)로 확인.
4. **A/B (1일)** — `media_ab.sh` 5회 인터리브, SWPF 카운터 포함(Django의 MODE=swpf를 옮긴다). **게이트 G3**: fill ≥ 30%, MPKI −30% 이상, 요청당 사이클 ≥ 1.05x.
   1.10x면 논문 행으로 채택. 미달 시 진단 순서: fill 비율이 낮으면 Q/k(버려짐), 타깃 라인 위 잔여가 높으면 d(리드), 명령·라인 증가가 크면 p 임계·표 방식(비용).
5. **일반화 (1–2일)** — compose-review(38 MPKI), socialNetwork compose-post(42), user-timeline(9–13). nginx/OpenResty(LuaJIT)와 Go는 제외, 스토어는 post-link로 나중에.
6. **비교군** — B-5 affinity sweep(반나절)과 B-3 커널 switch-in 모듈은 그대로 진행한다. 이 문서의 결과가 "프로세스 안에서 얼마까지"의 답이고, B-3가 "프로세스 밖의 값"이다.

## 6. 기대치와 리스크

- 상한: cold-start 손실(사이클 ~3배)의 절반이 코드 miss 몫이다(§1 분해). 첫 접근 열의 70%를 덮고 그중 70%가 제때 오면 miss −50% → IPC 0.34에서
  대략 **1.15–1.3x**가 목표 범위, 게이트 G3의 1.05x는 최소선. Ignite가 보이듯 BTB/CBP cold는 남으므로 alone(IPC 1.0)으로의 복귀는 불가능하다.
- 리스크 1 — queue drop: Q를 실측하지 않으면 k를 못 정한다(5-0-b 선행). 리스크 2 — run 종류 다양성: p ≥ 0.5 커버가 낮으면 in-process는 여기까지이고
  B-3로 넘어간다(G1이 결정). 리스크 3 — 코드 바이트 증가가 miss를 늘림: inline은 k ≤ 8로 묶고 큰 burst는 표 방식. 리스크 4 — glibc 27%는 GOT 형태의 비용(11–15 B)이
  든다: p 임계를 libc 라인에만 0.7로 올려 수를 줄인다. 리스크 5 — 레이아웃 drift: post-call 사이트가 함수 안 오프셋을 밀므로 K 보정과 twin 검증이 필수.
- 보고 형식은 `feedback-reporting-format` 규칙대로: 워크로드당 한 행, base(gs) 대비 실측 speedup과 MPKI before→after, 명령 수, 세팅. ablation과 스윕은 CSV.

## 참고문헌
- Ayers et al., "AsmDB: Understanding and Mitigating Front-End Stalls in Warehouse-Scale Computers", ISCA 2019 — https://research.google/pubs/asmdb-understanding-and-mitigating-front-end-stalls-in-warehouse-scale-computers/
- Khan et al., "I-SPY: Context-Driven Conditional Instruction Prefetching with Coalescing", MICRO 2020 — https://web.eecs.umich.edu/~barisk/public/ispy.pdf
- Godala et al., "PDIP: Priority Directed Instruction Prefetching", ASPLOS 2024 — https://liberty.cs.princeton.edu/Publications/asplos24_pdip.pdf
- Kolli, Saidi, Wenisch, "RDIP: Return-address-stack Directed Instruction Prefetching", MICRO 2013 — https://dl.acm.org/doi/10.1145/2540708.2540731
- Ros, Jimborean, "A Cost-Effective Entangling Prefetcher for Instructions", ISCA 2021 — https://webs.um.es/aros/papers/pdfs/aros-isca21.pdf
- Schall et al., "Lukewarm Serverless Functions: Characterization and Optimization" (Jukebox), ISCA 2022 — https://ustiugov.github.io/assets/files/JUKEBOX_ISCA22.pdf
- Schall, Sandberg, Grot, "Warming Up a Cold Front-End with Ignite", MICRO 2023 — https://ease-lab.github.io/ease_website/pubs/IGNITE_MICRO23.pdf
- Jamilan et al., "APT-GET: Profile-Guided Timely Software Prefetching", EuroSys 2022 — https://dl.acm.org/doi/10.1145/3492321.3519583
- Daly, Cain, "Cache Restoration for Highly Partitioned Virtualized Systems", HPCA 2012 — https://ieeexplore.ieee.org/document/6169029/
- Brown, Porter, Tullsen, "Fast Thread Migration via Cache Working Set Prediction", HPCA 2011 — https://cseweb.ucsd.edu/~tullsen/HPCA2011brown.pdf
- Luk, Mowry, "Cooperative Prefetching: Compiler and Hardware Support for Effective Instruction Prefetching in Modern Processors", MICRO 1998

## 7. 첫 구현과 측정 — media movie-id, interleaved (2026-09-21)

가장 구현이 쉬운 B 부류 워크로드로 media movie-id를 골랐다(fat-static 빌드·인터리브 하네스·운영점이 있고 method가 둘뿐). 세팅: 스택 전체가
코어 0–7, C6 off, MODE=2ghz, **R=600**(R=900은 5회 반복 중 p99가 초 단위로 무너져 600으로 내림; MPKI는 200–900에서 84–88로 같다).
모든 도구는 `flat_codegen/dsb_build/media/ws/`에 있다.

### 7-1. 만든 것
| 도구 | 역할 |
|---|---|
| `ws_up.sh`, `ws_pt_trace.sh` | 인터리브 스택 기동; **Intel PT** 트레이스(`-a -C 0-7 --switch-events`, tracepoint 없이 — raw_syscalls를 함께 켜면 링버퍼가 넘쳐 PT 청크가 유실된다; `-p PID` 모드는 두 번 다 빈 파일을 냈다), 디코드는 `--symfs=/proc/PID/root --pid=PID`(컨테이너 경로 심볼화 — chain_media_hi가 깨진 원인) |
| `run_paths.py` | run 분할(switch-in→out), hook = 재개 지점 심볼(컨테이너 libc는 stripped → `nm -D`), method 세션(디스패치 run부터 다음 디스패치까지), run의 **첫 mark**로 run 종류 결정, 종류별 첫 접근 열 `list_<method>__m<k>.tsv` + hook별 `list_<hook>__all.tsv` + 후속 run 분포 `next.tsv` |
| `ws_patch_src.sh` | 소스 mark 9곳(`WS_MARK(id)`: weak 심볼 호출, 런타임 없으면 2명령): gen-cpp `process_<Method>` 진입(1,2), handler Inject 뒤(3), memcached_get 뒤(4), mongo find 뒤(5), std::async 람다 3개의 시작(6,7,8), future join 뒤(9) → 바이너리 `out_mid_wsm` |
| `ws_marks.sh`, `ws_lists.py` | 바이너리에서 mark 주소 추출; `WS_LIST` 파일 생성(`L key dso line` 순서 목록, `S mark key pos` 사이트 위치 자동 결정, `N mark key…` = 그 mark 뒤에 올 run 종류 목록) |
| `ws_rt.c` → `libws.so`/`libws_nop.so` | LD_PRELOAD 런타임: recv/read/poll/epoll 래퍼가 rdtsc 차 > 20 k cycle이면 "잠들었다"로 보고 **다음 run 종류 목록**(mark가 예약한 N 큐, 없으면 hook 목록)의 앞 N0 라인을 `prefetcht1`; `ws_mark(id)`는 목록을 바꾸고 pos부터 QM 라인 발행 |
| `ws_plan_pass.py` | **dense drip**용 pass plan(`PREFETCHIT_COLD_PLAN`): 사이트 = 경로 위 exe 함수 진입(run당 호출 ≤1.5, p ≥ 0.8), 타깃 = 같은 run 종류 열에서 d..Dmax 라인 앞의 미배정 라인 k개; exe 라인은 전역 심볼+오프셋(pc-relative), 라이브러리 라인은 기본 버전 export 심볼+오프셋(GOT; compat/`GLIBC_PRIVATE` 앵커는 링크 실패). 앵커–라인 사이에 들어갈 burst 바이트(16 B 배수)만큼 오프셋 보정 |
| `ws_ab.sh`, `ws_summary.py` | 5–7 이벤트 perf stat(L2I, **SWPF_MISS/HIT**, 명령, 사이클, cs) + wrk2; arm 스펙 `name=ARM[:preload:list:N0:QM]` |

### 7-2. run 구조 (PT 0.1 s, 60 요청, 761 run → **요청당 12.7 run**)
| run 종류 (첫 mark) | 깨운 hook | run 수 | 첫 접근 라인(중앙값) | 길이 | p ≥ 0.5 라인의 첫 접근 커버 |
|---|---|---:|---:|---:|---:|
| m1 디스패치(readFrame→parse→process_UploadMovieId→handler→jaeger Extract/StartSpan/Inject→memcached_get) | recv | 76 | 762 | 58.5 µs | **95%** |
| m4 memcached 응답 뒤(pool push, span, **std::async ×3 = pthread_create ×3**, futex 대기) | recv/send | 77 | 909 | 113 µs | 93% |
| m0 첫 future.get 복귀(짧음) | futex | 93 | 63 | 9 µs | 43% |
| m9 join 뒤(span Finish, 응답 write, 다음 요청 readFrame까지) | futex | 77 | 318 | 38 µs | 93% |
| m6 / m7 / m8 = async 워커(memcached set / compose RPC / rating RPC) | **clone(스레드 생성)** | 76/76/75 | 324 / 136 / 138 | 35 / 28 / 29 µs | 96 / 100 / 100% |
| m0 (mark 없음: 워커의 RPC 응답 뒤 Push+종료 등) | recv/none | 243 | 318 | 17 µs | 74% |

- 후속 run은 결정적이다: m1 → m4(98%) → m0(88%) → m9(74%) → m1(90%); m6/7/8 → 종료 run. 그래서 mark가 다음 wake의 목록을 예약할 수 있다(`N` 줄).
- 첫 접근 시각: run 시작 후 5 µs 안 19.6%, 10 µs 37%, 20 µs 63%, 40 µs 90.7%(run 중앙값 28 µs). 소비율 ≈ **13 라인/µs = 2 GHz에서 150 cycle당 1 라인**.
- **요청당 첫 접근 라인 ≈ 3.7 k인데 L2I miss는 ≈ 10.1 k(85 MPKI × 119 k 명령)** → miss가 첫 접근의 2.7배. PT는 retire된 경로만 기록하므로 나머지는 cold BTB/BPU가 만드는 wrong-path/fall-through 코드 fetch로 해석한다(§1 분해에서 분기 예측 실패가 손실의 1/4). **첫 접근 prefetch의 상한은 집계된 miss의 ~37%**다.
- exe 함수 진입은 열 위에서 촘촘하다(간격 중앙값 2–3 라인, p90 9–15) → 함수 진입 사이트만으로 drip이 가능. 단 pass가 실제로 계측할 수 있는 것은 서비스 오브젝트가 정의한 함수뿐(205개 후보 중 107개; std::thread::join, TSocket::read 같은 정적 아카이브 함수는 사이트 불가, 타깃만 가능).

### 7-3. Round 1 — stage 0 + mark (LD_PRELOAD, 바이너리 wsm), 3회, R=600
| arm | 요청당 사이클 | vs base | L2I MPKI | IPC | 명령 | SWPF 실제 fill |
|---|---:|---:|---:|---:|---:|---:|
| base (wsm, preload 없음) | 365.6 k | 1.000x | 84.4 | 0.327 | 1.000x | – |
| ws32 (wake 32 + mark 32) | 364.5 k | 1.003x | 84.5 | 0.339 | +3.5% | 48% |
| **ws64 (wake 64 + mark 32)** | 360.4 k | **1.014x** | **81.0** | 0.347 | +4.5% | 47% |
| nop twin (ws64와 같은 명령, prefetch→nop) | 368.5 k | 0.992x | 85.7 | 0.338 | +4.3% | – |

읽는 법: (1) fill 47%는 기존 in-code plan의 1%와 대비되는 숫자 — 훅과 목록은 맞다. (2) 발행 대비 L2 도달(SWPF 계수)은 32라인 burst에서 74%, 64라인에서 66%:
**burst 32에서 이미 1/4이 버려진다 → 한계는 L2 queue(32–48)가 아니라 L1D fill buffer(16)** 쪽이다(prefetcht1도 LFB를 거친다). drip은 사이트당 ≤ 8이어야 한다.
(3) twin이 base보다 0.8% 느리고 명령이 +4.3%: 래퍼(rdtsc ×2)와 표 루프의 비용이 이득의 절반을 먹는다 → inline 형태가 필요하다. (4) 요청당 발행 ≈ 450–670 라인 = 첫 접근의 12–18%, 그중 절반이 fill → miss −4%, 사이클 −1.4%.

### 7-4. Round 2 — dense drip를 pass plan으로 (바이너리 wsp = wsm + `PREFETCHIT_COLD_PLAN=plan_pass.json`, preload 없음), 3회, R=600
plan: 205 사이트(경로 위 exe 함수 진입, d=8, Dmax=24, k=6) / 1,260 타깃(direct 970 + GOT 290) → 실제 계측 **106 사이트 / 1,214 prefetch**
(나머지 99 사이트는 정적 아카이브(thrift 13, jaeger 14, libstdc++ 36, 기타 35)의 함수라 서비스 빌드에서 계측 불가). 첫 접근 커버는 p ≥ 0.5 라인의 ≈30%.

| arm | 요청당 사이클 | vs base | L2I MPKI | 명령 | SWPF 실제 fill | L2 도달 SWPF/요청 |
|---|---:|---:|---:|---:|---:|---:|
| base (wsm) | 359.5 k | 1.000x | 86.2 | 1.000x | – | – |
| **wsp** | 349.7 k | **1.028x** | 84.0 | **+1.4%** | 41% | ≈800 |
| wsp nop twin | 365.5 k | 0.984x | 87.4 | +1.4% | – | – |

읽는 법: (1) 사이트당 ≤ 6라인의 inline drip는 round 1의 표 방식보다 명령 비용이 1/3이고 이득은 2배 — **twin 대비 1.045x, base 대비 1.028x**.
(2) MPKI는 −2.5%인데 사이클은 −2.8%: 없앤 miss가 retire 경로의 첫 접근 miss(프론트엔드를 실제로 세우는 것)이고, 집계 miss의 나머지 2/3(wrong-path)는
사이클에 덜 비싸다는 §7-2의 해석과 맞는다. (3) 발행의 70–80%가 L2에 도달(k ≤ 6이면 LFB 드롭이 적다), 도달분의 41%가 fill.
(4) 남은 것: 커버 30% → 아카이브 함수를 사이트로 쓰려면 아카이브를 pass로 다시 빌드해야 한다(round 4, `rebuild_deps_static.sh` + 같은 plan).

### 7-5. Round 3 — 계측 가능한 사이트만으로 plan을 다시 짜고 창을 넓힘 (wsp2: 107 사이트, d=8, Dmax=32, k=8 → 1,596 prefetch), 3회
| arm | 요청당 사이클 | vs base | L2I MPKI | 명령 | SWPF 실제 fill | L2 도달 SWPF/요청 |
|---|---:|---:|---:|---:|---:|---:|
| base (wsm) | 359.2 k | 1.000x | 86.5 | 1.000x | – | – |
| **wsp2** | 348.4 k | **1.031x** | **80.5** | +2.1% | 41% | ≈1,000 |
| wsp2 nop twin | 361.3 k | 0.994x | 90.5 | +2.1% | – | – |

round 2와 같은 사이트 집합에 k·Dmax를 키운 것만으로는 1.028x → 1.031x(MPKI −2.5% → −7%): 사이트가 없는 구간(libc 362라인짜리 스레드 생성,
jaeger 내부)이 남아 있어 **사이트 집합이 한계**다. → round 4 = 아카이브를 pass로 재빌드해 thrift/jaeger/mongoc 함수도 사이트로.

### 7-7. 두 질문에 대한 답 (데이터 기준)

**run은 언제 시작하는가 — 스레드가 스폰될 때인가?** 아니다(워커만 예외). run 시작 = 이 스레드가 **블로킹 호출에서 돌아오는 순간**이다.
movie-id 요청 하나에 run이 12.7개인데, 연결 스레드(thread-per-connection이라 연결당 한 번 스폰되고 그 뒤로는 재사용)의 run은 recv 복귀(새 요청·memcached 응답),
futex 복귀(future join) 뒤에 시작하고, 요청마다 `std::async`가 만드는 워커 스레드 3개만 **스레드 시작(clone)**이 곧 run 시작이다. 트레이스에서는
`sched_switch`(switch-in)가 정확한 경계이고 hook은 PT 재개 지점의 libc 심볼(recv/poll/futex/clone)로 판정한다. 런타임에서는 (a) 블로킹 호출 래퍼의
rdtsc 차이(> 20 k cycle이면 잠들었던 것) — 요청이 짧아 안 잔 recv도 있으므로 무조건 발행하면 SWPF_HIT만 늘어난다, (b) 워커 스레드는 람다 첫 줄의 mark,
(c) 선점(involuntary switch)은 못 본다 — 이번 트레이스에서 hook을 못 정한 run이 199/761인데 대부분 워커의 종료 run이고, 선점 재개는 드물다(cs 1.7만/초에
요청 12.7 run × 600 = 7.6천/초의 자발적 switch가 대부분). 더 정확한 판정은 커널만 안다(B-3).

**stream보다 더 intelligent한 방법은 없는가?** 이번 데이터가 가리키는 순서대로:
1. **후속 run 예약(N 큐)** — 이미 구현. mark k가 "다음 wake에서 쓸 목록"을 예약하면 wake 시점에 hook만 아는 것보다 목록이 정확하다(m1→m4→m0→m9가 74–98%).
   RDIP의 "서명 전이 시 다음 서명의 miss 집합"을 스레드-로컬 상태로 흉내 낸 것이다.
2. **cold 여부를 재서 발행(rdpmc 게이트)** — rdtsc 차 대신 L2 code miss 카운터(`rdpmc`, 사용자 모드 허용 시 ~30 cycle)를 run 시작 후 첫 mark에서 읽어
   "이 run이 실제로 cold한가"를 판정하고, 따뜻하면(L2 hit 위주) 발행을 끈다. interleaved라도 같은 스레드가 연속으로 잡히면 따뜻한 run이 섞이는데(SWPF_HIT 59%),
   그 비용을 없앤다. 선점 재개도 잡는다.
3. **표 기반 replay(소프트웨어 Jukebox)** — 목록을 코드가 아니라 데이터로 두고 run 종류 id로 인덱스: 코드 바이트를 안 늘리고 프로파일 교체가 재컴파일 없이
   된다. 다만 사이트가 성긴 곳(라이브러리 내부)에서는 한 사이트가 많이 내야 하고 LFB(16)에 막힌다 → round 1(1.014x)이 그 한계다. inline drip(1.028–1.031x)이
   같은 정보로 더 낸 이유는 **발행 지점이 촘촘해서 사이트당 ≤ 8라인**이기 때문이지 정보가 달라서가 아니다.
4. **BTB까지 데우는 것** — 집계 miss의 2/3가 첫 접근이 아닌 wrong-path fetch로 보인다(§7-2). prefetcht1로는 못 건드리고, `prefetchit0/1`이 frontend starvation에서
   무엇을 하는지(사용자 지적)를 이 regime에서 같은 plan으로 재야 한다(pass의 mnemonic 옵션으로 arm 하나 추가). 소프트웨어로 BTB를 데우는 유일한 방법은
   "그 코드를 실제로 실행"하는 것이라 없다 — Ignite류 HW 또는 B-3의 커널 switch-in 엔진의 몫.
5. 커널 switch-in prefetch(B-3)는 wake 이전 리드타임과 선점 재개까지 덮는 유일한 소프트웨어 옵션으로 남는다.

### 7-6. Round 4 — 아카이브(thrift/jaeger/opentracing/yaml/mongoc/bson/hiredis/redis++)를 pass+plan으로 재빌드 (이미지 `dsb-deps-ws3`, 바이너리 wsp3: 138 사이트 중 133 계측, 1,718 prefetch), 3회
| arm | 요청당 사이클 | vs base | L2I MPKI | 명령 | SWPF 실제 fill | L2 도달 SWPF/요청 |
|---|---:|---:|---:|---:|---:|---:|
| base (wsm) | 358.1 k | 1.000x | 86.1 | 1.000x | – | – |
| **wsp3** | 342.3 k | **1.046x** | **77.6 (−10%)** | **+1.6%** | 30% | ≈1,880 |
| wsp3 nop twin | 356.8 k | 1.003x | 85.3 | +1.9% | – | – |
| wsp2 (같은 라운드 재측정) | 347.3 k | 1.031x | 81.0 | +1.8% | 42% | ≈1,000 |

정리(모두 base = wsm, R=600, 3회 중앙값): **표 방식 wake+mark 1.014x → inline drip(서비스 오브젝트 사이트) 1.028–1.031x → 아카이브 사이트 포함 1.046x**,
명령 +1.6%, MPKI −10%. 사이트 집합을 넓힐수록 비례해서 늘었고 아직 포화가 아니다(남은 미커버: libc 안의 긴 구간 — 스레드 생성 362라인, jaeger·boost::log 내부,
mark 없는 m0 run). fill 비율이 47 → 30%로 내려간 것은 따뜻한 run(같은 스레드가 연속으로 잡힌 경우)에서도 발행하기 때문 → §7-7의 rdpmc 게이트가 다음 비용 절감.

### 7-8. 남은 일 (우선순위)
1. 커버 확장: (a) libc 구간은 앞선 exe 사이트가 더 내도록 "gap filler" k=12 허용(LFB 16 안), (b) 워커 종료 run·m0 run에 mark 추가, (c) compose-review·socialNetwork compose-post에 같은 파이프라인.
2. rdpmc 게이트(따뜻한 run에서 발행 억제)와 prefetchit1 arm(같은 plan, mnemonic만 교체).
3. 이 결과의 정식 보고: `feedback-reporting-format` 규칙대로 movie-id 한 행(1.046x, MPKI 86.1→77.6, +1.6% 명령, interleaved pool-8 C6 off R=600). 5회 반복으로 확정.
4. 소스 mark 패치(`ws_patch_src.sh apply`)는 DeathStarBench 트리에 **적용된 상태**다(모든 arm의 base가 wsm). 다른 서비스 빌드 전에 `revert`.

### 7-9. Round 5 — coverage·overhead·lead를 한꺼번에 (2026-09-21 오후, 3회, R=600; 아카이브 pass 빌드는 arm마다 임시 이미지)
플래너 변경: (a) mark 없는 run을 "직전 mark + p"로 라벨(워커의 RPC 응답 뒤 run, 메인 스레드의 futex run — 첫 접근의 37%가 여기 있었다; 목록 일치 83–85%),
(b) 128 B 페어 병합(MSR 0x1a4 = 0: adjacent-line prefetcher 켜짐 확인), (c) 다음 사이트가 Dmax 밖이면 그 사이트가 12개까지 내는 gap filler,
(d) fall-through로 들어간 라인(첫 접근의 53%) 제외 옵션, (e) d를 페어 단위 16(=32라인)까지.

| arm | 내용 | 요청당 사이클 | vs base | MPKI | 명령 |
|---|---|---:|---:|---:|---:|
| base (wsm) | | 359.0 k | 1.000x | 87.0 | – |
| wsp3 (round 4 arm 재측정) | 라벨 없음, 페어 없음, d=8 | 341.9 k | **1.050x** | 77.7 | +1.9% |
| p5a | 라벨 + 페어 + gap 12, d=8 페어 | 342.4 k | 1.048x | 78.3 | +2.4% |
| p5b | p5a + fall-through 제외 | 349.8 k | 1.026x | **77.2** | +1.6% |
| p5c | p5a, d=16 페어(32라인 앞) | 341.8 k | 1.050x | 79.2 | +2.2% |
| p5a nop twin | | 359.2 k | 0.999x | 86.2 | +2.3% |

읽는 법: (1) **페어 병합은 사이클을 못 줄인다** — miss는 더 줄지만(adjacent-line이 짝을 가져옴) 짝은 첫 라인의 fill 뒤에 오므로 150 cycle 뒤에 필요한
라인에는 늦다. (2) **fall-through 라인을 빼면 MPKI는 가장 낮은데 가장 느리다**: HW next-line은 X를 가져올 때 X+1을 요청하므로 miss 계수에는 안 잡혀도
프론트엔드는 기다린다. MPKI가 아니라 사이클이 목적함수라는 것을 다시 확인. (3) d를 32라인으로 늘려도 같은 성능 → 리드는 8라인(≈1,200 cycle)에서 이미 충분하고,
사이트 앞 d라인이 비는 손실과 상쇄된다. (4) 남은 손실은 coverage: 사이트가 없는 긴 구간(libc 스레드 생성 362라인, boost::log, libmemcached 내부)과 run 시작부.

### 7-10. Round 6 — 페어 없이 라벨·gap filler·리드만 (3회)
| arm | 내용 | vs base | MPKI | 명령 |
|---|---|---:|---:|---:|
| base (wsm) | | 1.000x (358.4 k) | 86.8 | – |
| wsp3 (재측정) | 133 사이트, d=8 | 1.037x | 76.9 | +1.9% |
| p6a | + 라벨(mark 없는 run) + gap 12, d=8 → 155 사이트, 1,982 pf | 1.028x | 75.6 | +2.3% |
| p6b | p6a, d=12 | 1.036x | 77.2 | +2.2% |
| p6c | p6a, d=16 | **1.043x** | 76.2 | +2.2% |
| p6a nop twin | | 0.994x | 85.9 | +2.2% |

wsp3의 세 라운드 값 1.046 / 1.050 / 1.037x가 보여주듯 run-to-run 폭이 ±1%라, 사이트를 133 → 155개로 늘리고(발행 1,718 → 1,982) 리드를 8 → 16라인으로 바꾼 차이는
모두 그 안이다. **이 계열은 movie-id에서 1.04–1.05x에서 포화**한다. 실제 fill이 발행의 26–30%에 머무는 이유는 늦어서가 아니라(d=16도 같음) 나머지 70%가 이미
L2에 있어서다 — adjacent-line prefetcher(128 B 짝)와 L2 streamer(fall-through 53%)가 먼저 가져온 라인, 그리고 같은 코어에 연속으로 잡힌 따뜻한 run.
즉 HW가 못 가져오는 라인(불연속 첫 라인)만이 SW의 몫이고, 그 몫의 상당수는 이미 덮었다. 남은 축: prefetchit1(round 7), run 시작부의 stage 0(round 8), 그리고
집계 miss의 2/3를 차지하는 wrong-path fetch는 BTB의 문제라 prefetch로는 닿지 않는다.

### 7-11. Round 7 — 라이브러리 타깃의 몫 (3회)
prefetchit1 비교를 위해 direct(exe 심볼) 타깃만 남긴 plan(GOT 타깃 302개 제거)을 만들었다. prefetchit1 arm은 아카이브(-fPIC) 모듈에서 어셈블러가
"'prefetchit1' only supports RIP-relative address"로 거부해 실패 → exe 모듈만 계측하는 7b로 다시 잰다. prefetcht1 direct-only arm은 유효:

| arm | vs base | MPKI | 명령 |
|---|---:|---:|---:|
| base (wsm) | 1.000x (362.5 k) | 87.6 | – |
| p6c (재측정) | **1.059x** | 78.0 | +2.4% |
| p7t = p6c 설정, GOT(libc/libmemcached) 타깃 없음 | 1.033x | 79.8 | +1.7% |

libc·libmemcached 라인(발행의 ~25%)이 이득의 절반(≈2.5%p)을 낸다 — 09-17의 "libc 타깃을 빼면 이득 2/3 소실"과 같은 방향. glibc를 정적으로 링크하면
이 라인들도 RIP-relative(7 B, prefetchit 가능)가 되므로 다음 후보다(NSS 주의).

### 7-12. Round 7b — prefetchit1 vs prefetcht1, 같은 사이트·같은 타깃 (exe 모듈만 계측, direct 타깃 1,296개, 3회)
| arm | vs base | MPKI | 명령 | SWPF 실제 fill |
|---|---:|---:|---:|---:|
| base (wsm) | 1.000x (358.0 k) | 84.8 | – | – |
| p7t2 = prefetcht1 | **1.040x** | 82.8 | +1.4% | 45% |
| p7i2 = prefetchit1 (RIP-relative, 인코딩 확인) | **0.982x** | 87.7 | +1.6% | – (SWPF 계수 0) |

같은 1,296개 자리에서 prefetcht1은 +4.0%, prefetchit1은 −1.8%다. prefetchit1은 L2 SW-prefetch 이벤트를 전혀 만들지 않고 MPKI를 오히려 올린다(코드 바이트·issue 비용만
남음) — 09-17 Verilator(0.887x)와 같은 결론이 IPC 0.33의 frontend-starved 서비스에서도 반복됐다. 이 호스트에서 prefetchit0/1은 우리가 필요한 L2 fill을 만들지 않는다.

### 7-13. Round 8 — run 시작부(stage 0)를 LD_PRELOAD로 얹기 (p9 = p6c 설정 + PIC 사이트의 burst 바이트 보정; 3회)
| arm | vs base | MPKI | 명령 |
|---|---:|---:|---:|
| base (wsm) | 1.000x (358.7 k) | 86.6 | – |
| p6c (재측정) | 1.043x | 76.2 | +2.2% |
| p9 | 1.038x | 76.7 | +2.2% |
| p9 + stage 0 (wake마다 16라인, mark는 다음 run 예약) | 1.013x | 76.9 | +4.0% |
| p9 + stage 0 32라인 | 1.023x | 77.7 | +4.8% |
| p9 + stage 0 16 nop twin | 1.019x | 77.5 | +4.2% |

stage 0이 더한 fill은 요청당 ≈50라인(+0.5 M/30 s)뿐이고 래퍼(rdtsc ×2 + 표 루프)의 명령 +1.8%가 그것을 지운다. **run 시작부는 inline으로만 의미가 있다**:
pass에 "블로킹 호출 복귀 직후" 사이트 종류(post-call)를 넣어 `recv` 뒤에 burst를 두는 것이 남은 구현 항목이다(현재 함수 진입 사이트는 recv *앞*에 놓여 잠들기 전에 발행된다).
PIC 사이트의 k 보정(p9)은 차이가 없었다(jaeger 사이트의 burst는 실제로 컸지만 그 함수 안쪽 타깃이 드물다).

### 7-14. 세 축의 결론 (2026-09-21, movie-id interleaved R=600, 모두 3회 중앙값)
| 라운드 | 무엇을 바꿨나 | 최선 arm | vs base | MPKI | 명령 |
|---|---|---|---:|---:|---:|
| 1 | LD_PRELOAD wake burst + mark(표 방식) | ws64 | 1.014x | 84.4→81.0 | +4.5% |
| 2–3 | inline drip, 서비스 오브젝트 사이트 | wsp2 | 1.031x | 86.5→80.4 | +2.2% |
| 4 | + 아카이브 사이트(thrift/jaeger) | **wsp3** | **1.046x** (재측정 1.050 / 1.037) | 86.1→77.6 | +1.6–1.9% |
| 5 | coverage: 라벨·페어·gap / overhead: fall-through 제외 / lead: d 16 | p5c | 1.050x | 87.0→79.2 | +2.2% |
| 6 | 페어 없이 라벨·gap, d 8/12/16 | p6c | 1.043x (재측정 1.059 / 1.043) | 86.8→76.2 | +2.2% |
| 7 | GOT(libc) 타깃 제거 | p7t | 1.033x | 87.6→79.8 | +1.7% |
| 7b | prefetchit1 (같은 자리) | p7i2 | **0.982x** | 84.8→87.7 | +1.6% |
| 8 | + stage 0 (preload) | p9s32 | 1.023x | 86.6→77.7 | +4.8% |

- **coverage**: 사이트 107 → 133 → 155개, 발행 1,600 → 1,980으로 늘려 MPKI는 80 → 76까지 내려가지만 사이클은 1.04–1.05x에서 멈춘다. 늘어난 fill이 임계 경로의 miss가 아니거나
  (워커 종료 run), HW prefetcher가 어차피 가져올 라인(페어 짝, fall-through)이기 때문. 실제 fill은 발행의 26–30%로 일정.
- **overhead**: 명령 +1.6–2.4%, twin 비용 0–1%. 페어 병합·fall-through 제외로 발행을 25–35% 줄여도 이득이 같이 줄거나(7b: −1.4%p) 그대로라 남는 여지가 없다.
  표 방식/래퍼(preload)는 +2%씩 비싸서 항상 손해.
- **lead**: d = 8 → 16 → 32라인(≈1.2 k → 4.8 k cycle)에서 차이 없음. 리드는 이미 충분하고, 늦어서 못 잡는 miss가 아니라는 뜻. 반대로 d를 키우면 run 앞부분이 비는 손실이 생긴다.
- 그래서 이 워크로드의 in-process 상한은 **약 1.05x**로 보는 것이 맞다. 그 이유는 §7-2: 집계 miss 10 k/요청 중 첫 접근은 3.7 k뿐이고 나머지는 cold BTB의 wrong-path fetch라
  prefetch로는 닿지 않는다(prefetchit1도 아님). 다음 단계는 (1) post-call 사이트로 run 시작부를 inline으로, (2) glibc 정적 링크(GOT → RIP-relative, 7 B), (3) 다른 서비스
  (compose-review 38 MPKI, compose-post 42)로 같은 파이프라인, (4) 5회 반복으로 wsp3/p6c 확정치. BTB 쪽은 B-3(커널 switch-in)와 HW의 몫.

### 7-15. 왜 headroom 대비 이득이 작은가 — 카운터 분해와 미커버 분석 (2026-09-21 15:00, R=600, 25 s 창)
**프론트엔드 분해 (base wsm → best p6c, 서비스 프로세스 `:u`)**
| 항목 | base | p6c |
|---|---:|---:|
| IPC | 0.336 | 0.355 |
| L2I MPKI | 87.5 | 77.8 |
| **BACLEARS (BTB miss → 재조향) /kI** | **38.0** | 38.7 |
| 분기 예측 실패 /kI (분기 208/kI의 11%) | 23.5 | 23.0 |
| 사이클 중 icache data stall / tag stall | 31% / 15% | 28% / 14% |
| 사이클 중 clear-resteer | 25% | 21% |
| 사이클 중 **ITLB walk** | 10% | 8% |
| Top-Down L1: retiring / bad-spec / fe-bound / be-bound | 13 / 8 / **53** / 27% | 13 / 8 / 52 / 28% |
| Top-Down: fetch-latency / br-mispredict | 45% / 7% | 44% / 8% |
(FRONTEND_RETIRED.*와 INT_MISC.UNKNOWN_BRANCH_CYCLES는 이 커널/PMU에서 0을 반환해 못 썼다. BACLEARS는 GNR 인코딩 0x60/0x01.)

읽는 법: 요청 하나(119 k 명령, 358 k cycle)에 **BTB miss 재조향 4,500회, 분기 예측 실패 2,800회, L2I miss 10.4 k, ITLB walk가 36 k cycle**이다.
프론트엔드가 slot의 53%를 잃는데 그중 우리가 건드리는 것은 "L2에서 놓친 라인의 지연"뿐이고, 그것도 cold BTB 뒤에 숨는다: 26 명령마다 BTB miss가 나면 FDIP가
앞서 못 가고, 분기가 *실행*된 뒤에야 타깃 fetch가 시작된다. 우리의 fill은 그 fetch를 L3 지연(~100 cycle) 대신 L2 지연(~15 cycle)으로 줄일 뿐 재조향 비용은 그대로다.
그래서 miss 11%를 없애고 5%를 얻었고, retire 경로의 첫 접근 전부(집계 miss의 37%)를 없애도 10–15%가 상한이다. 백엔드 27%(wake 뒤 cold한 **데이터**: 스택·힙·클라이언트
구조체)와 ITLB 10%는 명령 prefetch의 범위 밖이다.

**트레이스 쪽: plan이 못 덮는 첫 접근 (p6c 설정, run 가중)**
| 분류 | 전체 첫 접근 중 |
|---|---:|
| plan이 덮음 | 42% |
| gap — Dmax 안에 계측 가능한 사이트가 없음 | 24% |
| site-cap — 사이트는 있으나 k(8)/gap-k(12) 소진 | 12% |
| run-start — 첫 사이트 + d 이전 | 12% |
| p < 0.5 (run마다 다른 라인) | 10% |

코드군별(전체 첫 접근 중): **libc 32%**(덮음 10, gap 9.5, run-start 5.7) · jaeger 23%(덮음 11.5) · libstdc++ 13%(5.6) · thrift 9%(6.8) · boost 6%(2.2) ·
**libmemcached 6%(0.1 — 거의 전부 미커버)** · 서비스 코드 4%. 즉 못 덮는 것은 "사이트를 심을 수 없는 코드(libc·libmemcached·boost·libstdc++ 아카이브)와 run 시작부"이고,
사이트 밀도가 아니라 사이트 *가능 지역*의 문제다. 이것을 넘으려면 pass가 exe 쪽 call 직후(post-call)에 burst를 놓거나 glibc를 정적 링크해야 한다.

**다른 방식의 후보 (측정된 headroom 순)**
1. **BTB/분기 상태** (재조향 25% + bad-spec 8%): 소프트웨어 prefetch로는 불가. 코드 레이아웃(taken branch 수 자체를 줄임)은 이 논문의 범위 밖, HW record/replay(Ignite)나
   커널 switch-in 엔진(B-3)의 몫. 유일한 SW 우회는 wake 직후 요청 경로를 "실제로 실행"하는 warm-up인데 비용이 요청 자체와 같다.
2. **데이터 쪽 cold miss** (be-bound 27%): 같은 run 단위 분석을 PEBS load 샘플로 확장해 run 종류별 첫 접근 *데이터* 라인(연결 버퍼, 프로토콜 객체, 클라이언트 풀)을
   같은 사이트에서 prefetch — Brown & Tullsen의 working-set 이동을 소프트웨어로. 명령 쪽과 같은 도구로 되고 headroom이 더 크다.
3. **ITLB** (walk 10% → 8%): 코드 2 MB 페이지. 이 커널은 `CONFIG_READ_ONLY_THP_FOR_FS`가 꺼져 있어 madvise로는 안 되고, text를 익명 THP로 복사·remap하는
   hugetext 방식이 필요(exe text 2.2 MB, libc 1.6 MB → 각 1–2 페이지). `ws/hugetext.c`는 madvise 판(이 커널에서 무효)이라 remap 판으로 바꿔야 한다.
4. **워크로드 자체**: 요청마다 `std::async` 스레드 3개(clone 시작 run 3개 + pthread_create 경로 362 라인 = m4 run의 40%). 스레드 풀이면 run이 12.7 → ~7개로 준다.
   prefetch 결과는 아니지만 이 트레이스가 드러낸 가장 큰 단일 비용이다.
5. 남은 prefetch 개선: post-call 사이트(run-start 12% + libmemcached 6%), glibc 정적 링크(libc 32% 중 gap/run-start 15%), gap-k 상향(site-cap 12%).

### 7-16. "MPKI를 왜 못 줄이나" — 집계 miss의 구성 (2026-09-21 15:20)
같은 바이너리(wsm), 같은 부하(R=600)를 alone 배치(movie-id 전용 코어 30–31)와 interleaved(pool 0–7)에서 잰 값:

| 요청당 (119 k 명령) | alone | interleaved | 배율 |
|---|---:|---:|---:|
| 사이클 | 120 k | 358 k | 3.0× |
| L2I miss | 420 | 10,400 | 25× |
| **BACLEARS (BTB miss 재조향)** | 900 | **4,500** | 5× |
| **분기 예측 실패** | 300 | **2,800** | 9× |
| ITLB walk 사이클 비중 | 4% | 10% | 2.5× |
| icache data stall / resteer 사이클 비중 | 16% / 7% | 31% / 25% | |
| Top-Down fe-bound / be-bound | 32% / 40% | 53% / 27% | |

PT(완전 트레이스: 요청당 taken branch 13.6 k ≈ retire 분기 24.7 k의 55%)로 센 **실행 라인의 run별 첫 접근은 요청당 4,540개**(p 무관 전부)다. 집계 miss 10,400개 중
실행 라인이 낼 수 있는 miss는 최대 이 4,540개(≈38 MPKI)이고, **나머지 ≥5,900개(≈50 MPKI)는 프로그램이 실행하지 않는 라인의 fetch**다: taken branch 뒤 fall-through
로 fetch되는 그림자 라인(PT 추정 요청당 +1 라인 1,500, +2 라인 1,300)과 재조향 7,300회(BAClear 4,500 + mispredict 2,800) 뒤의 wrong-path fetch. 이 miss는 어떤
첫 접근 목록에도 없으므로 prefetch로는 못 잡는다. alone에서는 같은 코드가 재조향 5–9배 적게 나므로 이 miss 덩어리는 **cold BTB/BPU가 만드는 것**이다.

잡을 수 있는 4,540개 중: plan이 덮은 42%(1,900라인)에서 miss 1,150개가 사라졌다(덮은 라인의 61%; 나머지는 HW가 이미 가져왔거나 LFB에서 버려짐) → MPKI 87.5 → 77.8.
못 덮은 58%는 §7-15의 gap(libc·libmemcached) 24% / site-cap 12% / run-start 12% / p<0.5 10%. post-call 사이트와 glibc 정적 링크로 이 중 절반쯤을 더 잡으면 MPKI ≈ 65,
사이클 +3–4%p가 이 방식의 끝이다. (FRONTEND_RETIRED.L2_MISS로 retire 경로 miss를 직접 세면 확정되는데 이 커널/PMU에서는 0을 반환한다.)

### 7-17. Round 10 — 다른 종류의 타깃 (3회, base 대비)
| arm | 내용 | vs base | MPKI | 명령 |
|---|---|---:|---:|---:|
| base (wsm) | | 1.000x (357.1 k) | 87.0 | – |
| p6c (재측정) | | **1.046x** | 77.4 | +2.4% |
| p10a | + 페이지 첫 라인 3개/사이트를 64라인 앞서 (ITLB) | 1.033x | 76.7 | +2.6% |
| p10b | + 그림자 라인(taken branch 뒤 fall-through, 미실행) | 1.045x | **75.7** | +3.3% |
| p10c | gap 사이트 k 24, 도달 2×Dmax (libc 구간) | 1.040x | 76.5 | +2.4% |

페이지 단위 선행 prefetch는 라인 타깃을 밀어내 오히려 손해, 그림자 라인은 MPKI를 1.7 더 내리지만 사이클은 그대로(그 fetch는 기다리는 것이 아니므로), libc 구간용
큰 gap filler도 차이 없음. 라운드 4–10을 통틀어 **1.04–1.05x 밖으로 나가는 arm이 없다.**

### 7-18. 데이터 쪽 cold miss — PEBS load 샘플 (wsm, interleaved, 10 s; 672 샘플뿐 — raw `mem-loads,ldlat=` 이벤트가 이 PMU에서 지연 필터를 안 받았고 스레드 대부분이 샘플되지 않아 정성적 그림만)
지연 가중치 기준: 익명 소영역(malloc arena·TLS) 32%, **maps 스냅샷에 없는 영역 29%**(요청마다 만들었다 지우는 워커 스레드의 스택·TLS), brk 힙 11%, exe rodata 7%,
스레드 스택 6%(중앙값 5 cycle = 따뜻함). 상위 load 사이트: jaeger SpanContext/Span 생성자, malloc, pthread_create(112 cycle), `_dl_allocate_tls_init`.
즉 wake 뒤 cold한 데이터의 대부분은 **새로 할당되는 메모리**(스레드 스택·TLS·새 span 객체)라 주소를 미리 알 수 없고, 재사용되는 스레드별 구조체(스택 상단)는 이미
따뜻하다. 데이터 prefetch 목록으로 잡을 안정적 타깃이 없다 → 이 축은 prefetch가 아니라 스레드 풀·객체 풀(할당 자체를 없애는 것)의 영역. arm은 만들지 않았다.

### 7-19. Round 11 — run 시작부의 post-call 사이트, 그리고 trace 없는 static plan (3회)
pass에 사이트 종류를 추가했다: `"<fn>@n"` 키 + `"after_call": <callee>, "nth": n` → 그 호출 **직후**에 burst(`PrefetchITPass.cpp`, `after_call_missing` 계수).
run_paths가 run 종류별로 "재개 지점에서 처음 돌아오는 계측 가능한 exe 프레임"을 찾고(`entry_<type>.tsv`: TSocket::read←poll, handler←memcached_get,
_M_complete_async←pthread_once, ClientPool::Pop←pthread_mutex_lock, sweepQueue←pthread_cond_clockwait, write_partial←send …), 플래너가 그 호출 뒤에
run의 첫 12라인을 놓는다(`--post-call 12`; 9개 사이트 모두 실현, objdump로 `call poll` 직후 burst 확인).
static plan(`ws_static_plan.py`): 바이너리만으로 process_<Method>·async 람다에서 **직접 호출 그래프**를 DFS해 "정적 첫 접근 순서"를 만들고 같은 d/k로 배정.

| arm | vs base | MPKI | 명령 | fill |
|---|---:|---:|---:|---:|
| base (wsm) | 1.000x (357.3 k) | 87.7 | – | – |
| p6c | 1.047x | 76.6 | +2.5% | 27% |
| **p11a = p6c + post-call 9곳** | **1.053x** | 77.9 | +2.5% | 26% |
| p11a nop twin | 1.001x | 83.9 | +2.8% | – |
| pstat (static, 62 사이트 / 375 타깃) | 1.002x | 83.0 | −0.8% | 41% |
| pstat nop twin | 1.010x | 85.3 | −0.8% | – |

post-call 사이트는 +0.6%p(노이즈 안이지만 기대 방향). **static은 0**: 직접 호출 그래프가 148개 함수·620라인에서 끊긴다 — 경로의 호출 대부분이 thrift 가상 함수·
std::function·jaeger 콜백이라 정적으로는 따라갈 수 없고, 동적 첫 접근 4,540라인의 1/7만 본다(fill 41%로 정확하지만 양이 없다). 이 부류에서 static이 되려면
클래스 계층 분석(가상 호출의 모든 구현체를 후보로)이 pass 안에 있어야 하고, 그래도 "실행 순서"는 못 만든다.

### 7-20. Round 13 — static의 두 번째 판: pass의 plan-free 모드 (모든 직접 call 자리에 callee 진입 burst, 아카이브 포함; 3회)
| arm | 발행 수(정적) | vs base | MPKI | 명령 |
|---|---:|---:|---:|---:|
| base (wsm) | – | 1.000x (353.4 k) | 86.2 | – |
| p11a (trace-guided, 참고) | 2,175 | 1.035x | 77.1 | +2.4% |
| pstat2 = `PREFETCHIT_CALLEE_BURST_LINES=4` | 4,876 | 1.015x | 83.3 | −1.2% |
| pstat2 nop twin | | 1.011x | 83.4 | −0.9% |
| pstat3 = callee burst 8 | 9,752 | 1.003x | 84.4 | −1.0% |

두 static(호출 그래프 DFS plan 1.00–1.03x, callee 진입 burst 1.00–1.015x) 모두 twin과 구분되지 않는다. 이유는 같다: (1) 사이트가 callee의 *진입만* 겨누므로
리드가 call 한 개 분(수십 명령)이고 callee 몸통·라이브러리 내부는 못 본다, (2) 경로의 대부분이 가상 호출·std::function·jaeger 콜백이라 정적으로는 다음에
무엇이 실행될지 모른다, (3) 이 부류의 핵심 정보인 "run이 어디서 시작하는가"(재개 지점)는 정적으로 존재하지 않는다. capacity 부류에서 static seq가
Verilator에 통한 것은 레이아웃 순서 = 실행 순서였기 때문이고, 서비스 코드에서는 그 등식이 성립하지 않는다 → **B 부류의 static은 trace-guided의 1/5 이하**.

### 7-21. 최종 확정치 (2026-09-21 18:05, movie-id interleaved pool-8 C6 off 2 GHz R=600, 깨끗한 5회 중앙값; 첫 패스의 2–4회는 디스크 풀로 perf 파일이 잘려 제외)
| arm | 요청당 사이클 | **vs base** | L2I MPKI | 명령 | SWPF 실제 fill |
|---|---:|---:|---:|---:|---:|
| base (wsm, prefetch 없음) | 355.2 k | 1.000x | 86.6 | – | – |
| wsp3 (dense drip, 아카이브 사이트, d=8) | 340.3 k | 1.044x | 76.7 | +2.0% | 30% |
| p6c (+ 라벨·gap, d=16) | 342.8 k | 1.036x (n=4) | 76.2 | +2.5% | 27% |
| **p11a (p6c + run 시작부 post-call 사이트 9곳)** | **337.1 k** | **1.054x** | **76.9** | **+2.8%** | 27% |
| pstat (trace 없는 static plan) | 353.1 k | 1.006x | 82.6 | −0.6% | 41% |

보고용 한 행: **movie-id interleaved 1.054x, MPKI 86.6 → 76.9, 명령 +2.8%** (p11a). static은 1.006x.

**하루의 결론 (라운드 1–14, 모두 같은 세팅)**
1. 이 부류에서 소프트웨어 명령 prefetch의 in-process 상한은 **≈1.05x**다. 목록·리드·발행 형태를 어떻게 바꿔도 1.04–1.06x 안에서 움직였다.
2. 그 이유는 miss의 구성이다: 요청당 집계 miss 10.4 k 중 실행 라인의 첫 접근은 4.5 k뿐이고, 나머지 ≥5.9 k는 cold BTB(재조향 4,500회/요청, alone의 5배)가 만드는
   실행되지 않는 라인의 fetch다. 잡을 수 있는 4.5 k의 42%를 덮어 1,150개를 없앴고, post-call로 run 시작부를 더해 1.054x. 나머지 잡을 수 있는 miss는
   사이트를 심을 수 없는 코드(glibc·libmemcached·배포판 아카이브)에 있다.
3. 무엇이 안 되는지도 확정됐다: 128 B 페어(짝이 늦음), fall-through 제외(HW next-line은 늦다), 페이지 선행(라인을 밀어냄), 그림자 라인(MPKI만 내림), d>16(run 앞이 빔),
   preload stage 0(래퍼 비용), prefetchit1(−1.8%), static plan/callee burst(0–1%: 가상 호출·std::function 뒤를 못 보고 재개 지점을 모름), 데이터 prefetch(cold 데이터가
   새 할당 메모리라 타깃이 없음).
4. 남는 headroom은 BTB/BPU(재조향 25% + bad-spec 8%), 데이터(be-bound 27%), ITLB(10%)이고 모두 prefetch 명령 밖이다: 커널 switch-in(B-3)·HW record/replay(ISA 제안)·
   text 2 MB 페이지(remap)·스레드 풀(요청당 스레드 3개 생성이 run 12.7개 중 3개와 libc 362라인을 만든다)이 그 답이다.
