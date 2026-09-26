# 추가 A-3 / A-2 탐색 — 2026-09-24

신규 유망 후보는 **Ceph RGW 19.2.3의 인증된 S3 혼합 요청**이다. 아래는
qualification과 초기 진단이며 prefetch 성능 향상 확정 결과가 아니다.
작업 기록은 `llvm_prefetchit/results/class_a_search_20260924b/`에 있다.

## 정상 설정과 측정 범위

- S3 GET 70%, LIST 10%, PUT 20%; 96개 객체, 4/16/64 KiB 균등 크기.
  PUT은 같은 key의 내용을 다시 저장한다. 모든 GET 본문과 LIST의 96개 key 수를
  client가 검사한다. unsigned GET은 403을 확인했다. SigV4와 cephx를 유지한다.
- 실제 RADOS/BlueStore OSD 3개, replication 3 / min_size 2, monitor와 manager.
  OSD는 서로 다른 CPU에 배치한다. 3 GiB regular-file backing / OSD는 사설 CPU 경로
  실험용이며, production storage throughput 또는 host 장애 내성을 대표하지 않는다.
  객체 수·크기는 code miss를 만들기 위해 부풀리지 않았다.
- RGW 4 workers / cores 32–35, client cores 16–19. 추가로 1 worker / core 32를 검증했다.
  2 GHz, turbo/C6 off, 고정 uncore. **모든 실제 thread affinity를 측정 전후 검사**한다.
  카운터는 user-mode `L2_RQSTS.CODE_RD_MISS` 및 instructions/top-down이다.
  CPU utilization은 task-clock / (wall time × allocated cores).
- 다른 사용자의 QEMU는 변경하지 않았다. 이 공유 호스트에서 얻은 탐색 결과이므로
  speedup은 별도의 반복 비교가 필요하다. 후반 Ceph `MON_DISK_LOW` 경고는
  호스트 여유 공간에 대한 것이며, OSD 3개는 up, 모든 PG는 active+clean이었다.
  로그에 경고를 숨기지 않았다. 매 실행 전 여유 공간을 검사한다.

## Ceph RGW qualification

| 설정 | 목표 req/s | 실제 req/s | 코어 활용률 | L2 code MPKI | p99 | 검증 오류 |
|---|---:|---:|---:|---:|---:|---:|
| 기본 로그, GET, 4 workers | 1,000 | 998.62 | 13.23% | 6.806 | 0.844 ms | 0; 활용률 미달 |
| 기본 로그, GET, 4 workers | 2,000 | 1,998.04 | 25.35% | 6.649 | 33.15 ms | 0 |
| 기본 로그, 혼합, 4 workers | 1,000 | 998.71 | 19.72% | 8.294 | 4.51 ms | 0 |
| 기본 로그, 혼합, 4 workers | 2,000 | 1,998.70 | 38.43% | 8.245 | 33.31 ms | 0 |
| debug_rgw=0/0, access log 유지, 혼합 | 1,000 | 999.22 | 16.67% | 8.854 | 7.69 ms | 0 |
| debug_rgw=0/0, access log 유지, 혼합 | 2,000 | 1,998.69 | 33.09% | 8.944 | 33.22 ms | 0 |
| debug/access log 모두 0/0, 4 workers | 1,500 | 1,499.53 | 23.56% | 7.618 | 42.88 ms | 0 |
| debug/access log 모두 0/0, **1 worker** | 600 | 598.67 | 30.25% | **6.963** | 7.35 ms | 0 |
| debug/access log 모두 0/0, **1 worker** | 1,000 | 992.78 | 49.23% | **5.910** | 18.17 ms | 0 |

이는 요청당 gateway CPU 효율을 실험할 수 있는 부하점이다. 최대 throughput 측정이
아니며 네트워크는 localhost HTTP이다. RGW debug/access logging을 모두 꺼도,
그리고 단일 worker/코어에서도 높은 miss가 남는다. 쿼리·입력 의미는 유지했다.

모든 로그를 끈 4-worker/1,500 req/s에서 raw top-down은 retiring 24.77%, bad speculation
6.46%, frontend-bound 49.26%, backend-bound 22.32%, fetch latency 36.69%였다.
perf의 slot 비율을 그대로 보고하며 합계를 강제로 100%로 보정하지 않는다.
backend 비율이 0이 아니므로 MPKI 감소가 그대로 성능 이득이 된다고 주장하지 않는다.

