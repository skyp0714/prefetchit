from pathlib import Path
import sys,json
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,coverage_evaluate,lean_evaluate
r=Path('/storage/prefetchit/class_b_coverage_20260928')
miss=coverage_evaluate.evaluate(r/'screen_indirect',r/'indirect_screen_miss.json')
e2e=lean_evaluate.evaluate(r/'screen_indirect',out=r/'indirect_screen_evaluation')
eligible=[]
for arm,x in miss['decisions'].items():
 score=min(v['summary']['cost_reduction_pct'] for v in x['contrasts'].values())
 if x['miss_screen_eligible']:eligible.append((score,arm))
 print(arm,{c:dict(pairs=v['paired_reductions_pct'],mean=v['summary']['cost_reduction_pct']) for c,v in x['contrasts'].items()},flush=True)
b.save(r/'indirect_screen_decision.json',dict(eligible=sorted(eligible,reverse=True),selected=max(eligible)[1] if eligible else None,miss_decisions=miss['decisions'],e2e_decisions=e2e['decisions'],interpretation='Exploratory selection on primary code-miss objective; E2E endpoints remain separate, not a production promotion.'))
print('E2E:',{a:{c:{m:round(v[m]['cost_reduction_pct'],3) for m in ('stack_cpu','mean_ms','p99_ms')} for c,v in comparisons.items()} for a,comparisons in e2e['comparisons'].items()},flush=True)
