from pathlib import Path
import json
r=Path('/storage/prefetchit/class_b_lean_20260928')
def read(path):return json.loads(path.read_text())
def effect(value,throughput=False):
    point=value['gain_pct' if throughput else 'cost_reduction_pct'];low,high=value['ci95_pct']
    return f'{point:+.3f}% [{low:+.3f}, {high:+.3f}]'
def means_table(d):
    lines=['| arm | CPU µs/request | RPS | 평균 ms | 실행별 p99 평균 ms | util % |','|---|---:|---:|---:|---:|---:|']
    for name,v in d['means'].items():lines.append(f'| {name} | {v["stack_cpu"]:.2f} | {v["rps"]:.2f} | {v["mean_ms"]:.5f} | {v["p99_ms"]:.5f} | {v["util_pct"]:.2f} |')
    return lines
lines=['# 독립 검증과 후속 탐색 결과 (자동 집계 초안)','']
for concurrency in (4,16):
    root=r/f'confirmation_c{concurrency}';d=read(root/'evaluation.json')
    assert d['rows']==18 and d['independent_confirmation']
    decision=d['decisions']['selected_candidate']
    lines += [f'## V4 ungated C{concurrency}: 사전 기준 {"통과" if decision["confirmed"] else "불통과"}','']+means_table(d)+['',
        '| 비교 기준 | CPU 절감 [95% CI] | 평균 절감 [95% CI] | p99 절감 [95% CI] | 처리량 증가 [95% CI] |',
        '|---|---:|---:|---:|---:|']
    for control in ('base','matched_nop'):
        x=d['comparisons']['selected_candidate'][control];t=d['throughput']['selected_candidate'][control]
        lines.append('| '+control+' | '+' | '.join([effect(x[k]) for k in ('stack_cpu','mean_ms','p99_ms')]+[effect(t,True)])+' |')
    lines += ['', '양수는 개선. 개별 paired-log t95 구간이며 6개 새 seed block을 사용했다. 전체 CPU·평균은 원본/NOP 양쪽 CI 하한 >0, p99는 양쪽 하한 >-2%가 기준이다. closed-loop 처리량과 평균 지연은 연관된 지표다.','',
        '| 원본 변동 | 최소 | 최대 | 실행 간 CV % |','|---|---:|---:|---:|']
    for name in ('stack_cpu','mean_ms','p99_ms'):
        v=d['variation']['base'][name];lines.append(f'| {name} | {v["min"]:.5f} | {v["max"]:.5f} | {v["sample_cv_pct"]:.3f} |')
    service=read(root/'service_comparisons.json')['comparisons']['selected_candidate']
    lines += ['', '| 서비스 | 전체 CPU 절감 vs 원본 [95% CI] | user CPU 절감 vs 원본 [95% CI] |','|---|---:|---:|']
    for name in ('movie-id-service','compose-review-service','rating-service'):
        lines.append(f'| {name} | {effect(service["base"][name+":cpu_us_per_request"])} | {effect(service["base"][name+":user_us_per_request"])} |')
    lines += ['', '서비스별 수치는 보조 분해이며 전체 E2E 판정과 별개다. 개별 구간에는 다중 비교 보정이 없다.','']
if (r/'screen_v5/complete.json').exists():
    d=read(r/'screen_v5/evaluation.json');lines += ['## V5 gate-free callee: 2-block 탐색, 독립 확인 미실시','']+means_table(d)+['',
        '| 비교 기준 | CPU 절감 % | 평균 절감 % | p99 절감 % | 처리량 증가 % |','|---|---:|---:|---:|---:|']
    for control in ('base','callees_ungated_nop'):
        x=d['comparisons']['callees_ungated_it0'][control];t=d['throughput']['callees_ungated_it0'][control]
        values=[x[k]['cost_reduction_pct'] for k in ('stack_cpu','mean_ms','p99_ms')]+[t['gain_pct']]
        lines.append('| '+control+' | '+' | '.join(f'{v:+.3f}' for v in values)+' |')
    lines += ['', '현재 표는 탐색 점추정이다. V4 확인실험과 합치거나 승격 근거로 사용하지 않는다.','']
    p99=d['comparisons']['callees_ungated_it0']['base']['p99_ms']['ci95_pct']
    lines += [f'원본 대비 p99 절감의 개별 95% 구간은 [{p99[0]:+.3f}, {p99[1]:+.3f}]%로 0을 포함한다. 두 쌍으로 p99 개선을 확정할 수 없다.','']
else:lines += ['## V5','', '완료된 V5 성능 비교가 없다. 생략/실패 기록을 확인한다.','']
if (r/'diagnostics_late/timeline_summary.json').exists():
    summary=read(r/'diagnostics_late/timeline_summary.json');lines += ['## 별도 진단','',
        '| arm | 서비스 | period | 복귀 후 <20µs event 비중 % | 10–20µs 비중 % | 전체 추정 event/request | 10–20µs main 잔여 미스의 정적 타깃 중첩 % |','|---|---|---:|---:|---:|---:|---:|']
    for v in summary['rows']:
        if v.get('gate_only'):continue
        overlap=v['peak10_20']['static_target_overlap_pct_of_main'];text='—' if overlap is None else f'{overlap:.3f}'
        lines.append(f'| {v["name"]} | {v["service"]} | {v["period"]} | {v["before20"]["share_pct"]:.3f} | {v["peak10_20"]["share_pct"]:.3f} | {v["all"]["estimated_events_per_request"]:.3f} | {text} |')
    lines += ['', 'PEBS retirement timestamp이며 fetch 시각이 아니다. 스케줄 나이는 kernel 복귀 시간도 포함한다. 정적 중첩은 남아 있는 sampled miss 중의 비율이며 원래 미스 커버리지·실제 발행·cache fill 성공률이 아니다. 현재 진단은 MovieId, 한 sample period이며 all3/C16 미스 분포 확인으로 일반화하지 않는다.','',
        '| gate 진단 서비스 | checks/s | early % | eligible % | expired % |','|---|---:|---:|---:|---:|']
    for v in summary['rows']:
        if not v.get('gate_only'):continue
        g=v['gate'];checks=g['checks'];counts={k:sum(t[k] for t in g['tiers']) for k in ('early','eligible','expired')}
        pct=['—' if not checks else f'{100*counts[k]/checks:.3f}' for k in counts]
        lines.append(f'| {v["service"]} | {checks/g["elapsed_s"]:.1f} | '+' | '.join(pct)+' |')
    lines += ['', 'Gate 카운터는 별도 callee counter build의 논리 그룹 결과다. PEBS는 켜지 않았으며 atomic counter 자체의 교란은 남는다. 하드웨어 prefetch 명령 발행 수 또는 fill 성공 수가 아니다.','']
(r/'final_sections.md').write_text('\n'.join(lines)+'\n')
print('Wrote final_sections.md from completed measurements; requires final interpretation and report integration.')
