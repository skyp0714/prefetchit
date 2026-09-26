# TODO — 다음 작업 (2026-09-19 기준)

전제: `README.md`의 용어·측정 규칙과 `docs/prefetch_plan_by_miss_class.md` §0의 세팅(코어 고정, 사용 코어 C6 off, 현실적 부하,
alone/interleaved 두 regime, `:u` 카운터, NOP twin, 같은 라운드 인터리브 ≥3회)을 따른다. **PGO = trace로 prefetch 위치만 정하는 것**,
레이아웃을 바꾸는 최적화는 어떤 arm에도 쓰지 않는다. 2026-09-17의 공유 코어·C6 켜진 세팅 결과는 참고값(`docs/archive/`)이며 목표치가 아니다.

## 0. 시작 전 체크리스트 (매 세션)

```bash
cd ~/prefetchit
llvm_prefetchit/scripts/platform/freeze_platform.sh show
sudo MODE=3.8ghz llvm_prefetchit/scripts/platform/freeze_platform.sh   # 단일코어(Verilator) / MODE=2ghz 서비스
# 서버 코어 C6 off: for st in /sys/devices/system/cpu/cpu{N..M}/cpuidle/state*; do [[ $(cat $st/name) == C6* ]] && echo 1 | sudo tee $st/disable; done
llvm_prefetchit/migration/verify.sh --root "$PWD"
export PATH=$PWD/benchmarks/tools/miniforge3/bin:$PATH; set +u; source benchmarks/chipyard/env.sh; set -u   # Verilator 작업 시
```
- 소켓 1(코어 0–42)만 사용, 측정 중 빌드 금지, 끝나면 `MODE=restore` + C6 재활성 + `docker compose down -v`.
- DSB socialNetwork는 `flat_codegen/dsb_build/postlink/reset_sn_stack.sh`로 올린다(redis 스냅샷 off, 새 볼륨, 그래프 로드).
- 긴 체인은 단계마다 `timeout`, 인자 없는 `wait` 금지, `pgrep` 패턴은 `^`로 앵커(스크립트 자기 자신·툴 셸 매칭 사고 3회).
- 저장소는 `prefetchit` 하나다(2026-09-22 통합, 6개 컴포넌트 history 보존). 커밋 후 **push는 사용자 확인 필요**.

---

## 1. A 부류(capacity) — `docs/prefetch_plan_by_miss_class.md` §2

### 1-A. Verilator/arcilator seq 모드의 명령 비용 절감 (검증된 1.149x/1.543x 위에서)
- MachineFunction pass에서 정확히 128 B 간격으로 `prefetcht1 D(%rip)` 1개(IR K=20은 31–125 B로 흔들려 명령 +6.4%, twin −5.7%).
- 잔여 miss: 인접하지 않은 callee 전환(11%), memset/memcpy 반환 직후 → burst 규칙.
- 일반화: LargeBoom/Quad, ESSENT. 결과 표는 `results/static_overhaul_20260916/summarize_all.py`에 행 추가.

### 1-B. DCPerf v2 DjangoBench (CPython, 2.4 MPKI @68%) — A-2/A-3
- CPython 3.x를 `-O3 -g -fpass-plugin` 으로 재빌드(venv_cpython의 인터프리터 교체), uwsgi 워커 4개 코어 36–39, C6 off.
- LBR/rate trace → cold plan v4 → 명령 샘플링 → v10 → NOP twin 5회. `dcperf_v2_screen.sh`의 서버 패턴 `^uwsgi --ini`, `JAVA_HOME=JDK 11`.
- 보고: base / plan / twin의 wrk 처리량과 uwsgi MPKI.

### 1-C. media C++ 서비스 alone (movie-id 4.9, compose-review 3.8, nginx 3.6) — A-2/A-3
- media 스택용 `build_utl_variant.sh`(SVCBIN=MovieIdService 등) + fat-static; C6 off alone regime에서 gs / plan v10 / twin.
- 이 빌드가 2-A의 베이스가 된다.

### 1-D. FeedSim v2 (2.1–2.3 MPKI @19%) — A-2
- LeafNodeRank를 pass로 재빌드(feedsim/src/build), mock_services는 그대로. 필요 파일: silesia, certs, `*.json`(설치기가 안 놓음, host quirks 메모 참조).

### 1-E. post-link 재작성기 비용 절감 (스토어용, A-5)
- 직접 call 사이트는 stub 대신 callee 앞 padding에 prefetch, PLT 사이트는 in-place 16 B → 명령 +5.7% → <1%. mongodb/redis/memcached에 C6-off alone에서 재시도.

