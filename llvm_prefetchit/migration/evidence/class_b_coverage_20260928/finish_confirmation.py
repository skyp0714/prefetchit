from pathlib import Path
import sys,json
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,coverage_evaluate,lean_evaluate
r=Path('/storage/prefetchit/class_b_coverage_20260928')
miss=coverage_evaluate.evaluate(r/'confirmation',r/'confirmation_miss.json')
e2e=lean_evaluate.evaluate(r/'confirmation',candidate='selected_it0',matched_nop='selected_nop',out=r/'confirmation_evaluation')
contrasts=miss['comparisons']['selected_it0']
checks={c:dict(estimate=x['sum:FE_L2']['cost_reduction_pct'],ci95=x['sum:FE_L2']['ci95_pct'],confirmed=x['sum:FE_L2']['pairs']==6 and x['sum:FE_L2']['ci95_pct'][0]>0) for c,x in contrasts.items()}
result=dict(selection=json.load(open(r/'confirmation_selection.json')),miss_checks=checks,code_miss_confirmed=all(x['confirmed'] for x in checks.values()),e2e_confirmed=e2e['decisions']['selected_it0']['confirmed'],e2e_decision=e2e['decisions']['selected_it0'],interpretation='Independent6seed paired-log t95 intervals vs original and matching NOP bundle. Code-miss and E2E conclusions are separate; no pooling with any exploratory stage.')
b.save(r/'final_decision.json',result)
print(json.dumps(dict(miss=checks,e2e_confirmed=result['e2e_confirmed']),indent=2),flush=True)