## 간접 호출 / 직접 호출 진단

같은 4-worker/1,500 req/s, debug/access log off 설정에서
`FRONTEND_RETIRED.L2_MISS` PEBS + 32-entry user LBR를 수집했다.
19,939개 표본이며 recording/decoding log에 lost-event 경고가 없었다.

| 최근 32개 LBR와 miss IP의 관계 | 간접 CALL | 직접 CALL |
|---|---:|---:|
| target과 같은 64-byte cache line | **8.88%** | **30.19%** |
| target 이후 256-byte 범위 | **10.89%** | **41.27%** |
| target과 같은 알려진 함수 | 9.40% | 36.50% |

분모는 unresolved 표본을 포함한 전체다. 함수 이름을 해석하지 못한 표본은 5,357개
(26.87%)다. 주소 기반 같은 line/+256 관계에는 심볼 이름이 필요하지 않다.
LBR 근접성은 call stack이나 인과관계, critical-path stall 비율, speedup 상한이 아니다.
두 CALL 열은 겹칠 수 있으므로 더하지 않는다.

miss IP의 DSO 비중은 radosgw 70.06%, libceph-common 11.03%, librados 7.11%이다.
간접 target은 인증 applier, `RGWRESTMgr_S3::get_handler`, `RGWOp::init_quota`,
SAL storage method, Asio completion, `AsyncConnection::send_message` 등에 분산돼 있다.
`RGWGetObj::execute` 첫 256 bytes는 전체의 0.10%, `RGWPutObj::execute`는 0.075%에
그쳐 **execute 하나만 미리 읽는 방법으로 3–5%를 기대할 근거는 없다.**

따라서 A-3의 live object/vtable target 실험 후보로 남기되, 인증·storage·completion의
여러 호출 구간을 다뤄야 한다. 직접 callee miss도 많아 같은 코드베이스에서 A-2 방식의
정적 call graph 실험과 F/G/F+G 비교를 진행할 가치가 있다. 먼저 기존 범용 정적
callee lookahead의 제한된 NOP-site 실험도 수행했다.

정적 정책은 miss trace로 site/target을 고르지 않는다. binary의 알려진 직접 callee를
선택해 함수 내부의 기존 7/8-byte NOP를 같은 길이의 `prefetcht1`으로 바꾼다.
`g128`은 최소 128 / 최대 2,048 static bytes 앞의 callee(4,868 sites), `g512`는
최소 512 / 최대 8,192 bytes(2,972 sites)다. 이는 실제 cycle lead나 완전한 CFG
분석이 아니며, 제한된 static direct-callee 정책이다.

| 1 worker, 600 req/s, 2쌍 역순 비교 | 요청당 CPU 효율 변화 | 각 쌍 |
|---|---:|---|
| g128 | **+0.007%** | +0.018%, −0.004% |
| g512 | **−0.131%** | −0.697%, +0.438% |

원본이 byte-exact NOP twin이다(각 patch를 되돌린 hash 확인). 별도 12초 warmup 뒤
32초 동안 server thread만 perf로 측정하고, 그 client가 검증 완료한 실제 요청 수로
CPU time을 나눴다. 모든 응답 검증 오류는 0, 실제 약 598 req/s, p99 5.81–6.47 ms였다.
두 정책 모두 탈락했으며 바이너리를 삭제했다. **새 speedup, 1% 이득, call-graph 방식의
성능 상한을 확인한 결과가 아니다.** 새로운 live-target F 또는 F+G는 아직 미실험이다.

