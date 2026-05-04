# prefetch_test.c 설명과 PREFETCHI/PREFETCHT 비교

작성일: 2026-05-03
소스: `microbench/src/prefetch_test.c`
주요 실행 파일: `microbench/src/prefetch_test`

## 한 줄 요약

이 benchmark는 `bar`, `foo`, `baz`라는 target code가 instruction cache 쪽에서 차가운 상태일 때, target 실행 직전에 prefetch를 넣으면 timed target 실행 시간이 줄어드는지 본다. 지금 버전은 code prefetch인 `PREFETCHI`와 data prefetch인 `PREFETCHT0`를 같은 target code address에 대해 나란히 실행해서 비교한다.

중요한 결론은 이렇다.

- `PREFETCHT0`도 code address를 data처럼 prefetch하면 종종 좋아진다. 아마 L2 같은 unified lower cache를 따뜻하게 만드는 효과가 섞인다.
- 그래도 이것을 instruction fetch용 prefetch라고 해석하면 안 된다. 더 차갑게 만든 8 MiB evictor 조건에서는 대체로 `PREFETCHI`가 더 안정적으로 좋거나 최소한 덜 나쁘다.
- `actual_exec_warm`은 target을 실제로 한 번 실행해서 이미 따뜻하게 만든 ideal bound다. 이 값은 보통 34-50 cycles 근처로, prefetch가 도달할 수 있는 최선의 하한선이다.

## 빌드와 실행

`prefetch_test`는 반드시 `-O1`로 빌드한다.

```sh
cd microbench/src
make prefetch_test
```

Makefile과 helper script가 둘 다 아래 형태로 컴파일한다.

```sh
clang -O1 -march=graniterapids -m64 -no-pie -fno-plt -mprefetchi prefetch_test.c utils.c -o prefetch_test
```

기본 실행 형태:

```sh
./prefetch_test [iterations] [evict_kib] [cpu]
```

예시:

```sh
./prefetch_test 1000 4096 10 > ../result/prefetch_test_prefetchi_vs_prefetcht_evict4096_i1000.csv
```

출력 CSV 컬럼:

```text
strategy,delay,iters,evict_kib,mean,min,p05,p25,p50,p75,p95,p99,max
```

여기서 가장 먼저 볼 값은 `p50`이다. `mean`은 interrupt나 OS noise에 더 민감하고, `p95/p99`는 tail latency를 볼 때 쓴다.

## 코드가 하는 일

### 1. Target 함수

`bar`, `foo`, `baz`는 실제로 실행 시간을 재는 target instruction stream이다.

```c
__attribute__((noinline, used, aligned(4096), section(".text.target.bar")))
int bar(int a) { ... }
```

세 함수 모두:

- `noinline`: compiler가 call을 없애지 못하게 한다.
- `used`: 죽은 코드로 제거되지 않게 한다.
- `aligned(4096)`: 각 함수를 page boundary 근처에 둬서 서로 가까운 sequential fetch 효과를 줄인다.
- separate section: `.text.target.bar`, `.text.target.foo`, `.text.target.baz`에 따로 배치한다.
- 함수 body 안에 48개의 NOP를 넣어서 target code line이 너무 작지 않게 만든다.

### 2. Indirect call

실제로 timing하는 부분은 `call_targets_indirect()`다. 이 함수는 volatile function pointer table을 통해 `bar`, `foo`, `baz`를 indirect call한다.

```c
static TargetFn volatile g_targets[3] = {bar, foo, baz};
```

왜 direct call을 피하나?

- direct call이면 compiler와 frontend가 target을 너무 쉽게 알 수 있다.
- FDIP 같은 hardware frontend mechanism이 target을 미리 가져오는 효과가 커질 수 있다.
- indirect call과 순서 섞기를 사용하면 prefetch 효과와 일반 frontend 예측 효과를 조금 더 분리해서 볼 수 있다.

### 3. PREFETCHI와 PREFETCHT0

`PREFETCHI`는 instruction stream을 위한 prefetch hint다.

```c
__builtin_ia32_prefetchi(bar, 3);
```

`PREFETCHT0`는 data cache용 prefetch hint다. 여기서는 일부러 같은 code address에 대해 data prefetch를 날린다.

```c
asm volatile("prefetcht0 bar(%%rip)" ::: "memory");
```

이 비교의 의미는 다음이다.

- `PREFETCHI`: code를 instruction-fetch 경로로 당겨오는 의도.
- `PREFETCHT0`: code address를 data처럼 당겨오는 우회 실험.
- 만약 `PREFETCHT0`도 좋아지면, 그것은 보통 L2/LLC 같은 unified cache가 따뜻해진 효과일 수 있다. L1I에 직접 들어갔다고 단정하면 안 된다.

### 4. Strategy 이름

각 delay마다 아래 strategy를 전부 돈다.

