from pathlib import Path
import json
r=Path('/storage/prefetchit/class_b_lean_20260928')
result=[]
for phase in ('screen_v4','confirmation_c4','confirmation_c16','screen_v5'):
 p=r/phase/'compact_pmu.json'
 if not p.exists():continue
 records=json.loads(p.read_text());by={v['arm']:v for v in records}
 protocol=json.loads((r/phase/'protocol.json').read_text())
 for arm,record in by.items():
  for service,values in record['services'].items():
   x=values['per_request'];extra=record.get('extra',{}).get('late',{}).get(service,{}).get('per_request',{})
   comparisons={}
   for control in protocol['arms'][arm].get('controls',[]):
    if control not in by:continue
    y=by[control]['services'][service]['per_request']
    comparisons[control]={k:100*(1-x[k]/y[k]) for k in ('cycles:u','instructions:u','L2I','FE_L2','ITLB_WALK') if y[k]}
   result.append(dict(phase=phase,arm=arm,service=service,block=record['block'],
    per_request=x,extra_per_request=extra,L2I_mpki=1000*x['L2I']/x['instructions:u'],
    itlb_walk_active_pct_user_cycles=100*extra['ITLB_WALK_ACTIVE']/extra['cycles:u'] if extra else None,
    cost_reduction_pct=comparisons))
(r/'final_pmu_comparison.json').write_text(json.dumps(dict(rows=result,
 interpretation='Separate post-ROI PMU windows, one block per phase. Ratios are descriptive, no uncertainty estimate or causal promotion. Bracketing request denominator includes recorder setup/teardown. L2I and FE_L2 count different event populations; FE_LATE_SWPF is not all prefetch issues.'),indent=2)+'\n')
print('Wrote',len(result),'service/arm PMU rows')
