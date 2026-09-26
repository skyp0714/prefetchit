"""Trace-derived wake-stream plans, paired controls, independent confirmation."""
from common import *
from build import build,EXES
from audit_qualification import audit
import math,statistics,tarfile
from scipy.stats import t

def summarize(rows,key):
 arms=sorted({r['arm'] for r in rows});blocks=sorted({r['block'] for r in rows});out=[]
 for arm in [a for a in arms if a!='base' and not a.endswith('_nop')]:
  comparisons={}
  for control in ['base',arm+'_nop']:
   logs=[]
   for block in blocks:
    pair={r['arm']:r for r in rows if r['block']==block}
    if arm not in pair or control not in pair:continue
    if not pair[arm]['valid'] or not pair[control]['valid']:continue
    logs.append(math.log(pair[control]['cpu_us_per_request']/pair[arm]['cpu_us_per_request']))
   if len(logs)<2:comparisons[control]=dict(pairs=len(logs),status='insufficient valid pairs');continue
   mean=statistics.mean(logs);half=float(t.ppf(.975,len(logs)-1))*statistics.stdev(logs)/math.sqrt(len(logs))
   comparisons[control]=dict(pairs=len(logs),cpu_cost_reduction_pct=100*(1-math.exp(-mean)),ci95_pct=[100*(1-math.exp(-(mean-half))),100*(1-math.exp(-(mean+half)))])
  out.append(dict(arm=arm,comparisons=comparisons))
 return out

def compact_trial(root):
 # Each run's measured PMU/CPU/settings/validation is retained; verbose service logs
 # and timestamp copies have served their purpose once exact ROI counts are saved.
 gone=[]
 for p in root.rglob('*'):
  if p.is_file() and not p.is_symlink() and (p.name=='requests.json.gz' or p.name in ['up.log','backends_up.log','jaeger_up.log','init_movies.log','down.log']):
   gone.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)));p.unlink()
 save(root/'cleanup.json',dict(removed=gone,bytes_removed=sum(x['bytes'] for x in gone)))