| strategy | 의미 |
| --- | --- |
| `baseline` | prefetch 없이 delay 후 target 실행 |
| `prefetchi_direct` | 같은 함수에서 바로 `PREFETCHI` 후 delay |
| `prefetcht_direct` | 같은 함수에서 바로 `PREFETCHT0` 후 delay |
| `prefetchi_farfunc` | 멀리 떨어진 함수 안에서 `PREFETCHI` |
| `prefetcht_farfunc` | 멀리 떨어진 함수 안에서 `PREFETCHT0` |
| `actual_exec_warm` | target을 실제 한 번 실행해서 warm 상태를 만든 뒤 timing |
| `prefetchi_far_before` | far pressure code를 실행한 뒤 `PREFETCHI` |
| `prefetcht_far_before` | far pressure code를 실행한 뒤 `PREFETCHT0` |
| `prefetchi_far_after` | `PREFETCHI` 후 far pressure code 실행 |
| `prefetcht_far_after` | `PREFETCHT0` 후 far pressure code 실행 |
| `prefetchi_branch_taken` | 큰 taken branch path 안에 `PREFETCHI` |
| `prefetcht_branch_taken` | 큰 taken branch path 안에 `PREFETCHT0` |
| `prefetchi_branch_nottaken` | 큰 not-taken path 안에 `PREFETCHI` |
| `prefetcht_branch_nottaken` | 큰 not-taken path 안에 `PREFETCHT0` |
| `prefetchi_serial_direct` | `cpuid`로 serialize한 뒤 `PREFETCHI` |
| `prefetchi_serial_far_after` | `cpuid`, `PREFETCHI`, far pressure code |
| `prefetchi_timed_path_*` | timed region wrapper인 `call_targets_indirect`까지 `PREFETCHI` |
| `prefetchi_burst*` | `PREFETCHI`를 여러 번 반복 |
| `prefetchi_serial_timed_path_burst_far_after` | `cpuid`, wrapper+target burst prefetch, far pressure code |
| `prefetchi_coldpath*` | 큰 cold code path를 지나간 뒤 `PREFETCHI` |
| `prefetchi_branch_deep*` | 더 큰 not-taken branch path 뒤 `PREFETCHI` |

### 5. Delay 종류

각 strategy는 모든 delay에 대해 반복된다.

| delay | 의도 |
| --- | --- |
| `none` | prefetch 직후 바로 target 실행 |
| `nop64`, `nop256`, `nop1024` | 작은 frontend-only delay |
| `nop2048`, `nop4096`, `nop8192`, `nop16384` | prefetch completion window를 확인하기 위한 큰 NOP delay |
| `spin1k`, `spin10k` | 작은 branch loop delay |
| `arith256`, `arith1024` | backend arithmetic delay |
| `complex_light` | branch가 있는 가벼운 control flow |
| `complex_heavy` | far function call이 섞인 무거운 control flow |

여기서 중요한 점은 delay가 길다고 항상 prefetch에 좋은 것이 아니라는 것이다. delay가 길면 `PREFETCHI`가 완료될 시간이 생기지만, 동시에 FDIP, next-line prefetch, normal fetch가 target을 알아서 가져올 시간도 생긴다. 그래서 baseline도 같이 좋아져서 prefetch의 차이가 사라질 수 있다.

### 6. I-cache evictor

매 sample마다 executable NOP sled를 실행한다.

```c
setup_evictor(evict_kib * 1024ull);
evict_icache();
```

이 코드는 큰 executable buffer를 만들고 NOP를 채운 뒤 실행한다. 목적은 target code를 instruction side에서 차갑게 만드는 것이다.

실험상 64 KiB, 256 KiB, 1024 KiB evictor는 효과가 약했다. 4096 KiB부터 prefetch signal이 보였고, 8192 KiB에서는 cold-code 효과가 더 강해졌다.

### 7. Timing loop

각 sample의 순서는 아래와 같다.

```text
evict_icache()
lfence
run_strategy(strategy)
run_delay(delay)
t0 = rdtsc
call_targets_indirect(seed)
t1 = rdtscp
cycles = t1 - t0
```

즉, prefetch 자체의 실행 시간을 재는 benchmark가 아니다. prefetch와 delay 이후 target instruction stream을 실행할 때 걸리는 시간을 재는 benchmark다.

## Assembly 확인

빌드 후 target 주소는 다음처럼 배치되었다.

```text
000000000040b000 T bar
000000000040c000 T foo
000000000040d000 T baz
000000000040e000 t prefetchi_targets_direct
000000000040f000 t prefetchi_targets_far
0000000000410000 t prefetcht_targets_direct
0000000000411000 t prefetcht_targets_far
0000000000412000 t branch_prefetchi_targets
0000000000413000 t branch_prefetcht_targets
```

`PREFETCHI`는 이 binutils에서 `nop DWORD PTR`로 decode되지만, opcode byte가 `0f 18 /7`이고 RIP-relative target이 `bar`, `foo`, `baz`를 정확히 가리킨다.

```text
40e000: 0f 18 3d ... # 40b000 <bar>
40e007: 0f 18 3d ... # 40c000 <foo>
40e00e: 0f 18 3d ... # 40d000 <baz>
```

`PREFETCHT0`는 objdump에서 명확히 `prefetcht0`로 나온다.

