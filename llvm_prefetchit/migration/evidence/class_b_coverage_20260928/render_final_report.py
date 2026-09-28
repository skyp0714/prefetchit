from pathlib import Path
import json,statistics,subprocess
r=Path('/storage/prefetchit/class_b_coverage_20260928');repo=Path('/home/hnpark2/prefetchit')
read=lambda p:json.loads(p.read_text())
final=read(r/'final_decision.json');miss=read(r/'confirmation_miss.json');e2e=read(r/'confirmation_evaluation/evaluation.json');diag=read(r/'selected_diagnostic_summary.json')['selected'];selection=final['selection']['selected']
path=repo/'docs/class_b_coverage_20260928.md';methods=path.read_text().split('## 구현',1)[1].split('\n\nCompact evidence:',1)[0].rstrip()
labels={'coverage_full_it0':'V6 직접 확대','coverage_weighted_it0':'V6 발행 축소','indirect_it0':'V7 간접 타깃','lift_it0':'V8 상위 caller','paths_it0':'V9 경로 보존','base':'원본'}
names={'movie':'MovieId','compose':'ComposeReview','rating':'Rating'}
def effect(v):
 ci=v.get('ci95_pct');return f"{v['cost_reduction_pct']:+.3f}%"+(f" [{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else '')
def mean(arm,metric):return statistics.mean(x['metrics'][metric] for x in miss['rows'] if x['arm']==arm)
total=sum(read(r/name/'complete.json')['rows'] for name in ('screen','screen_indirect','screen_paths','confirmation'))
lines=['# 코드 미스 타깃 확대와 경로 보존: 독립 검증','',f'Media 전체 스택의 유효한 clean E2E 실행 {total}회를 완료했다. 학습·잔여 미스 진단은 이 실행 수와 성능 판정에 섞지 않았다. 최종 조합은 '+', '.join(f"{names[k]}={labels[v['name']]}" for k,v in selection.items())+'다.','']
for control,label in [('base','원본'),('selected_nop','동일 배치 NOP 조합')]:
 v=miss['comparisons']['selected_it0'][control]['sum:FE_L2'];lines.append(f"- 합산 FE_L2/request 절감 vs {label}: **{effect(v)}**")
lines += ['',f"독립 코드 미스 기준: **{'통과' if final['code_miss_confirmed'] else '미통과'}**. 별도 E2E 승격 기준: **{'통과' if final['e2e_confirmed'] else '미통과'}**. 미스 감소만으로 요청 성능 개선을 선언하지 않는다.",'','모든 절감률은 양수가 개선이다. 6개 새 seed block의 개별 paired-log t95 구간이며, 탐색 자료를 합치거나 요청들을 독립 반복으로 세지 않았다.','', '![독립 코드 미스와 요청 성능 효과](figures/class_b_coverage_effects_20260928.png)','', '## 독립 확인: 요청 성능','', '| 비교 기준 | 전체 CPU/request 절감 | 평균 지연 절감 | p99 절감 | 처리량 증가 |','|---|---:|---:|---:|---:|']
for control,label in [('base','원본'),('selected_nop','자체 NOP')]:
 v=e2e['comparisons']['selected_it0'][control];tp=e2e['throughput']['selected_it0'][control];ci=tp['ci95_pct']
 lines.append(f"| {label} | {effect(v['stack_cpu'])} | {effect(v['mean_ms'])} | {effect(v['p99_ms'])} | {tp['gain_pct']:+.3f}% [{ci[0]:+.3f}, {ci[1]:+.3f}] |")
lines += ['', '| 조건 | CPU µs/request | 평균 ms | 실행별 p99 평균 ms | RPS | CPU util % |','|---|---:|---:|---:|---:|---:|']
for arm in ('base','selected_nop','selected_it0'):
 x=e2e['means'][arm];lines.append(f"| {arm} | {x['stack_cpu']:.2f} | {x['mean_ms']:.5f} | {x['p99_ms']:.5f} | {x['rps']:.2f} | {x['util_pct']:.2f} |")
user_cpu=sum(e2e['services']['base'][k]['user_us_per_request'] for k in ('movie-id-service','compose-review-service','rating-service'))
lines += ['',f"수정한 세 서비스의 원본 user CPU 합계는 {user_cpu:.2f} µs/request로 전체 CPU/request의 {100*user_cpu/e2e['means']['base']['stack_cpu']:.2f}%였다. 이는 지연 개선의 엄격한 상한은 아니지만, 대상 코드의 미스 감소율을 전체 CPU 절감률로 옮길 수 없는 이유다. C4 closed-loop 처리량과 평균 지연은 서로 연결된 지표이며, 최대 처리량을 새로 측정한 결과는 아니다."]
lines += ['','## 독립 확인: 서비스별 미스','', '| 서비스 / 적용 정책 | 원본 FE_L2/request | 선택 FE_L2/request | 절감 vs 원본 | 절감 vs 자체 NOP |','|---|---:|---:|---:|---:|']
for k,name in names.items():
 metric=k+':FE_L2';a=miss['comparisons']['selected_it0']['base'][metric];n=miss['comparisons']['selected_it0']['selected_nop'][metric]
 lines.append(f"| {name} / {labels[selection[k]['name']]} | {mean('base',metric):.2f} | {mean('selected_it0',metric):.2f} | {effect(a)} | {effect(n)} |")
lines += ['', '동일 배치 NOP 조합 자체의 합산 FE_L2/request 절감 vs 원본은 '+effect(miss['comparisons']['selected_nop']['base']['sum:FE_L2'])+'였다. 이 차이를 모두 prefetch 발행 효과로 계산하지 않았다.']
lines += ['','## 별도 PMU 지표','', '| 지표 / 세 서비스 정규화 값의 합 | 절감 vs 원본 | 절감 vs 자체 NOP |','|---|---:|---:|']
metrics=[('sum:L2I','Speculative L2I/request'),('sum:cycles:u','User cycles/request'),('sum:instructions:u','Retired instructions/request'),('sum:ITLB_WALK','ITLB walks/request'),('extra:frontend:sum:FE_L1','Retired FE_L1/request'),('extra:frontend:sum:ICACHE_DATA_STALL','I-cache data-stall events/request'),('extra:frontend:sum:ICACHE_TAG_STALL','I-cache tag-stall events/request'),('extra:frontend:sum:BACLEARS','BACLEAR events/request'),('extra:frontend:sum:ITLB_WALK_ACTIVE','ITLB walk-active events/request')]
for metric,label in metrics:
 a=miss['comparisons']['selected_it0']['base'].get(metric);n=miss['comparisons']['selected_it0']['selected_nop'].get(metric)
 if a and n:lines.append(f"| {label} | {effect(a)} | {effect(n)} |")
lines += ['', '| 이벤트 / 1,000 retired instructions | 원본 | 선택 조합 |','|---|---:|---:|']
for label,metric,denom in [('Retired FE_L2','sum:FE_L2','sum:instructions:u'),
                          ('Speculative L2I','sum:L2I','sum:instructions:u'),
                          ('Retired FE_L1','extra:frontend:sum:FE_L1','extra:frontend:sum:instructions:u')]:
 values=[1000*mean(arm,metric)/mean(arm,denom) for arm in ('base','selected_it0')]
 lines.append(f"| {label} | {values[0]:.3f} | {values[1]:.3f} |")
lines += ['', '이 비율은 해당 PMU 묶음의 세 서비스 request-normalized 평균을 합산해 계산했다. PMU와 PEBS는 대상 cgroup의 모든 사용자 스레드를 포함한다. 요청 critical path에 속하는 미스만을 별도로 식별하지 않았으므로, event 감소율을 지연 감소율로 바꾸지 않았다. Speculative 요청과 retired 이벤트의 모집단이 달라 두 값의 차이를 wrong-path 비중이나 노출된 stall로 환산하지 않았다.']
lines += ['','FE_L2는 retired frontend event, L2I는 speculative instruction-fetch miss 집합이다. 정지·page-walker 이벤트는 서로 겹칠 수 있어 합산 손실률이나 특정 미스 원인의 비중으로 바꾸지 않았다. 서로 다른 frontend selector는 별도 PMU 창에서 측정했다.',
 '', '이번 조합의 이득은 retired L2 미스 감소에서 가장 뚜렷하다. 원본 대비 retired L1 미스는 4.64%, 명령어 수는 1.41% 증가했고, I-cache data/tag 정지와 user cycles의 감소는 확인되지 않았다. 추가 실행과 L1 동작이 L2 이득을 상쇄했을 가능성은 있지만, 이 카운터만으로 각각의 인과 효과를 분해할 수는 없다. ITLB walk와 BACLEAR에도 일관된 개선이 없어 BTB/FDIP 또는 ITLB를 단일 원인으로 확정하지 않았다.',
 '', '## 탐색 결과: 독립 확인과 분리','', '| 구현 | 합산 FE_L2 절감 vs 원본 | vs 자체 NOP | 전체 CPU 절감 vs 원본 | 평균 절감 vs 원본 |','|---|---:|---:|---:|---:|']
for mf,ef in [('screen_miss.json','screen_evaluation/evaluation.json'),('indirect_screen_miss.json','indirect_screen_evaluation/evaluation.json'),('paths_screen_miss.json','paths_screen_evaluation/evaluation.json')]:
 m=read(r/mf);e=read(r/ef)
 for arm,decision in m['decisions'].items():
  nop=next(c for c in decision['contrasts'] if c!='base');a=m['comparisons'][arm]['base']['sum:FE_L2']['cost_reduction_pct'];n=m['comparisons'][arm][nop]['sum:FE_L2']['cost_reduction_pct'];p=e['comparisons'][arm]['base']
  lines.append(f"| {labels[arm]} | {a:+.3f}% | {n:+.3f}% | {p['stack_cpu']['cost_reduction_pct']:+.3f}% | {p['mean_ms']['cost_reduction_pct']:+.3f}% |")
lines += ['','각 행은 해당 단계의 2-block 탐색 점추정이다. 정책별 자체 NOP와 원본을 비교했고 단계끼리 표본을 합치지 않았다. 서비스별 반응 차이를 보고, 각 서비스에서 양쪽 대조군보다 두 block 모두 FE_L2가 낮았던 정책 중 최소 비교 효과가 가장 큰 것을 선택했다. 이 조합 자체의 성능은 탐색 수치를 더해 추정하지 않고 6개 새 seed의 전체 스택 실행으로 검증했다. 선택 방식 변경 시점과 이유는 `confirmation_strategy_amendment.json`에 보존했다.','', '## 선택 조합의 잔여 미스와 선행 힌트','', '| 서비스 | main-image 표본 비중 | 잔여 main 미스 중 정적 target line 중첩 | 잔여 main 미스 중 선행 LBR 경로에서 matching hint 관측 |','|---|---:|---:|---:|']
for k,name in names.items():
 x=diag[k]['events']['l2'];main=x['main_pct'];lines.append(f"| {name} | {main:.2f}% | {100*x['static_target_pct']/main:.2f}% | {100*x['observed_matching_pf_pct']/main:.2f}% |")
lines += ['','분모는 선택 조합에서 관측된 미스이며 피한 미스는 포함되지 않는다. 유한한 retired LBR 경로에서 같은 line을 겨냥한 힌트가 관측됐다는 뜻으로, 하드웨어 발행 수·fill 성공·정확한 fetch lead·BTB 실패 원인의 증명이 아니다. PEBS와 LBR profiling 결과는 clean E2E 결과에 섞지 않았다.']
ages=[]
for k,name in names.items():
 h=diag[k]['events']['l2']['lead'];ages.append(f"{name} {100*h.get('prior_block_minage_0-31',0)/sum(h.values()):.1f}%")
lines += ['', 'Matching hint가 관측된 잔여 미스 중 LBR retired-cycle 최소 나이 proxy가 0–31인 비중은 '+', '.join(ages)+'였다. 이는 retired 분기 기록으로 만든 하한 proxy이며 실제 issue-to-fetch lead time은 아니다. 후속 실험에서는 이미 겨냥한 MovieId/ComposeReview 타깃의 발행 위치·예산을 바꾸고, Rating의 타깃 밖 entry를 별도로 겨냥하는 것이 구체적인 탐색 방향이다. 성공한 fill과 너무 늦거나 무시된 hint는 이 자료로 분리하지 못한다.']
residual=read(r/'residual_location_summary.json')['services']
lines += ['', '| 서비스 | 타깃 entry line | 타깃 밖 entry line | 함수 내부 line | symbol 경계 불명확 |','|---|---:|---:|---:|---:|']
for k,name in names.items():
 x=residual[k]['selected']['pct'];inside=sum(x.get(key,0) for key in ('targeted_interior','untargeted_interior'))
 lines.append(f"| {name} | {x.get('targeted_entry',0):.2f}% | {x.get('untargeted_entry',0):.2f}% | {inside:.2f}% | {x.get('unknown_or_overlapping_symbol',0):.2f}% |")
lines += ['', '각 비율의 분모는 해당 선택 바이너리의 잔여 main-image 표본 전체다. entry는 함수 시작 주소가 속한 64B line이며 alias는 한 번만 세고 겹치는 symbol은 경계 불명확으로 남겼다. 원본과 선택 바이너리의 주소를 직접 대조하지 않았다.','', '| 서비스 | 잔여 main 미스 상위 함수 | main 표본 비중 |','|---|---|---:|']
for k,name in names.items():
 for x in residual[k]['selected']['functions'][:3]:
  symbol=subprocess.check_output(['c++filt',x['names'][0]],text=True).strip().replace('|','/').replace('`','')
  if len(symbol)>150:symbol=symbol[:147]+'...'
  lines.append(f"| {name} | `{symbol}` | {x['main_share_pct']:.2f}% |")
lines += ['', '이 상위 함수와 주소 분류는 다음 타깃 선정에 사용할 잔여 미스 진단이다. 한 번씩의 profiling 표본이므로 함수별 성능 개선의 반복 검증을 대신하지 않는다.', '', '## 원본 변동과 검증','']
x=e2e['variation']['base'];base_miss=[row['metrics']['sum:FE_L2'] for row in miss['rows'] if row['arm']=='base'];cv=100*statistics.stdev(base_miss)/statistics.mean(base_miss)
lines += [f"6회 원본의 실행 간 CV는 CPU/request {x['stack_cpu']['sample_cv_pct']:.3f}%, 평균 지연 {x['mean_ms']['sample_cv_pct']:.3f}%, p99 {x['p99_ms']['sample_cv_pct']:.3f}%, 합산 FE_L2/request {cv:.3f}%였다.",'','최종 compiler/분기 경로 검사 29개를 통과했다. 각 실제 ELF의 원본 main symbol binding, RIP-relative IT0 대상 instruction boundary와 exact-layout NOP를 검증했다. 실패·대체된 생성물은 결과·설정·명령·소스·패치·해시를 남긴 뒤 정리했다.']
lines += ['', '현재 CPU의 읽기 전용 CPUID 검사에서도 leaf 7/subleaf 1 EDX=0xe4000, PREFETCHI bit 14=1을 확인했다. 기능 비트와 64-bit RIP-relative 조건은 [Intel ISA reference](https://cdrdv2-public.intel.com/819680/architecture-instruction-set-extensions-programming-reference.pdf)를 기준으로 확인했다. 기능 지원 여부가 개별 힌트의 fill 성공을 증명하지는 않는다.']
audit=read(r/'final_environment_audit.json');retention=read(r/'final_retention.json')
lines += ['',f"환경 감사: 유효 E2E {audit['valid_e2e_trials']}회, PMU {len(audit['pmu_windows'])}개 창 모두 fully scheduled, PEBS {len(audit['sample_captures'])}개 capture 총 {sum(v['samples'] for v in audit['sample_captures']):,}개 표본에서 유실·throttle 0. 플랫폼과 scheduler 설정을 복구했고 실험 컨테이너 및 prefetch 커널 모듈이 남지 않았다. 정적 커버리지 12개 값도 보존한 입력으로 재계산해 일치함을 확인했다.",
 '',f"독립 코드 미스 감소가 확인된 선택 ELF와 동일 배치 NOP {len(retention['candidates'])}개를 후속 비교 기준으로 보존했다. E2E 개선은 확인되지 않았다. 대체·탈락 ELF, 테스트 생성물, raw/decoded trace와 DSO 복사본은 각 결과를 추출한 뒤 삭제 manifest와 함께 정리했다. 원본 실행 파일·입력·소스·공유 의존성은 유지했고 NAS 전송은 하지 않았다."]
i=read(r/'indirect_static.json');d=read(r/'static_coverage.json')
lines += ['', '| 최종 선택 서비스 | 정적 힌트 수 | executable section 증가 vs 원본 |','|---|---:|---:|',
 f"| MovieId / V7 | {i['indirect']['movie']['hints']:,} | {i['indirect']['movie']['growth_pct']:.3f}% |",
 f"| ComposeReview / V8 | {i['lift']['compose']['hints']:,} | {i['lift']['compose']['growth_pct']:.3f}% |",
 f"| Rating / V6 | {d['rating']['hints']:,} | {d['rating']['executable_growth_pct']:.3f}% |", '', '## 구현'+methods]
text='\n'.join(lines)
text=text.replace('## 같은 원본 표본에서의 정적 타깃 중첩','## 같은 원본 표본에서의 정적 타깃 중첩')
text+='\n\nCompact evidence: [`llvm_prefetchit/migration/evidence/class_b_coverage_20260928`](../llvm_prefetchit/migration/evidence/class_b_coverage_20260928).\n'
path.write_text(text)
print(path)
