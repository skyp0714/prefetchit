from pathlib import Path
import sys,json
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from dense_causes import ev,fe
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_coverage_20260928')
assert (r/'screen_indirect/complete.json').exists()
pool=[]
for label,file,specfile in [('direct','screen_miss.json','screen_spec.json'),('indirect','indirect_screen_miss.json','screen_indirect_spec.json')]:
 data=json.load(open(r/file));spec=json.load(open(r/specfile))
 for name,result in data['decisions'].items():
  if not result['miss_screen_eligible']:continue
  setting=spec['arms'][name]
  if not all(Path(p).is_file() for p in setting['overrides'].values()):continue
  score=min(c['summary']['cost_reduction_pct'] for c in result['contrasts'].values())
  nop=next(c for c in setting['controls'] if c.endswith('_nop'))
  pool.append(dict(score=score,name=name,stage=label,setting=setting,nop=spec['arms'][nop],source=str(r/file)))
assert pool,'No code-miss-qualified candidate; retain a negative decision and choose another justified experiment instead of silently changing selection.'
selected=max(pool,key=lambda x:(x['score'],x['name']))
old=json.load(open(r/'screen_spec.json'))
arms=dict(base=old['arms']['base'],selected_nop=dict(selected['nop'],controls=['base']),selected_it0=dict(selected['setting'],controls=['base','selected_nop']))
spec=dict(out=str(r/'confirmation'),arms=arms,module=old['module'],clock_options={},blocks=6,concurrency=4,roi_s=60,seedbase=64001,pmu_blocks=list(range(6)),pmu_event_sets={'frontend':','.join(['cycles:u','instructions:u',fe('FE_L1',0x12),ev('ICACHE_DATA_STALL',0x80,4),ev('ICACHE_TAG_STALL',0x83,4),ev('BACLEARS',0x60,1),ev('ITLB_WALK_ACTIVE',0x11,0x10,',cmask=1')])},phase='Independent confirmation: six NEW seeds, never pooled with exploration',primary_miss='Both base and exact-layout NOP comparisons must have lower95% bound >0 for summed FE_L2/request. Service breakdown and speculative L2I remain separate.',e2e='CPU and mean lower95% bound >0 versus both controls; p99 lower95% bound >-2%. No E2E promotion from code-miss evidence alone.')
b.save(r/'confirmation_spec.json',spec)
b.save(r/'confirmation_selection.json',dict(selected=selected,candidates=pool,selection='Highest minimum paired-log code-miss reduction vs original and own NOP among available qualified exploratory references. Stages are not pooled; independent new seeds are the confirmation.'))
kept=set(arms['selected_nop']['overrides'].values())|set(arms['selected_it0']['overrides'].values())
obsolete=[]
for tag in ('coverage_callees','coverage_indirect','coverage_indirect_lift'):
 build=json.load(open(r/(tag+'_build.json')))
 for key,exe in b.SERVICES.items():
  for path in (Path(build['overrides'][key]),r/'builds'/tag/key/(exe+'.nop')):
   if path.exists() and str(path) not in kept:obsolete.append(path)
if obsolete:remove_generated(obsolete,r/'screen_superseded_cleanup.json','Exploratory references superseded by selected independent-confirmation candidate. All per-run PMU/E2E outcomes, source snapshots, symbol ranges, linked metadata, opcode patches and hashes retained before deletion.')
print(json.dumps(dict(selected=selected['name'],score=selected['score'],blocks=6,seeds=[64001,64006])),flush=True)