```text
410000: 0f 18 0d ... # 40b000 <bar>
410007: 0f 18 0d ... # 40c000 <foo>
41000e: 0f 18 0d ... # 40d000 <baz>
```

따라서 이번 비교는 두 prefetch가 모두 같은 target code address를 대상으로 한다.

## 측정 파일

이번 비교에 사용한 CSV:

- `microbench/result/prefetch_test_prefetchi_vs_prefetcht_evict4096_i1000.csv`
- `microbench/result/prefetch_test_prefetchi_vs_prefetcht_evict4096_i1000_rep2.csv`
- `microbench/result/prefetch_test_prefetchi_vs_prefetcht_evict8192_i300.csv`
- `microbench/result/prefetch_test_large_delay_evict8192_i300.csv`
- `microbench/result/prefetch_test_large_delay_evict8192_i300_rep2.csv`
- `microbench/result/prefetch_test_force_prefetchi_nop_evict8192_i300.csv`
- `microbench/result/prefetch_test_force_prefetchi_nop4096_evict32768_i200.csv`
- `microbench/result/prefetch_test_force_prefetchi_timedpath_nop4096_evict32768_i200.csv`
- `microbench/result/prefetch_test_force_prefetchi_serial_wait_nop4096_evict32768_i200.csv`
- `microbench/result/prefetch_test_force_prefetchi_nop_evict32768_i120.csv`
- `microbench/result/prefetch_test_force_prefetchi_nop64_evict32768_i300.csv`
- `microbench/result/prefetch_test_force_prefetchi_nop64_evict32768_i300_rep2.csv`

환경:

- CPU: Intel Xeon 6787P
- `PREFETCHI` CPUID support: yes
- pin CPU: 10
- realtime scheduling: permission 부족으로 실패했지만 benchmark는 계속 실행됨

## 4096 KiB evictor, direct 비교

아래 표는 가장 깨끗한 direct 비교다. 숫자는 `p50 cycles`이고, `r1/r2`는 같은 조건 1000 sample 반복 두 번이다.

| delay | baseline p50 r1/r2 | actual p50 r1/r2 | PREFETCHI direct p50 r1/r2 | PREFETCHT direct p50 r1/r2 | 해석 |
| --- | ---: | ---: | ---: | ---: | --- |
| `none` | 124/78 | 34/34 | 64/68 | 62/66 | direct에서는 `PREFETCHT0`가 약간 유리하거나 동률 |
| `nop64` | 62/62 | 34/34 | 62/62 | 62/62 | baseline이 이미 따뜻해서 차이가 작음 |
| `nop256` | 62/62 | 34/34 | 62/62 | 62/78 | baseline이 이미 따뜻해서 차이가 작음 |
| `nop1024` | 70/62 | 34/34 | 62/62 | 62/62 | baseline이 이미 따뜻해서 차이가 작음 |
| `spin1k` | 260/216 | 36/36 | 260/220 | 260/220 | direct prefetch benefit이 거의 없음 |
| `spin10k` | 262/228 | 36/36 | 262/222 | 266/220 | direct는 불안정하고 거의 도움 안 됨 |
| `arith256` | 210/170 | 36/34 | 186/170 | 136/170 | `PREFETCHT0`가 한 번 크게 좋았지만 반복에서는 동률 |
| `arith1024` | 130/98 | 36/36 | 136/98 | 136/98 | 반복 간 baseline 자체가 많이 변함 |
| `complex_light` | 138/100 | 36/36 | 136/98 | 248/96 | 반복 간 변동 큼 |
| `complex_heavy` | 68/64 | 46/36 | 66/64 | 64/68 | baseline이 이미 따뜻해서 차이가 작음 |

4096 KiB 조건에서 direct 비교만 보면 `PREFETCHT0`가 `PREFETCHI`와 비슷하거나 특정 run에서 더 좋아 보이는 경우가 있다. 하지만 반복 간 변동이 꽤 커서, 이 결과만으로 data prefetch가 code prefetch보다 낫다고 말하기는 어렵다.

## 4096 KiB evictor, 각 family의 best strategy

아래는 같은 4096 KiB 조건에서 `prefetchi_*` 중 best p50와 `prefetcht_*` 중 best p50를 고른 것이다.