### 1-F. 레지스터 기반 간접 타깃 prefetch (A-8, 2026-09-21 측정: proto 16% / Django 19% / thrift 6–11%의 miss가 vtable·디스패치 테이블 뒤)
- proto: IR pass에 indirect-call target hoisting 모드(`ClearNonEmpty`·`MergeIntoClearedMessages`·`InternalWriteMessage` 등 6사이트 = miss 15%) → NOP twin 비교.
- Django: ceval `DISPATCH()`에 다음-다음 opcode 핸들러 prefetch(레지스터 계산) → uwsgi MPKI·처리량.

### 1-G. MariaDB 타깃별 주입 (A-4, 우선순위 낮음, 0.8–1.1 MPKI)

---

## 2. B 부류(interleaving) — `docs/prefetch_plan_by_miss_class.md` §3

- **09-26 추가, 10% 목표**: [추가 분석·구현](class_b_headroom_20260926.md). 가중 타깃 병합과 kernel-alias switch-in 버스트 프로토타입 구현, 도구 테스트11개·커널 빌드 통과. 새 성능은 미측정이며 권한 확보 후 기본 kernel lifecycle 5개 확인을 통과했다. 높은 MPKI 운영점·의존성 coverage·문맥별 버스트를 비교하고, 커널 후보는 비용이 다른 태스크에 잡히는 효과를 풀 전체 CPU로 검증한다.

### 2-0. wake-stream (2026-09-21, `docs/prefetch_plan_classB_wakestream.md` §7) — 2-A/2-B보다 우선
- **최종(18:05, 5회)**: p11a(dense drip + post-call run 시작부) **1.054x, MPKI 86.6→76.9, 명령 +2.8%**; static plan 1.006x, callee-burst static 1.015x(twin 1.011x). 14 라운드의 결론과 안 되는 것 목록은 §7-21. pass에 `after_call`/`@n` 사이트 종류 추가됨(PrefetchITPass.cpp, 백업 .bak_postcall). `media_stack.sh down`에 `-v` 추가(익명 볼륨 207개·14 GB가 디스크를 채웠음).
- **구현·측정 완료(movie-id interleaved, R=600, 3회, 8 라운드)**: LD_PRELOAD 1.014x → inline drip 1.031x → 아카이브 사이트 **1.046x**(wsp3; 재측정 1.050/1.037) → coverage·overhead·lead 스윕(라벨, 128 B 페어, gap filler, fall-through 제외, d 8–32)은 모두 ±1% 안 = **이 계열의 상한 ≈1.05x**(§7-14). prefetchit1은 같은 자리에서 0.982x. preload stage 0은 래퍼 비용에 지워짐. 남은 일: pass post-call 사이트(run 시작부 inline), glibc 정적 링크, compose-review/compose-post, 5회 확정. 도구 `flat_codegen/dsb_build/media/ws/`; DSB 소스에 mark 패치 적용 상태(`ws_patch_src.sh revert`).
- §5 순서대로: 심볼화 수정(`MovieIdService=0` — 현재 ab_hi의 `effhi` arm은 빈 plan이라 무효) → fill-queue microbench(Q)·L3 latency → interleaved **Intel PT** trace → `run_paths.py`/`wakestream_plan.py` → pass post-call 사이트(rdtsc 게이트, 표 방식 burst) → movie-id A/B(SWPF 카운터, 게이트 G1–G3).

### 2-A. 프로세스 안 상한 확정 (B-1)
- 1-C의 빌드로 media movie-id/compose-review + socialNetwork compose-post를 **C6 off + 8/16코어 pool** 세팅에서 gs / plan v10 / twin, 5회.
- 도구: `dsb_shared_screen.sh`(pool), `dsb_warm_ab2.sh`(SVC/SVCBIN/LUA/WRK_URL/CONN/R 환경변수), `cold_plan.py`(--site-exec 가지치기).

### 2-B. RPC 디스패처의 method별 warm-up (B-2)
- thrift generated `process_<method>` 진입을 method별 사이트로 사용, 사이트당 ≤32라인, 2·3차 배치는 handler 진입·첫 하위 RPC 직전.
- plan 생성기: LBR 창의 handler 이름으로 miss 라인을 method별로 귀속(`cold_plan.py --by-method`).

