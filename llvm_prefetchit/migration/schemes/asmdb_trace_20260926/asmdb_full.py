"""Use the complete existing capture to test rare-path coverage, with new evaluation runs."""
from pathlib import Path
import json,os,shutil
os.environ['ASMDB_RESULT_DIR']='/storage/prefetchit/class_a_expansion_20260925/asmdb_trace_full'
os.environ['ASMDB_MIN_LINE_SAMPLES']='1'
from asmdb_execute import B,R,S,BASE,REPO,save,command,rewrite,compare,cleanup,decode,coverage
from asmdb_plan import make
OLD=S/'asmdb_trace'
def main():
 os.chdir(REPO);os.sched_setaffinity(0,{84,85});R.mkdir();assert shutil.disk_usage(R).free>40*2**30
 initial=json.loads((OLD/'screen/paired_summary.json').read_text());choice=max(initial['results'],key=lambda r:r['comparisons']['base']['speedup_pct'])['arm'];cal=json.loads((OLD/'calibration.json').read_text());w=next(x for x in cal['windows'] if x['name']==choice)
 save(R/'protocol.json',dict(training='entire pre-existing baselinePT between first andlastPEBS timestamp; includes singleton PEBS targetlines, min8observedpairhits',window=w,probability_thresholds=[.8,.5],site_cap=4096,dynamic_instruction_cap_pct=1.5,scope='coverage sensitivity experiment motivated by sparse short-window candidate histories, not exact AsmDB hardware reproduction',screen='three fresh seed1 paired repetitions; all attempted policies reported',confirmation='best mean>=.5%vsbase and >0vsNOP gets seven fresh paired seed4 repetitions; no old measurements pooled',input='same original benchmark and seed0 training binary; no workload inflation'))
 command(['python3',str(B/'asmdb_prepare.py')],'prepare.log')
 heat=json.loads((R/'pebs_heat.json').read_text());save(R/'windows.json',dict(windows=[[heat['time_first'],heat['time_last']]],selection='entire originalcapturebetweenfirstandlastPEBS',decode='every instruction i1i with control-flow continuity audit'))
 save(R/'calibration.json',dict(**cal,reused_from=str(OLD/'calibration.json')))
 seq=decode();command([str(R/'stream'),'pairs',str(R/'mapping.tsv'),str(seq),str(R/'targets.txt'),str(w['low']),str(w['high']),str(R/'full_pairs.tsv')],'planner.log')
 arms={'base':BASE,'static':S/'fleet_filters/static_all'};paths=[]
 for name,prob in [('strict',.8),('relaxed',.5)]:
  plan=make('full',w['low'],w['high'],max_sites=4096,output_name=name,min_hits=8,min_probability=prob);assert plan['sites'];save(R/(name+'_joint_coverage.json'),coverage(plan,seq));out=R/name;rewrite(BASE,out,plan)
  for binary in [out,Path(str(out)+'.nop')]:
   for seed in [1,4]:
    command(['taskset','-c','32',str(binary),'--benchmark_filter=^BM_PROTO_Arena$','--benchmark_min_time=1x',f'--seed={seed}','--benchmark_format=json'],binary.name+f'_smoke{seed}.json',timeout=60)
    x=json.loads((R/(binary.name+f'_smoke{seed}.json')).read_text());assert len(x['benchmarks'])==1 and not x['benchmarks'][0].get('error_occurred')
  arms[name]=out;arms[name+'_nop']=Path(str(out)+'.nop');paths.extend([out,Path(str(out)+'.nop')]);print(json.dumps(dict(name=name,sites=len(plan['sites']),hints=sum(len(s['targets']) for s in plan['sites']),added_instruction_pct=plan['estimated_added_dynamic_instructions_pct'],estimated_coverage_pct=plan['estimated_weighted_target_coverage_pct'])),flush=True)
 cleanup([seq,R/'instructions.json',R/'mapping.tsv',R/'stream'],'complete trace analyzed; originalPT and selected exact plans retained','pre_timing_cleanup.json')
 screen=compare(R/'screen',arms,3,1);good=[r for r in screen['results'] if r['comparisons']['base']['speedup_pct']>=.5 and r['comparisons'][r['arm']+'_nop']['speedup_pct']>0];best=max(good,key=lambda r:r['comparisons']['base']['speedup_pct'])['arm'] if good else None
 cleanup([p for p in paths if best is None or p.name not in [best,best+'.nop']],'failed/superseded whole-trace screen; exact patch and evidence retained','screen_cleanup.json')
 confirmation=None;keep=False
 if best:
  confirmation=compare(R/'confirmation',{k:v for k,v in arms.items() if k in ['base','static',best,best+'_nop']},7,4);row=confirmation['results'][0];keep=all(row['comparisons'][ref]['ci95_pct'][0]>0 for ref in ['base',best+'_nop'])
  if not keep:cleanup([arms[best],arms[best+'_nop']],'independent confirmation failed','confirmation_cleanup.json')
 cleanup([R/'full_pairs.tsv',*R.glob('history_test*.bin'),R/'history_test_mapping.tsv',R/'history_test_targets.txt'],'analysis completed; compact plan, results and originalPT retained','final_analysis_cleanup.json')
 save(R/'completed.json',dict(screen=screen,selected=best,confirmation=confirmation,retained=keep));print(json.dumps(dict(stage='completed',best=best,retained=keep)),flush=True)
if __name__=='__main__':main()