| delay | best PREFETCHI p50 r1/r2 | best PREFETCHT p50 r1/r2 | 안정적 해석 |
| --- | ---: | ---: | --- |
| `none` | `prefetchi_farfunc` 62 / `prefetchi_branch_nottaken` 62 | `prefetcht_direct` 62 / `prefetcht_farfunc` 62 | 동률 |
| `nop64` | `prefetchi_far_after` 60 / `prefetchi_direct` 62 | `prefetcht_far_after` 60 / `prefetcht_direct` 62 | 동률 |
| `nop256` | `prefetchi_far_before` 60 / `prefetchi_direct` 62 | `prefetcht_far_after` 60 / `prefetcht_far_before` 62 | 동률 |
| `nop1024` | `prefetchi_direct` 62 / `prefetchi_direct` 62 | `prefetcht_direct` 62 / `prefetcht_direct` 62 | 동률 |
| `spin1k` | `prefetchi_direct` 260 / `prefetchi_direct` 220 | `prefetcht_direct` 260 / `prefetcht_direct` 220 | 둘 다 도움 없음 |
| `spin10k` | `prefetchi_branch_taken` 134 / `prefetchi_far_before` 64 | `prefetcht_far_before` 134 / `prefetcht_far_before` 64 | 둘 다 특정 frontend-pressure 형태에서만 도움 |
| `arith256` | `prefetchi_far_after` 132 / `prefetchi_far_after` 76 | `prefetcht_branch_nottaken` 132 / `prefetcht_far_before` 98 | 반복 간 변동 |
| `arith1024` | `prefetchi_far_before` 134 / `prefetchi_direct` 98 | `prefetcht_direct` 136 / `prefetcht_direct` 98 | 반복 간 변동 |
| `complex_light` | `prefetchi_direct` 136 / `prefetchi_direct` 98 | `prefetcht_branch_nottaken` 246 / `prefetcht_direct` 96 | 반복 간 변동 |
| `complex_heavy` | `prefetchi_farfunc` 64 / `prefetchi_farfunc` 62 | `prefetcht_direct` 64 / `prefetcht_far_before` 64 | 거의 동률 |

4096 KiB에서는 `PREFETCHI`와 `PREFETCHT0`의 best-case p50가 동률인 경우가 많다. 이것은 data prefetch가 instruction prefetch와 같은 일을 한다는 뜻이 아니라, 이 정도 coldness에서는 lower-level cache warming과 normal frontend prefetch가 섞여 두 방법이 비슷하게 보일 수 있다는 뜻에 가깝다.

## 8192 KiB evictor, 초기 더 차가운 조건

8 MiB evictor에서는 target code가 훨씬 차갑게 보였고, baseline p50가 대부분 500-600 cycles대로 올라갔다. 아래 표는 큰 NOP delay를 추가하기 전의 초기 300-sample run이다. 이 표만 보면 `PREFETCHI`가 좋은 경우가 있어 보였지만, 이후 큰 delay를 추가해 반복 측정하니 이 해석은 너무 낙관적이었다.

| delay | baseline p50 | actual p50 | PREFETCHI direct | PREFETCHT direct | best PREFETCHI | best PREFETCHT | winner |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `none` | 634 | 36 | 628 | 590 | `prefetchi_far_after` 558 | `prefetcht_far_after` 516 | `PREFETCHT0` |
| `nop64` | 566 | 36 | 564 | 546 | `prefetchi_direct` 564 | `prefetcht_branch_nottaken` 500 | `PREFETCHT0` |
| `nop256` | 566 | 36 | 562 | 550 | `prefetchi_branch_nottaken` 532 | `prefetcht_direct` 550 | `PREFETCHI` |
| `nop1024` | 630 | 34 | 460 | 562 | `prefetchi_branch_taken` 454 | `prefetcht_far_before` 546 | `PREFETCHI` |
| `spin1k` | 564 | 36 | 612 | 674 | `prefetchi_far_before` 522 | `prefetcht_far_after` 570 | `PREFETCHI` |
| `spin10k` | 568 | 36 | 574 | 596 | `prefetchi_far_before` 552 | `prefetcht_far_before` 562 | `PREFETCHI` |
| `arith256` | 514 | 34 | 526 | 668 | `prefetchi_far_after` 502 | `prefetcht_farfunc` 548 | `PREFETCHI` |
| `arith1024` | 562 | 34 | 542 | 558 | `prefetchi_far_after` 450 | `prefetcht_branch_nottaken` 536 | `PREFETCHI` |
| `complex_light` | 546 | 42 | 560 | 564 | `prefetchi_far_after` 526 | `prefetcht_direct` 564 | `PREFETCHI` |
| `complex_heavy` | 554 | 50 | 562 | 620 | `prefetchi_farfunc` 556 | `prefetcht_branch_nottaken` 582 | `PREFETCHI` |

초기 8 MiB 조건의 해석:

- `none`, `nop64`에서는 `PREFETCHT0` best가 더 낮게 나왔다.
- `nop256` 이상, spin, arithmetic, complex delay에서는 대체로 `PREFETCHI`가 더 좋았다.
- direct만 보면 `nop1024`에서 `PREFETCHI direct`가 460 cycles로 `PREFETCHT direct` 562 cycles보다 확실히 좋았다.
- `arith256`, `spin1k`, `complex_heavy`처럼 `PREFETCHT0 direct`가 baseline보다 오히려 나빠지는 경우도 있다.

## 8192 KiB evictor, 큰 NOP delay 재측정

`PREFETCHI`가 `actual_exec_warm`보다 너무 느리다는 문제를 확인하기 위해 `nop2048`, `nop4096`, `nop8192`, `nop16384`를 추가했다. 이 재측정의 목적은 prefetch 뒤 window를 충분히 줬을 때 target latency가 몇백 cycles 단위로 내려가는지 보는 것이다.