### 2-C. affinity sweep (B-5, 대조군)
- pool 안에서 코어당 공유 서비스 수 1·2·3·전체로 cpuset 그룹을 만들어 MPKI 곡선. `dsb_shared_screen.sh`에 그룹 배치 모드 추가.

### 2-D. 커널 switch-in prefetch 모듈 (B-3)
- `llvm_prefetchit/kernel/wake_prefetch/`: opt-in TGID/mm, pinned executable page의 kernel alias, 8/16/32/64라인 T1/NOP, saved user IP/syscall profile. 등록은 root 전용 misc-device ioctl. 현재 헤더 빌드와 기본 runtime smoke를 통과했고 모듈은 언로드했다.
- 기존 trace의 추정 hook 이름은 정확한 syscall 번호가 아니다. 새 context 수집과 held-out 검증 후 user-timeline·compose-post·media를 비교한다.
- module-off/no-plan/NOP/PF 및 user-stream 조합을 비교하며, outgoing task에 잡히는 callback 비용까지 공유 풀 전체 CPU로 확인한다. 권한 확보·기본 runtime 검증 완료, 실서비스 성능 검증 대기.

---

## 3. 미측정·미완 벤치마크 (`docs/prefetch_plan_by_miss_class.md` §5, 2026-09-19 밤 갱신)
- 완료(탈락): DCPerf v2 batch 6종, TaoBench(클라이언트 확인), CloudSuite graph/in-memory-analytics, DaCapo h2o/fop/kafka, TailBench img-dnn/moses/shore/masstree, FleetBench 7종.
- **새 A 부류 후보: FleetBench proto_benchmark 16.9 MPKI(1코어)** → §1-A 순서(seq → cold plan → twin)로 바로 착수 가능.
- 추가 후보 **측정 완료(2026-09-21, `llvm_prefetchit/results/newcands_20260921/`)**: A 부류 신규 = ARM core-benchmarks frontend(dfs16 **72.1**, ipc3000 **48.9** MPKI, 1코어), MySQL 8(**2.35**, 4코어 75%), Rails+puma(**1.91**, 4코어 38%); B 부류 신규 = ScyllaDB(0.40 → **6.05–10.97** 공유 시), MySQL 8(→**9.25**), Rails(→**3.48**). 탈락 = ScyllaDB alone, finagle-http 0.26, OpenMM 0.01. 보류 = GHDL-LLVM(apt 충돌), BenchBase(JDK 23), HHVM(JIT), Ceph(셋업).
- 다음 착수 순서(A 부류): **ARM frontend ipc3000 → FleetBench proto → MySQL 8 → Rails**. ARM frontend는 생성기 자체의 `--insert_code_prefetches`가 있어 우리 pass와 직접 비교되는 유일한 후보다.
- 진행 중/미완: adsim 설치(libaegis 추가 후 재빌드), cdn_bench 측정(IPv6 루프백), TailBench silo/sphinx/xapian(입력 재다운로드), ucache_bench(디스크), data-analytics(YARN NodeManager 등록 실패), media-streaming(클라이언트 ssh), video_transcode 클립, WDL/Mediawiki/Spark, μSuite SetAlgebra/HDSearch, 서버리스(vHive/vSwarm), hotel Go 삽입기.
- 디스크(2026-09-20 정리, 사용자 지시): 삭제 = DCPerf v1 빌드, DCPerf v2 탈락 패키지(adsim, cdn_bench, xsbench/gapbs/graph500/liblinear/schbench/syscall, TaoBench), TailBench moses/img-dnn/shore 입력, PostgreSQL·php/WordPress·ClickHouse 빌드, gem5 빌드, CloudSuite data-caching 이미지 → 69 GB 여유. 남긴 것 = django v2·feedsim v2(A 부류), TailBench 소스(silo/masstree), MariaDB(A-4), MicroSuite(SetAlgebra/HDSearch 미시도), SPEC2026(재설치 어려움), DaCapo 데이터·CloudSuite web-serving/web-search/data-serving 이미지(JVM/JIT 참고값).

## 4. 기록 규칙
- 결과 디렉토리 `<topic>_<yyyymmdd>/`, 요약은 README §2/§5 표와 `core_results.tsv`에만.
- 각 워크로드 한 행: speedup vs base, vs twin, MPKI before→after, 명령 수, 세팅(코어·C6·regime·활용률). A 부류는 정적 링크 몫과 prefetch 몫 분리.
- 실패도 원인(축: cold/capacity/interleaving, 리드타임, outstanding 한도, 오버헤드, 도구 범위 밖)과 함께 남긴다.
