"""AsmDB-inspired finite instruction-window placement with empirical execution probabilities.

PEBS line heat weights target importance. Histories are actual decoded instruction
sequences. P(target entry in window | trigger execution) limits fan-out/repeated
loop issuance. A marginal-coverage / issue-cost heuristic limits fan-in. This is
an adaptation for T1/L2, not reproduction of the paper's simulated L1I instruction.
"""
from pathlib import Path
import collections,csv,json,math,os,statistics
R=Path(os.environ.get('ASMDB_RESULT_DIR','/storage/prefetchit/class_a_expansion_20260925/asmdb_trace'))
def save(p,x):p.write_text(json.dumps(x,indent=2))
def make(name,low,high,max_sites=512,output_name=None,kind_filter=None,min_hits=32,min_probability=.8):
 ins=json.loads((R/'instructions.json').read_text());byid={r['id']:r for r in ins};heat={int(k):v for k,v in json.loads((R/'pebs_heat.json').read_text())['lines'].items()}
 f=(R/(name+'_pairs.tsv')).open();header=f.readline().split();total=int(header[2]);candidates=[]
 for row in csv.DictReader(f,delimiter='\t'):
  r={k:int(v) for k,v in row.items()};s=byid[r['site_id']];target=r['target_line'];prob=r['hits']/r['triggers']
  if kind_filter and s['kind']!=kind_filter:continue
  if r['hits']<min_hits or prob<min_probability or r['hits']/r['target_visits']<.02 or target==(s['va']&~63):continue
  if not heat.get(target):continue
  r.update(probability=prob,heat=heat[target],cost_per_fire=0 if s['kind']=='nop' else 3,kind=s['kind'])
  # Prefer economical histories, with a positive decode cost for NOP replacement
  # because even a replaced instruction must issue a memory request.
  r['score']=heat[target]*(r['hits']/r['target_visits'])/(r['triggers']*(1 if s['kind']=='nop' else 3))
  candidates.append(r)
 candidates.sort(key=lambda r:(-r['score'],-r['hits'],r['site_id'],r['target_line']))
 sites={};target_paths=collections.Counter();covered_est=collections.Counter();estimated_added=0;selected=[]
 for r in candidates:
  sid=r['site_id'];target=r['target_line'];s=byid[sid];limit=1 if s['kind']=='nop' else 4
  if len(sites.get(sid,[]))>=limit or target in sites.get(sid,[]):continue
  if target_paths[target]>=4 or covered_est[target]>=.90:continue
  if sid not in sites and len(sites)>=max_sites:continue
  extra=0 if s['kind']=='nop' else (1 if sid in sites else 3)
  if estimated_added+extra*r['triggers']>total*.015:continue
  sites.setdefault(sid,[]).append(target);estimated_added+=extra*r['triggers'];target_paths[target]+=1;covered_est[target]+=r['hits']/r['target_visits'];selected.append(r)
 result=[dict(byid[s],targets=t) for s,t in sorted(sites.items())]
 output_name=output_name or name
 plan=dict(name=output_name,low=low,high=high,sites=result,selection=selected,training_instructions=total,estimated_added_dynamic_instructions_pct=100*estimated_added/total,estimated_weighted_target_coverage_pct=100*sum(heat[t]*min(1,c) for t,c in covered_est.items())/sum(heat.values()),scope=__doc__,limitations='coverage sum can overlap across sites; joint audit if supplied is separate. Target entry probability is not conditional miss probability. Main ELF only; histories reset on unknown/DSO boundary. Max4 paths/target,4 targets/detour,1 target/NOP; dynamic added-instruction budget1.5%; async unwind unsupported within detour stub.',max_sites=max_sites,candidate_pairs=len(candidates))
 plan['kind_filter']=kind_filter
 plan['min_hits']=min_hits;plan['min_probability']=min_probability
 save(R/(output_name+'_plan.json'),plan);return plan
def coverage(plan,sequence):
 import array
 ins=json.loads((R/'instructions.json').read_text());lines=[0]+[r['va']&~63 for r in ins];targets={t for r in plan['sites'] for t in r['targets']};selected={r['id']:r['targets'] for r in plan['sites']};heat={int(k):v for k,v in json.loads((R/'pebs_heat.json').read_text())['lines'].items()}
 # Audit a bounded deterministic prefix to avoid a second full Python trace walk.
 # Full pair frequencies are C++; this audit explicitly reports its smaller scope.
 seq=array.array('I');
 with sequence.open('rb') as f:seq.frombytes(f.read(4*2000000))
 pending=collections.deque();latest={};visits=collections.Counter();covered=collections.Counter();last=0
 low,high=plan['low'],plan['high']
 for i,sid in enumerate(seq):
  if sid==0:pending.clear();latest.clear();last=0;continue
  while pending and pending[0][0]<=i:
   at,ts=pending.popleft()
   for t in ts:latest[t]=at-low
  line=lines[sid]
  if line!=last and line in targets:
   visits[line]+=1
   if line in latest and i-latest[line]<=high:covered[line]+=1
  if sid in selected:pending.append((i+low,selected[sid]))
  last=line
 return dict(scope='joint dynamic target-entry coverage, first2M decoded records only; not actual miss-instance coverage',records=len(seq),weighted_coverage_of_observed_selected_targets=100*sum(heat[t]*covered[t]/v for t,v in visits.items())/sum(heat[t] for t in visits) if visits else 0,distinct_observed_targets=len(visits),visits=sum(visits.values()),covered=sum(covered.values()))