결론부터 말하면, 큰 delay를 넣어도 `PREFETCHI`는 몇백 cycles 개선을 만들지 못했다. 8 MiB evictor에서 두 번 반복한 결과, `PREFETCHI` best gain은 첫 run에서 최대 106 cycles, 두 번째 run에서 최대 76 cycles였다. 사용한 기준인 “최소 몇백 cycles 개선”에는 못 미친다.

반대로 `PREFETCHT0`는 같은 code address에 대해 몇백 cycles 개선을 반복적으로 만들었다. 이것은 code bytes가 lower-level unified cache 쪽으로 당겨지는 효과가 강하다는 뜻일 수 있다. 하지만 이것을 instruction-side prefetch 성공으로 해석하면 안 된다.

### PREFETCHI p50, 8 MiB, 300 samples

| delay | baseline r1/r2 | actual r1/r2 | direct r1/r2 | far_after r1/r2 | branch_nottaken r1/r2 | best gain r1/r2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `none` | 578/578 | 36/36 | 586/640 | 568/602 | 592/594 | 10/-8 |
| `nop64` | 550/592 | 36/36 | 550/580 | 572/594 | 548/550 | 2/42 |
| `nop256` | 564/598 | 36/36 | 556/568 | 560/562 | 566/596 | 8/36 |
| `nop1024` | 556/596 | 36/36 | 556/592 | 558/572 | 556/586 | 8/24 |
| `nop2048` | 554/570 | 36/36 | 556/588 | 570/564 | 574/584 | -2/6 |
| `nop4096` | 560/572 | 36/36 | 566/570 | 482/566 | 454/560 | 106/12 |
| `nop8192` | 454/544 | 36/36 | 460/558 | 396/574 | 400/568 | 58/-14 |
| `nop16384` | 398/574 | 36/36 | 408/558 | 400/552 | 396/562 | 2/76 |

해석:

- `far_after`와 `branch_nottaken`이 가끔 direct보다 좋다.
- 하지만 `PREFETCHI` 기준으로는 개선 폭이 작고 반복성이 약하다.
- delay를 `nop16384`까지 키워도 `actual_exec_warm`인 36 cycles 근처로 가지 않는다.
- 따라서 현재 harness에서 `far_after`와 `branch_nottaken`이 `PREFETCHI`를 강제로 제대로 실행시키는 역할을 확실히 하고 있다고 보기 어렵다.

### PREFETCHT0 p50, 8 MiB, 300 samples

| delay | baseline r1/r2 | actual r1/r2 | direct r1/r2 | far_after r1/r2 | branch_nottaken r1/r2 | best gain r1/r2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `none` | 578/578 | 36/36 | 496/470 | 478/450 | 486/488 | 100/144 |
| `nop64` | 550/592 | 36/36 | 304/438 | 308/294 | 432/442 | 246/298 |
| `nop256` | 564/598 | 36/36 | 376/392 | 306/268 | 442/360 | 258/330 |
| `nop1024` | 556/596 | 36/36 | 438/412 | 442/338 | 440/450 | 154/258 |
| `nop2048` | 554/570 | 36/36 | 306/436 | 310/418 | 356/404 | 250/324 |
| `nop4096` | 560/572 | 36/36 | 378/430 | 278/474 | 466/476 | 282/142 |
| `nop8192` | 454/544 | 36/36 | 508/348 | 498/424 | 454/430 | 0/212 |
| `nop16384` | 398/574 | 36/36 | 456/520 | 410/460 | 324/578 | 74/264 |

해석:

- `PREFETCHT0`는 여러 delay에서 몇백 cycles 개선을 만든다.
- 이 개선은 `PREFETCHI`보다 훨씬 크고, 반복 run에서도 자주 재현된다.
- code address를 data prefetch하면 lower-level cache가 따뜻해져 instruction fetch latency가 줄어드는 효과가 있을 수 있다.
- 하지만 `actual_exec_warm`과는 여전히 멀다. data prefetch도 L1I/uop/BTB/iTLB warm 상태를 만들지는 못한다.

## PREFETCHT0 수준으로 PREFETCHI 끌어올리기

위 결과만으로는 `PREFETCHI`가 너무 약했다. 그래서 `PREFETCHI` hint가 실제로 execute되는 상황을 더 강하게 만들기 위해 다음 변형을 추가했다.

| 변형 | 의도 | 결과 |
| --- | --- | --- |
| `prefetchi_serial_direct` | `cpuid` 후 바로 `PREFETCHI` | direct보다 훨씬 좋아짐 |
| `prefetchi_serial_far_after` | `cpuid`, `PREFETCHI`, far code | 32 MiB evictor에서 300-cycle 근처까지 개선 |
| `prefetchi_timed_path_*` | `bar/foo/baz`뿐 아니라 timed wrapper인 `call_targets_indirect`도 prefetch | 단독으로는 작고, serial/burst/far_after와 결합할 때 유효 |
| `prefetchi_burst*` | 같은 target에 `PREFETCHI`를 반복 발행 | serial/timed/far_after와 결합할 때 가장 좋음 |
| `prefetchi_coldpath*` | prefetch 함수 안에서 큰 NOP path를 먼저 실행 | 기대보다 효과 작음 |
| `prefetchi_branch_deep*` | 더 깊은 not-taken path에서 prefetch | 기대보다 효과 작음 |
| `prefetchi_serial_wait*` | `PREFETCHI` 뒤에 다시 `cpuid` | 오히려 대체로 나빠짐 |

