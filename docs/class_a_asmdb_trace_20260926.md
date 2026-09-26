# Trace 기반 AsmDB식 삽입: 스킴 결과와 takeaway

**FleetBench Proto Arena에서 기존 정적 schema 방식의 이득을 높이지 못했다.** 전체 trace strict/relaxed는 baseline 대비 약 −1.94%, 기존 static은 같은 비교에서 +3.57%였다.

| 스킴 | 위치 / 힌트 | baseline 대비 speedup [95% CI] | 동일 배치 NOP 대비 | 고정 작업당 L2 code miss 변화 |
|---|---:|---:|---:|---:|
| screen / short | 512 / 651 | -0.43% [-0.50, -0.37] | +0.48% | -0.55% |
| screen / nominal | 512 / 717 | -0.53% [-0.64, -0.43] | +0.30% | +0.07% |
| screen / long | 512 / 792 | -0.53% [-0.66, -0.40] | +0.33% | -0.27% |
| broad_screen / broad2048 | 822 / 992 | -1.10% [-1.26, -0.93] | +0.97% | +0.51% |
| broad_screen / broad4096 | 822 / 992 | -1.16% [-1.27, -1.06] | +0.55% | +0.88% |
| broad_screen / inline | 7 / 7 | +0.07% [+0.02, +0.12] | -0.06% | -0.52% |
| full_screen / strict | 4096 / 6117 | -1.94% [-1.99, -1.90] | +1.23% | +1.64% |
| full_screen / relaxed | 4096 / 6274 | -1.94% [-2.07, -1.82] | +0.99% | +1.81% |

각 정책은 새 seed1의 3쌍 탐색이다. baseline 평균 ≥0.5%와 NOP 대비 양의 평균을 모두 요구한 후속 7쌍 확인 기준을 통과한 후보가 없다. short/nominal/long은 각각 58–186 / 117–373 / 234–746명령어 lead window를 사용했다. broad2048/4096은 실제 822위치로 수렴한 byte-identical 정책이므로 두 방법으로 세지 않는다.

Takeaway:

- **Prefetch 효과보다 삽입 비용이 컸다.** full strict/relaxed는 NOP 대비 +1.23/+0.99%지만 baseline 대비 모두 −1.94%다. stub으로 이동하고 복귀하는 분기·배치 비용을 포함한 순이득은 없다.
- **coverage를 늘려도 해결되지 않았다.** 4.49억 명령어 trace와 4,096위치까지 늘렸지만 고정 작업당 실제 code miss는 +1.64/+1.81%였다. PEBS 가중 coverage 추정은 동적 miss 제거율이 아니다.
- **기존 schema 정보가 이번 trace 정책보다 유효했다.** 동일 full-screen의 static은 +3.57% [3.44, 3.70]다. 다음 시도는 분기 없는 compiler 삽입과 발행 비용·lead·cold target 선별을 함께 다뤄야 한다.
- 이 결과는 FleetBench 한 workload의 T1 data-prefetch 변환 결과다. 원 논문의 제안 명령이나 일반 call graph 전체의 한계를 검증한 것은 아니다. 기존 NOP-only 7위치 방식도 NOP 대비 이득이 없다.

해석상 제한: 초기 screen/broad의 도달 확률 분모는 미래 창이 완전히 관측된 실행에 한정됐다. full-screen 이전에 모든 관측 trigger 실행을 분모에 넣도록 수정했다. 이전 정책의 타이밍은 보존하되 예측 정확도로 일반화하지 않는다. PT decode/검사 가능한 control-flow 오류는 0이지만 raw out-of-order 경고는 있었으며, stub 내부의 비동기 unwind metadata는 지원하지 않는다.

[정확한 수치](../llvm_prefetchit/migration/evidence/asmdb_trace_20260926/comparison.json) · [스킴 소스와 해시](../llvm_prefetchit/migration/schemes/asmdb_trace_20260926/README.md)

압축 재현 기록과 삭제 내역은 로컬 전용 `llvm_prefetchit/migration/evidence/retention_cleanup_20260926/{asmdb_reproduction.tar.gz,manifest.json}`에 보관한다. GitHub에는 포함하지 않는다.

완료된 실험의 중간 계획·패치·명령·측정·binary hash·제외 이유는 압축 기록에 통합했다. 탈락 바이너리, decoded trace/index, 원본 PT 캡처와 중복 loose 기록은 삭제했다. benchmark 원본 소스·입력 및 현재 유효한 static/reference는 보존했다.