live operation은 `retarget`가 바꿀 수 있다. 이후의 유효한 op에서 future method를
읽어야 하며, IO yield를 넘겨 너무 일찍 prefetch하면 유지되지 않을 수 있다.
[해당 버전의 request 처리 코드](https://github.com/ceph/ceph/blob/v19.2.3/src/rgw/rgw_process.cc)
기준으로 `init_processing` 뒤→`verify_permission`, `verify_params` 뒤→`execute`는
검토할 수 있는 구간이지만, 아직 이 F 삽입을 구현하거나 효과를 검증한 것은 아니다.

## 추가 후보의 음성 결과

| 후보 / 정상 작업 | L2 code MPKI | 결과 |
|---|---:|---|
| LibreOffice 24.2, 공식 Math Guide ODT→PDF | 0.145–0.149 | 출력 PDF 확인; 낮은 MPKI |
| ns-3 Wi-Fi TCP / UDP | 0.0056 / 0.0122 | 표준 train 입력, stdout 기준 출력과 완전 일치 |
| ns-3 Wi-Fi EHT / DCTCP | 0.1185 / 0.0126 | 표준 ref 개별 입력, stdout·DCTCP 데이터 기준 출력과 일치 |
| OMNeT++ RandomMesh, 484 nodes, 4 runs | 0.0252 | scalar 출력 4개 모두 기준과 byte-identical |
| Cppcheck, 3 Gmsh C++ 파일 exhaustive analysis | 0.0031 | diagnostic/report 기준 출력과 byte-identical |
| Yosys 0.33, PicoRV32 RV32I / RV32IM 합성 | 0.0357 / 0.0400 | structural check 통과; 합성물 hash/cell 수 보존 |
| Traffic Server, pinned 1/2 workers, cache hit | 0.008–0.014 | 응답 본문/처리율 정상, 낮은 MPKI |
| Traffic Server, pinned TLS+20% origin mix | 0.148–0.198 | 낮은 MPKI; 높은 p99도 별도 기록 |

**Traffic Server의 초기 16–42 MPKI는 폐기했다.** `taskset`과 affinity 설정에도
ET_NET thread가 전체 86개 CPU로 mask를 넓혀, 고정 코어/C6-off 조건에서 벗어났다.
전체 thread를 실제로 pin한 뒤 위의 낮은 결과를 얻었다. 초기 수치를 A-3 후보나
prefetch 성능 이득으로 사용하지 않는다. 향후 모든 service harness에서 thread mask
검사를 필수로 한다.

LibreOffice의 Phoronix 20-document 묶음은 다운로드 403으로 실행하지 못했다.
대신 공식 Math Guide 24.8 원본 ODT를 사용했으므로 이를 Phoronix 점수라고 부르지 않는다.
Yosys는 [PicoRV32](https://github.com/YosysHQ/picorv32/commit/ef203c2b0a3fb793280f5114941416c425c5b461)
원본 RTL을 사용했다. 위 SPEC 개별 작업은 공식 SPEC score가 아니다.

실패/탈락한 private 실행 파일·작업 복사본·PDF·netlist·scalar 출력은 hash와 검증
결과를 남긴 뒤 정리했다. 원본 source/input/package는 보존했다. Ceph의 현재 control과
필요한 trace는 다음 실험용으로 유지한다.


## 보존 결과

GitHub에는 [qualification 요약](../llvm_prefetchit/migration/evidence/class_a_search_20260924b/qualification.json)과 정적 탐색 요약을 공개한다.
27개 qualification 행, 6개 정적 정책 비교 trial, 19,939개 PEBS 표본 분석,
175개 platform context 복원 검증의 상세 압축 archive는 로컬에 보존하며 Git에는 넣지 않는다.

정지한 Ceph의 생성 replica/index/backing store·임시 로그/자격 증명 등 **9,365,291,008 bytes**를
정리했다. S3 원본 객체 96개의 실제 byte는 모두 dataset hash와 대조했고,
2,752,512-byte 논리 입력을 9,399-byte tar.gz로 별도 보존했다. 원본 입력의 손실은 없다.
탈락한 두 prefetch binary, ATS private binary/cache, PDF/netlist/scalar 사본도 정리했다.

원본 패키지·문서와 현재 Ceph 기준 binary 등 28개 파일은
`/fast-lab-share/hnpark2/prefetchit/archives/20260924T211605Z-class-a-search`
에 단일 rsync 20 MiB/s로 백업하고, 별도 순차 20 MiB/s SHA-256 검증을 마쳤다.
112,702,811 bytes는 local symlink로 전환했다. Ceph의 현재 기준 binary와 필요한
16 MB perf trace는 local에 남겼다. NAS alias를 직접 timing하지 말고 local로 stage해야 한다.
모든 사설 service는 정지했다.
