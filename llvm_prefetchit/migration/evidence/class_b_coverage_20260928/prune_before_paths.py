from pathlib import Path
import sys,json
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from dense_causes import ev,fe
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_coverage_20260928')
assert (r/'screen_indirect/complete.json').exists()
pool=[];per_service={k:[] for k in b.SERVICES}
for label,file,specfile in [('direct','screen_miss.json','screen_spec.json'),('indirect','indirect_screen_miss.json','screen_indirect_spec.json')]:
 data=json.load(open(r/file));settings=json.load(open(r/specfile))
 for name,result in data['decisions'].items():
  arm=settings['arms'][name]
  nop=next(c for c in arm['controls'] if c.endswith('_nop'))
  if result['miss_screen_eligible']:
   score=min(c['summary']['cost_reduction_pct'] for c in result['contrasts'].values())
   pool.append(dict(score=score,name=name,stage=label,setting=arm,nop=settings['arms'][nop],source=str(r/file)))
  for service in b.SERVICES:
   metric=service+':FE_L2';effects=[]
   for control in ('base',nop):
    for block in range(settings['blocks']):
     pair={x['arm']:x['metrics'][metric] for x in data['rows'] if x['block']==block and x['arm'] in (name,control)}
     assert len(pair)==2
     effects.append(100*(1-pair[name]/pair[control]))
   if all(x>0 for x in effects):
    score=min(data['comparisons'][name][control][metric]['cost_reduction_pct'] for control in ('base',nop))
    per_service[service].append(dict(score=score,name=name,stage=label,all_paired_reductions_pct=effects,binary=arm['overrides'][service],nop=settings['arms'][nop]['overrides'][service],source=str(r/file)))
assert pool,'No globally qualified reference; stop and retain all outcomes before choosing another experiment.'
selected=max(pool,key=lambda x:(x['score'],x['name']))
old=json.load(open(r/'screen_spec.json'));base=old['arms']['base']
chosen={k:max(values,key=lambda x:(x['score'],x['name'])) if values else dict(name='base',score=0,binary=base['overrides'][k],nop=base['overrides'][k],source='No candidate reduced service FE_L2 in both blocks against both controls') for k,values in per_service.items()}
# Retention decisions must not silently exclude a previously measured arm.
# Reconstruct a winning thinned ELF from retained full IT0 and verify its exact
# earlier hash; never time a different reconstruction under the old label.
for key,choice in chosen.items():
 if not Path(choice['binary']).is_file():
  assert choice['name']=='coverage_weighted_it0'
  import coverage_plan
  original=json.load(open(r/'coverage_weighted1_build.json'))[key]
  source=Path(json.load(open(r/'coverage_callees_build.json'))['overrides'][key])
  dest=r/'builds/coverage_weighted1_regenerated_it0'/key/b.SERVICES[key];dest.parent.mkdir(parents=True)
  result=coverage_plan.thin(source,dest,r/'profile.json',1)
  assert result['sha256']==original['sha256'],'Reconstruction must be byte-identical'
  choice['binary']=str(dest);choice['reconstructed_sha256']=result['sha256']
arms=dict(base=base,selected_nop=dict(clock=False,controls=['base'],overrides={k:v['nop'] for k,v in chosen.items()}),selected_it0=dict(clock=False,controls=['base','selected_nop'],overrides={k:v['binary'] for k,v in chosen.items()}))
spec=dict(out=str(r/'confirmation'),arms=arms,module=old['module'],clock_options={},blocks=6,concurrency=4,roi_s=60,seedbase=64001,pmu_blocks=list(range(6)),pmu_event_sets={'frontend':','.join(['cycles:u','instructions:u',fe('FE_L1',0x12),ev('ICACHE_DATA_STALL',0x80,4),ev('ICACHE_TAG_STALL',0x83,4),ev('BACLEARS',0x60,1),ev('ITLB_WALK_ACTIVE',0x11,0x10,',cmask=1')])},phase='Independent confirmation: six NEW seeds, never pooled with exploration',primary_miss='Both base and exact-layout NOP comparisons must have lower95% bound >0 for summed FE_L2/request. Service breakdown and speculative L2I remain separate.',e2e='CPU and mean lower95% bound >0 versus both controls; p99 lower95% bound >-2%. No E2E promotion from code-miss evidence alone.')
b.save(r/'provisional_service_selection.json',dict(selected=chosen,candidates=per_service,best_uniform_reference=selected,uniform_candidates=pool,selection='Per-service highest minimum paired-log FE_L2 reduction vs original and own NOP, requiring both blocks positive for that service. Unqualified services keep original. Mixed bundle has not previously been timed: fresh independent whole-stack confirmation tests interactions. Exploratory stages are not pooled.'))
kept=set(arms['selected_nop']['overrides'].values())|set(arms['selected_it0']['overrides'].values())
obsolete=[]
for tag in ('coverage_callees','coverage_indirect','coverage_indirect_lift'):
 build=json.load(open(r/(tag+'_build.json')))
 for key,exe in b.SERVICES.items():
  for path in (Path(build['overrides'][key]),r/'builds'/tag/key/(exe+'.nop')):
   if path.exists() and str(path) not in kept:obsolete.append(path)
if obsolete:remove_generated(obsolete,r/'before_paths_superseded_cleanup.json','Exploratory references superseded by selected independent-confirmation candidate. All per-run PMU/E2E outcomes, source snapshots, symbol ranges, linked metadata, opcode patches and hashes retained before deletion.')
print(json.dumps(dict(selected={k:v['name'] for k,v in chosen.items()},scores={k:v['score'] for k,v in chosen.items()},blocks=6,seeds=[64001,64006])),flush=True)
