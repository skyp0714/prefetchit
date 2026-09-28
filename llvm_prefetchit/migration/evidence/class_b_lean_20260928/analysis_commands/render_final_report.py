from pathlib import Path
import datetime,json
r=Path('/storage/prefetchit/class_b_lean_20260928');repo=Path('/home/hnpark2/prefetchit')
def read(p):return json.loads(p.read_text())
decision=read(r/'final_decision.json');assert read(r/'late_sequence.json')['complete']
phases=[p for p in ('screen_v1','screen_v2','screen_v3','screen_v4','confirmation_c4','confirmation_c16','screen_v5') if (r/p/'complete.json').exists()]
total=sum(read(r/p/'complete.json')['rows'] for p in phases)
lines=['# 10–20µs 중심 prefetch: 삽입 축소와 E2E 검증','',
 f'2026-09-28의 약 7시간 캠페인에서 {total}회의 유효한 Media 전체 스택 성능 실행을 완료했다. MovieId·ComposeReview·Rating을 함께 변경했고, C4(약 85% util)와 C16(이전 처리량 plateau 부근)을 독립 비교했다. 별도 PMU/PEBS/gate 진단은 이 실행 수와 성능 판정에 섞지 않았다.','']
if not decision['ten_percent_e2e_confirmed']:
 lines+=['**10% E2E 개선은 확인하지 못했다.** 코드 팽창과 삽입 수는 크게 줄였지만, 미스 감소가 요청 지연·처리량 개선으로 이어졌다고 확정할 수 있는 결과는 아래 독립 기준으로 판단한다.','']
for c in (4,16):
 d=read(r/f'confirmation_c{c}/evaluation.json');x=d['comparisons']['selected_candidate']['base'];cpu=x['stack_cpu'];mean=x['mean_ms'];passed=d['decisions']['selected_candidate']['confirmed']
 lines.append(f'- v4 ungated C{c}: 전체 CPU/request 절감 {cpu["cost_reduction_pct"]:+.3f}% (95% CI {cpu["ci95_pct"][0]:+.3f}~{cpu["ci95_pct"][1]:+.3f}%), 평균 절감 {mean["cost_reduction_pct"]:+.3f}%. 사전 승격 기준 {"통과" if passed else "불통과"}.')
if (r/'screen_v5/complete.json').exists():
 d=read(r/'screen_v5/evaluation.json');x=d['comparisons']['callees_ungated_it0']['base'];eligible=d['decisions']['callees_ungated_it0']['point_eligible']
 lines.append(f'- v5 callee ungated: 별도 2-block 탐색에서 원본 대비 CPU 절감 {x["stack_cpu"]["cost_reduction_pct"]:+.3f}%, 평균 절감 {x["mean_ms"]["cost_reduction_pct"]:+.3f}%. 원본/NOP 양쪽 점추정 기준 {"통과" if eligible else "불통과"}. 독립 확인을 하지 않아 확정 개선으로 승격하지 않았다.')
else:lines.append('- v5의 완료된 E2E 탐색은 없다. 보존한 시간 예산 생략/실패 기록을 확인한다.')
lines+=['','양수는 비용 절감/개선이다. C4/C16 독립 자료와 각 탐색 자료는 합치지 않았다.','',
 '![독립 확인의 효과와 95% 구간](figures/class_b_lean_confirmation_20260928.png)','']
sections=(r/'final_sections.md').read_text().splitlines()[2:]
lines+=sections+['']
if (r/'v5_binary_audit.json').exists() and read(r/'late_sequence.json')['v5_valid']:
 base=read(r/'static_progression.json')['baseline'];audit=read(r/'v5_binary_audit.json')
 lines+=['## v5 실제 코드 크기','', '| 서비스 | 정적 IT0 수 | executable bytes 증가 vs 원본 |','|---|---:|---:|']
 for row in audit:
  if row['arm']!='callees_ungated':continue
  growth=100*(row['executable_bytes']/base[row['service']]['executable_bytes']-1)
  lines.append(f'| {row["service"]} | {row["prefetch_instructions"]} | {growth:+.3f}% |')
 lines+=['', '최종 대상은 원본과 새 main executable에 모두 정의되는 함수 entry이며 RIP-relative IT0, instruction boundary, 동일 배치 NOP를 감사했다. Gate/clock/runtime 심볼이 없는지도 확인했다.','']
if (r/'final_residual_locations.json').exists():
 data=read(r/'final_residual_locations.json')
 lines+=['## 미스 위치: entry와 함수 내부','']
 if (repo/'docs/figures/class_b_lean_timeline_20260928.png').exists():
  lines+=['![복귀 후 미스 밀도](figures/class_b_lean_timeline_20260928.png)','']
 lines+=['| arm / main-image 표본 | entry cache line % | 그 뒤 cache line % | symbol 미매핑·중복 % | v5 대상 entry line % | v5 대상 함수 내부 뒤쪽 line % |','|---|---:|---:|---:|---:|---:|']
 for row in data['rows']:
  for name,g in row['groups'].items():
   p=g['pct_of_main'];t=g['v5_selected_function_pct_of_main']
   target='—' if data['v5_target_function_names'] is None else f'{t.get("targeted_function_later_cache_line",0):.3f}'
   entry='—' if g['v5_selected_entry_line_pct_of_main'] is None else f'{g["v5_selected_entry_line_pct_of_main"]:.3f}'
   lines.append(f'| {row["name"]} / {name} | {p.get("entry_cache_line",0):.3f} | {p.get("later_cache_line",0):.3f} | {p.get("unmapped",0)+p.get("ambiguous",0):.3f} | {entry} | {target} |')
 lines+=['', '분모는 각 행의 main-image 잔여 PEBS 이벤트다. entry는 함수 시작 주소가 속한 64B line이며, 함수 시작부터 64바이트 전체를 의미하지 않는다. 함수 alias는 합치고 겹치는 symbol 범위는 제외했다. v5 함수 집합은 실제 감사한 target 이름이며 원본과 v5의 각 symbol 주소에 따로 적용했다. 정적 연관성으로 실제 issue/fill 성공률을 추정하지 않는다.','']
if (r/'final_interpretation.md').exists():lines+=[(r/'final_interpretation.md').read_text(),'']
lines+=[(r/'final_methods.md').read_text(),'']
retained=read(r/'artifact_retention.json')
lines+=['최종 보존 상태: v4 독립 확인 reference '+('보존' if retained['v4_confirmed_reference'] else '없음')+', v5 미확인 탐색 reference '+('보존' if retained['v5_exploratory_reference'] else '없음')+'. 원본 세 바이너리와 현재 compiler plugin·ABI2 module은 재현용으로 보존했다. 서비스는 정지했고 module은 해제했다.','']
out=repo/'docs/class_b_lean_20260928.md';out.write_text('\n'.join(lines));print(out)