핵심은 `cpuid`로 serialize한 뒤, timed path 전체를 `PREFETCHI` burst로 여러 번 요청하고, 그 다음 far code로 prefetch가 진행될 시간을 주는 조합이었다.

```text
prefetchi_serial_timed_path_burst_far_after:
    cpuid
    PREFETCHI(call_targets_indirect)
    PREFETCHI(bar)
    PREFETCHI(foo)
    PREFETCHI(baz)
    small NOP gap
    repeat burst
    far_pressure_c()
    delay
    measure call_targets_indirect()
```

### 32 MiB evictor, nop4096 scout

`nop4096` 하나만 32 MiB evictor에서 먼저 확인했다.

| strategy | p50 | gain vs baseline | mean | p95 |
| --- | ---: | ---: | ---: | ---: |
| baseline | 822 | 0 | 828.4 | 974 |
| actual_exec_warm | 44 | 778 | 55.2 | 90 |
| prefetcht_far_after | 448 | 374 | 470.3 | 648 |
| prefetcht_direct | 476 | 346 | 538.6 | 900 |
| prefetchi_serial_far_after | 502 | 320 | 520.1 | 672 |
| prefetchi_serial_timed_path_far_after | 512 | 310 | 519.9 | 686 |
| prefetchi_direct | 800 | 22 | 806.0 | 948 |

이 시점에서 `PREFETCHI`도 300-cycle 이상 개선되기 시작했다. 단, best `PREFETCHT0`보다는 약 54 cycles 느렸다.

### 32 MiB evictor, NOP sweep

120-sample scout에서 delay를 다시 훑었다.

| delay | baseline | best PREFETCHI | gain | best PREFETCHT0 | gain |
| --- | ---: | --- | ---: | --- | ---: |
| `nop64` | 770 | `prefetchi_serial_timed_path_burst_far_after` 470 | 300 | `prefetcht_far_after` 416 | 354 |
| `nop256` | 714 | `prefetchi_serial_timed_path_burst_far_after` 446 | 268 | `prefetcht_far_after` 418 | 296 |
| `nop1024` | 732 | `prefetchi_serial_timed_path_burst_far_after` 458 | 274 | `prefetcht_far_before` 420 | 312 |
| `nop2048` | 720 | `prefetchi_serial_timed_path_direct` 474 | 246 | `prefetcht_far_before` 420 | 300 |
| `nop4096` | 718 | `prefetchi_serial_wait_timed_path_far_after` 444 | 274 | `prefetcht_far_after` 418 | 300 |
| `nop8192` | 756 | `prefetchi_serial_timed_path_burst_far_after` 460 | 296 | `prefetcht_far_after` 432 | 324 |
| `nop16384` | 704 | `prefetchi_serial_timed_path_far_after` 460 | 244 | `prefetcht_far_after` 432 | 272 |

가장 좋은 후보는 `nop64 + prefetchi_serial_timed_path_burst_far_after`였다.

### 32 MiB evictor, nop64 confirmation

`nop64` 조건을 300 samples로 두 번 반복했다.

| run | baseline | actual | best PREFETCHI | gain | best PREFETCHT0 | gain |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| r1 | 792 | 36 | `prefetchi_serial_timed_path_burst_far_after` 436 | 356 | `prefetcht_far_after` 406 | 386 |
| r2 | 866 | 36 | `prefetchi_serial_timed_path_burst_far_after` 512 | 354 | `prefetcht_far_after` 492 | 374 |

같은 run에서 `PREFETCHT0 direct`와 비교하면 `PREFETCHI`가 사실상 같은 수준까지 왔다.

| run | baseline | PREFETCHI best | PREFETCHT0 direct | PREFETCHT0 best |
| --- | ---: | ---: | ---: | ---: |
| r1 | 792 | 436 | 436 | 406 |
| r2 | 866 | 512 | 510 | 492 |

즉, 현재 satisfactory condition은 다음이다.

```sh
cd microbench/src
./prefetch_test 300 32768 10 nop64 all \
  > ../result/prefetch_test_force_prefetchi_nop64_evict32768_i300.csv
```

이 조건에서 `PREFETCHI`는 `PREFETCHT0 direct`와 같은 수준이고, best `PREFETCHT0`보다 20-30 cycles 정도 느리다. 사용자가 제시한 “최소 몇백 cycles 개선” 기준은 만족한다.

## Delay별 결론

