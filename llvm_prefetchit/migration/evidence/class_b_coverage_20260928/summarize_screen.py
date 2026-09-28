from pathlib import Path
import sys,json,gzip
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,coverage_evaluate,lean_evaluate,lean_profile
r=Path('/storage/prefetchit/class_b_coverage_20260928')
miss=coverage_evaluate.evaluate(r/'screen',r/'screen_miss.json')
e2e=lean_evaluate.evaluate(r/'screen',out=r/'screen_evaluation')
for arm,v in miss['decisions'].items():
 print(arm,{c:dict(pairs=x['paired_reductions_pct'],mean=x['summary']['cost_reduction_pct']) for c,x in v['contrasts'].items()},flush=True)
print('E2E:',{a:{c:{m:round(v[m]['cost_reduction_pct'],3) for m in ('stack_cpu','mean_ms','p99_ms')} for c,v in comparisons.items()} for a,comparisons in e2e['comparisons'].items()},flush=True)
for key,path in json.load(open(r/'coverage_callees_build.json'))['overrides'].items():
 ranges,command=lean_profile.symbol_ranges(path)
 with gzip.open(r/(key+'_v6_symbols.json.gz'),'wt') as f:json.dump(dict(binary_sha256=b.sha(path),command=command,ranges=ranges),f,separators=(',',':'))
b.save(r/'screen_decision.json',dict(miss_decisions=miss['decisions'],e2e_decisions=e2e['decisions'],next='Proceed with independently trained indirect target profile. Keep V6 as a mechanistic reference only if miss eligibility holds; no E2E promotion from screening.'))