def evaluate(key,arms,rate,group,blocks,seedbase,family='media'):
 out=S/(family+'_evaluation')/key/group;out.mkdir(parents=True,exist_ok=False);rows=[];names=list(arms)
 save(out/'protocol.json',dict(arms={k:str(v) for k,v in arms.items()},hashes={k:sha(v) for k,v in arms.items()},blocks=blocks,rate=rate,seedbase=seedbase,order=f'cyclic rotation, reversed every full cycle; {blocks} blocks / {len(names)} arms; complete cycles position-balanced',primary='target cgroup user+kernel CPU / exact completed external request; PMU collected separately when enabled',analysis='paired log CPU-cost reduction; exploration and confirmation not pooled; all outcomes retained, invalid pairs excluded only by predeclared operating gates'))
 for block in range(blocks):
  order=names[block%len(names):]+names[:block%len(names)]
  if (block//len(names))%2:order=list(reversed(order))
  for arm in order:
   d=out/f'{block:02d}_{arm}';tag=f'b_{key}_{group}_{block}_{arm}'
   platform(tag,['python3',B/(family+'.py'),'--out',d,'--service',key,'--binary',arms[arm],'--rate',str(rate),'--seed',str(seedbase+block)])
   result=json.loads((d/'summary.json').read_text())[0];r=result['services'][key]
   row=dict(block=block,arm=arm,valid=r['valid'],cpu_us_per_request=r['primary']['cpu_us_per_request'],user_us_per_request=r['primary']['user_us_per_request'],user_cycles_per_request=r['user_cycles_per_request'],mpki=r['post_pmu']['mpki'],code_misses_per_request=r['code_misses_per_request'],output=str(d),pool_util_pct=result['pool_util_pct'],whole_stack_cpu_us_per_request=result['all_cpu_us']/r['primary']['completed'],p99_ms=r['primary']['p99_ms'],warmup_errors=result['load'].get('warmup_errors',0),steady_errors=result['load'].get('steady_errors',result['load']['errors']))
   rows.append(row);save(out/'rows.json',rows);save(out/'paired_summary.json',summarize(rows,key));compact_trial(d)
   print(json.dumps(dict(key=key,group=group,**row)),flush=True)
 return summarize(rows,key)

def run_family(family):
 if (S/(family+'_completed.json')).exists():return
 os.chdir(REPO);audit(family);qual=S/('media_qualification_v2' if family=='media' else family+'_qualification');selected=json.loads((qual/'audited_selected.json').read_text());eligible={k:v for k,v in selected.items() if 'rate' in v}
 if eligible and not (S/(family+'_trace_stack')/'completed.json').exists():platform(family+'_trace_v5',['python3',B/('trace_'+family+'.py')])
 ws=REPO/'flat_codegen/dsb_build/media/ws';saved_results=S/(family+'_results.json');all_results=json.loads(saved_results.read_text()) if saved_results.exists() else {}
 for key,selection in eligible.items():
  if key in all_results:continue
  root=S/(family+'_build')/key;trace=T/key;exe=EXES[key];arms={'base':root/'base'/exe}
  leads=json.loads(os.environ.get('CLASS_B_LEADS_BY_SERVICE','{}')).get(key,list(map(int,os.environ.get('CLASS_B_LEADS','8,16').split(','))))
  for lead in leads:
   name='wake'+str(lead);plan=root/(name+'.plan.json')
   cmd=['python3',ws/'ws_plan_pass.py',trace/'runs',trace,plan,'--symfs',trace/'symfs','--exe','/custom/'+exe,'--instrumentable',root/'base/instrumentable.txt','--d',str(lead),'--dmax',str(lead*3),'--k','8','--kmerge','16','--gap-k','16','--post-call','12','--p-min','.5','--site-p','.8','--max-calls','1.5']
   run(cmd,root/(name+'.plan.log'));p=json.loads(plan.read_text());assert p['sites'],'empty plan must not be treated as a prefetch experiment'
   binary=build(key,name,plan);arms[name]=binary;arms[name+'_nop']=Path(str(binary)+'.nop')
  # Heavy decoded copies are discarded before any primary timing; exact plans,
  # symbol snapshots and run summaries suffice to interpret the experiment.
  removed=[]
  for name in ['branches.txt','pt.data']:
   p=trace/name
   if p.exists():removed.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)));p.unlink()
  save(trace/'decode_cleanup.json',dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed)))
  screen=evaluate(key,arms,selection['rate'],'screen',3,223,family);all_results[key]=dict(selection=selection,screen=screen)
  good=[]
  for r in screen:
   comps=r['comparisons']
   if all(v.get('pairs')==3 and v.get('cpu_cost_reduction_pct',-999)>=1 for v in comps.values()):good.append(r)
  keep=None
  if good:
   keep=max(good,key=lambda r:r['comparisons']['base']['cpu_cost_reduction_pct'])['arm']
  # Failed/superseded variants are deleted immediately, keeping selected controls.
  removed=[]
  for name,p in arms.items():
   if name=='base' or name in [keep,str(keep)+'_nop']:continue
   removed.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p),reason='No independent-confirmation promotion; measurements/plan/source retained'));p.unlink()
  save(root/'screen_cleanup.json',dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed)))
  if keep:
   confirmed=evaluate(key,{n:arms[n] for n in ['base',keep,keep+'_nop']},selection['rate'],'confirmation',7,1023,family)
   all_results[key]['confirmation']=confirmed
   positive=bool(confirmed) and all(c.get('pairs')==7 and c.get('ci95_pct',[-999])[0]>0 and c.get('cpu_cost_reduction_pct',-999)>=1 for c in confirmed[0]['comparisons'].values())
   all_results[key]['confirmed_gain']=positive
   if not positive:
    removed=[]
    for name in [keep,keep+'_nop']:
     p=arms[name];removed.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p),reason='Independent confirmation did not establish >=1% mean and positive CI against both controls'));p.unlink()
    save(root/'confirmation_cleanup.json',dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed)))
  save(S/(family+'_results.json'),all_results)
  run(['python3',B/'report.py'],S/'report.log')
 # A second application family is separately staged, not counted as already run.
 save(S/(family+'_completed.json'),dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),eligible=list(eligible),results=all_results))
def main():
 run_family('media')
 while not (B/'SOCIAL_READY').exists():time.sleep(5)
 run(['python3',B/'social_campaign.py','--qualify-only'],S/'social_qualification_campaign.log',timeout=14400)
 run_family('social')

if __name__=='__main__':main()