| delay | 결론 |
| --- | --- |
| `none` | prefetch가 들어갈 시간은 짧지만, 4 MiB에서는 둘 다 크게 좋아지고 8 MiB에서는 `PREFETCHT0` best가 더 좋았다. 다만 이건 instruction prefetch라기보다 lower cache warming 가능성이 크다. |
| `nop64` | 32 MiB evictor와 `prefetchi_serial_timed_path_burst_far_after` 조합에서 현재 best condition이다. `PREFETCHI`가 354-356 cycles 개선되어 `PREFETCHT0 direct`와 같은 수준까지 온다. |
| `nop256` | 4 MiB에서는 둘 다 동률에 가깝다. 8 MiB에서는 `PREFETCHI` best가 더 좋다. |
| `nop1024` | 초기 run에서는 `PREFETCHI direct`가 좋아 보였지만, 큰 delay 추가 후 반복에서는 몇백 cycles gain이 재현되지 않았다. |
| `nop2048` | `PREFETCHI`는 거의 개선이 없고, `PREFETCHT0`는 반복적으로 큰 gain을 보였다. |
| `nop4096` | `PREFETCHI branch_nottaken`이 첫 run에서 106 cycles 개선했지만 두 번째 run에서는 12 cycles뿐이었다. `PREFETCHT0`는 142-282 cycles gain을 보였다. |
| `nop8192` | `PREFETCHI` 개선은 작거나 음수다. 너무 긴 NOP delay가 baseline 자체도 바꿔서 해석이 흐려진다. |
| `nop16384` | delay를 매우 크게 줘도 `PREFETCHI`가 actual bound 근처로 가지 않는다. delay 부족만이 원인은 아닌 것으로 보인다. |
| `spin1k` | direct prefetch는 거의 도움이 없다. 8 MiB best에서도 `PREFETCHI`가 덜 나쁘지만, 이 delay는 만족스럽지 않다. |
| `spin10k` | direct는 별로지만 far-before 같은 frontend-pressure 형태에서는 둘 다 좋아질 수 있다. 그래도 8 MiB에서는 `PREFETCHI`가 약간 우세하다. |
| `arith256` | 4 MiB direct에서는 `PREFETCHT0`가 한 번 크게 좋았지만 반복에서 사라졌다. 8 MiB에서는 `PREFETCHI`가 더 안정적으로 낫다. |
| `arith1024` | 4 MiB에서는 baseline 변동이 크다. 8 MiB에서는 `PREFETCHI far_after`가 best다. |
| `complex_light` | 4 MiB 결과가 매우 불안정하다. 8 MiB에서는 `PREFETCHI`가 낫다. |
| `complex_heavy` | 4 MiB에서는 baseline이 이미 따뜻하게 나와 차이가 작다. 8 MiB에서는 `PREFETCHI`가 덜 나쁘거나 더 좋다. |

## 최종 해석

`PREFETCHT0(data)`는 code address에 대해 실행해도 성능 이득을 만들 수 있다. 특히 큰 delay를 추가한 8 MiB evictor 재측정에서는 `PREFETCHT0`가 몇백 cycles 개선을 반복적으로 만들었다.

`PREFETCHI(code)`는 단순 direct, far_after, branch_nottaken만으로는 기대한 크기의 이득을 만들지 못했다. 하지만 `cpuid` serialization, timed path 전체 prefetch, burst prefetch, far_after를 결합하면 `PREFETCHT0 direct`와 같은 수준의 이득이 나온다. 현재 best는 `32 MiB evictor + nop64 + prefetchi_serial_timed_path_burst_far_after`다.

따라서 지금 결과를 가장 보수적으로 쓰면:

- 단순 `PREFETCHI direct`는 여전히 거의 효과가 없다.
- `far_after`와 `branch_nottaken`만으로는 부족하고, `cpuid`로 frontend/backend를 비운 뒤 timed path 전체를 burst로 prefetch해야 큰 효과가 나온다.
- 현재 best `PREFETCHI`는 사용자가 원하는 “최소 몇백 cycles 개선” 기준을 만족한다.
- `PREFETCHT0`의 큰 gain은 lower-level cache warming 효과로 보인다. instruction-side prefetch 성공으로 해석하면 위험하다.
- `actual_exec_warm`은 여전히 36 cycles 근처이므로, prefetch가 실제 execution warm 상태 전체를 만드는 것은 아니다.

## 다시 실험할 때 추천 명령

```sh
cd microbench/src
make prefetch_test

# 4 MiB, 반복성 확인용
./prefetch_test 1000 4096 10 > ../result/prefetch_test_prefetchi_vs_prefetcht_evict4096_i1000_new.csv

# 더 차갑게 만든 비교
./prefetch_test 300 8192 10 > ../result/prefetch_test_prefetchi_vs_prefetcht_evict8192_i300_new.csv

# 큰 delay 포함 비교
./prefetch_test 300 8192 10 > ../result/prefetch_test_large_delay_evict8192_i300_new.csv

# 현재 best PREFETCHI 조건
./prefetch_test 300 32768 10 nop64 all > ../result/prefetch_test_force_prefetchi_nop64_evict32768_i300_new.csv

# helper 요약
python3 run_prefetch_stats.py 300 8192 10 ../result/prefetch_test_prefetchi_vs_prefetcht_summary_check.csv
```

`run_prefetch_stats.py`는 이제 delay마다 best `PREFETCHI`와 best `PREFETCHT0`도 같이 요약한다.

