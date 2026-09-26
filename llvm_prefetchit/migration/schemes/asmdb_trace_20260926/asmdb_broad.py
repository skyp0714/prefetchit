"""Predeclared coverage expansion after initial512-site screen; independent confirmation."""
from pathlib import Path
import json,os,subprocess
from asmdb_execute import B,R,S,BASE,REPO,save,command,rewrite,compare,cleanup
from asmdb_plan import make
def main():
 os.chdir(REPO);os.sched_setaffinity(0,{84,85})
 first=json.loads((R/'screen/paired_summary.json').read_text())
 # Choose window by end-to-end baseline metric, not by miss-count reduction.
 selected=max(first['results'],key=lambda r:r['comparisons']['base']['speedup_pct'])['arm']
 w=next(w for w in json.loads((R/'calibration.json').read_text())['windows'] if w['name']==selected)
 save(R/'broad_protocol.json',dict(window_selection=selected,rule='best initial512site screen mean vsbaseline; no old observations pooled',max_sites=[2048,4096],additional_control='trace-selected in-place NOP-only policy to isolate detour overhead, max4096sites',other_thresholds='same min32hits/P>=.8/max4paths/target/dynamicaddedinstructionbudget1.5%',screen='three fresh paired seed1 repetitions',confirmation='best mean>=.5%vsbase and positivevsNOP gets seven new paired seed3 repetitions; if no such candidate, retain negative screen only'))
 # Reconstruct original instruction index after its first use was compacted.
 # Source/PEBS windows identical; no new training or timing data influences targets.
 command(['python3',str(B/'asmdb_prepare.py')],'broad_reindex.log')
 arms={'base':BASE,'static':S/'fleet_filters/static_all'};paths=[]
 for name,cap,kind in [('broad2048',2048,None),('broad4096',4096,None),('inline',4096,'nop')]:
  plan=make(selected,w['low'],w['high'],max_sites=cap,output_name=name,kind_filter=kind)
  if not plan['sites']:save(R/(name+'_excluded.json'),dict(reason='no sites under predeclared thresholds'));continue
  out=R/name;rewrite(BASE,out,plan)
  for binary in [out,Path(str(out)+'.nop')]:
   for seed in [1,3]:
    cmd=['taskset','-c','32',str(binary),'--benchmark_filter=^BM_PROTO_Arena$','--benchmark_min_time=1x',f'--seed={seed}','--benchmark_format=json'];command(cmd,binary.name+f'_smoke{seed}.json',timeout=60)
    result=json.loads((R/(binary.name+f'_smoke{seed}.json')).read_text());assert len(result['benchmarks'])==1 and not result['benchmarks'][0].get('error_occurred')
  arms[name]=out;arms[name+'_nop']=Path(str(out)+'.nop');paths.extend([out,Path(str(out)+'.nop')])
  print(json.dumps(dict(name=name,sites=len(plan['sites']),hints=sum(len(s['targets']) for s in plan['sites']),added_instruction_pct=plan['estimated_added_dynamic_instructions_pct'],estimated_coverage_pct=plan['estimated_weighted_target_coverage_pct'])),flush=True)
 cleanup([R/'instructions.json'],'candidate bytes retained in complete selected plans; remove regenerated full index before timing','broad_index_cleanup.json')
 screen=compare(R/'broad_screen',arms,3,1)
 good=[r for r in screen['results'] if r['comparisons']['base']['speedup_pct']>=.5 and r['comparisons'][r['arm']+'_nop']['speedup_pct']>0]
 best=max(good,key=lambda r:r['comparisons']['base']['speedup_pct'])['arm'] if good else None
 cleanup([p for p in paths if best is None or p.name not in [best,best+'.nop']],'coverage expansion failed/superseded screen; patch and measurements retained','broad_screen_cleanup.json')
 confirmation=None;keep=False
 if best:
  confirmation=compare(R/'broad_confirmation',{k:v for k,v in arms.items() if k in ['base','static',best,best+'_nop']},7,3)
  row=confirmation['results'][0];keep=all(row['comparisons'][ref]['ci95_pct'][0]>0 for ref in ['base',best+'_nop'])
  if not keep:cleanup([arms[best],arms[best+'_nop']],'no independent positive confirmation vsbothcontrols','broad_confirmation_cleanup.json')
 save(R/'broad_completed.json',dict(screen=screen,selected=best,confirmation=confirmation,retained=keep))
if __name__=='__main__':main()