## 2026-05-04: current farcall-repeat2 apples-to-apples 비교

빌드:

```sh
cd microbench/src
make prefetch_test
```

현재 binary는 `clang -O1 -march=graniterapids -m64 -no-pie -fno-plt -mprefetchi`로 빌드된다.

### 추가한 비교군

- `prefetcht1` single/multiline/farcall-repeat2 경로를 추가했다.
- `apples_actual_exec`는 timed region과 같은 target을 미리 한 번 실행한다.
- `*_farcall_burst_repeat2_nof`는 single-line hint를 `cold farcall + hot farcall`로 2회 실행한다.
- `*_farcall_lines_repeat2_nof`는 target당 8개 line hint를 `cold farcall + hot farcall`로 2회 실행한다.

### one-target mode, pause64

명령:

```sh
./prefetch_test 1000 0 10 "=pause64" \
  "=apples_actual_exec,=apples_base_farcall_burst_repeat2_nof,=apples_prefetchit0_farcall_burst_repeat2_nof,=apples_prefetchit1_farcall_burst_repeat2_nof,=apples_prefetcht0_farcall_burst_repeat2_nof,=apples_prefetcht1_farcall_burst_repeat2_nof,=apples_base_farcall_lines_repeat2_nof,=apples_prefetchit0_farcall_lines_repeat2_nof,=apples_prefetchit1_farcall_lines_repeat2_nof,=apples_prefetcht0_farcall_lines_repeat2_nof,=apples_prefetcht1_farcall_lines_repeat2_nof" \
  flush_targets_one_target > ../result/prefetch_test_apples_current_pause64_i1000.csv
```

| strategy | p50 | p75 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: |
| actual run | 58 | 60 | 60 | 84 |
| base single-shape | 808 | 1018 | 1274 | 1452 |
| PREFETCHIT0 single | 90 | 722 | 1072 | 1150 |
| PREFETCHIT1 single | 284 | 922 | 1260 | 1510 |
| PREFETCHT0 single | 954 | 1094 | 1420 | 1510 |
| PREFETCHT1 single | 896 | 1102 | 1336 | 1516 |
| base multiline-shape | 1030 | 1096 | 1488 | 1538 |
| PREFETCHIT0 multiline | 90 | 92 | 92 | 92 |
| PREFETCHIT1 multiline | 90 | 90 | 92 | 92 |
| PREFETCHT0 multiline | 366 | 678 | 796 | 802 |
| PREFETCHT1 multiline | 362 | 578 | 792 | 800 |

결론: current forced-execution 조건에서 instruction prefetch는 multiline일 때만 actual bound 근처에 안정적으로 붙는다. data prefetch는 multiline으로도 p50/p75/tail이 훨씬 느리다.

### IT1 multiline vs data T1 multiline window

명령:

```sh
./prefetch_test 1000 0 10 \
  "=none,=pause8,=pause16,=pause32,=pause48,=pause64,=pause96,=pause128,=pause160,=pause192,=pause224,=pause256,=pause384,=pause512,=pause768,=pause1024,=pause1536,=pause2048,=pause4096" \
  "=apples_actual_exec,=apples_base_farcall_lines_repeat2_nof,=apples_prefetchit1_farcall_lines_repeat2_nof,=apples_prefetcht1_farcall_lines_repeat2_nof" \
  flush_targets_one_target > ../result/prefetch_test_it1_vs_t1_window_pause_i1000.csv
```

`PREFETCHIT1 multiline`은 p50은 delay 없이도 90 cycles지만 tail이 남는다. p95/p99 기준으로는 `pause48`부터 92 cycles 근처로 안정화된다. `PREFETCHT1 multiline`은 delay를 `pause4096`까지 늘려도 p50이 300-700 cycles대이고 p95/p99는 700-800 cycles대라 code-side warm state를 만들지 못한다.

### all-target timed mode, pause64

명령:

```sh
./prefetch_test 1000 0 10 "=pause64" \
  "=apples_actual_exec,=apples_base_farcall_burst_repeat2_nof,=apples_prefetchit0_farcall_burst_repeat2_nof,=apples_prefetchit1_farcall_burst_repeat2_nof,=apples_prefetcht0_farcall_burst_repeat2_nof,=apples_prefetcht1_farcall_burst_repeat2_nof,=apples_base_farcall_lines_repeat2_nof,=apples_prefetchit0_farcall_lines_repeat2_nof,=apples_prefetchit1_farcall_lines_repeat2_nof,=apples_prefetcht0_farcall_lines_repeat2_nof,=apples_prefetcht1_farcall_lines_repeat2_nof" \
  flush_targets > ../result/prefetch_test_apples_current_alltargets_pause64_i1000.csv
```

세 target을 모두 timed region에서 실행하면 actual bound는 p50 150 cycles, p99 172 cycles이다. `PREFETCHIT0/1 multiline`은 p50 172, p99 174로 actual bound 근처에 붙는다. data prefetch multiline은 p50은 172로 좋아지지만 p95/p99가 300 cycles대로 남는다.
