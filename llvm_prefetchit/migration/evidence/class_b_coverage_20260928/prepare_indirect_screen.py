from pathlib import Path
import sys,json,gzip
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,lean_profile,lean_plan
r=Path('/storage/prefetchit/class_b_coverage_20260928')
spec=json.load(open(r/'screen_spec.json'));arms={'base':spec['arms']['base']};training=json.load(gzip.open(r/'indirect_profile/aggregates.json.gz','rt'));static={}
for label,tag in [('indirect','coverage_indirect'),('lift','coverage_indirect_lift')]:
 v=json.load(open(r/(tag+'_build.json')))
 arms[label+'_nop']=dict(clock=False,controls=['base'],overrides={k:str(r/'builds'/tag/k/(exe+'.nop')) for k,exe in b.SERVICES.items()})
 arms[label+'_it0']=dict(clock=False,controls=['base',label+'_nop'],overrides=v['overrides'])
 static[label]={}
 for k,x in v['targets'].items():
  baseline=Path(arms['base']['overrides'][k]);basebytes=sum(s['size'] for s in lean_plan.sections(baseline.read_bytes()) if s['flags']&4 and s['type']==1)
  names=set(x['target_names']);ranges=training[k]['symbol_ranges'];lines={s['start']//64 for s in ranges if names.intersection(s['names'])};rows=training[k]['phases']['heldout']['main_ips'];n=sum(z['samples'] for z in rows);covered=sum(z['samples'] for z in rows if int(z['va'],16)//64 in lines)
  static[label][k]=dict(hints=x['static_hints'],target_names=len(names),executable_bytes=x['executable_bytes'],growth_pct=100*(x['executable_bytes']/basebytes-1),heldout_main_entry_line_coverage_pct=100*covered/n)
  linked,command=lean_profile.symbol_ranges(v['overrides'][k])
  with gzip.open(r/(k+'_'+label+'_symbols.json.gz'),'wt') as f:json.dump(dict(binary_sha256=b.sha(v['overrides'][k]),command=command,ranges=linked),f,separators=(',',':'))
b.save(r/'indirect_static.json',static)
b.save(r/'screen_indirect_spec.json',dict(out=str(r/'screen_indirect'),arms=arms,module=spec['module'],clock_options={},blocks=2,concurrency=4,roi_s=60,seedbase=63001,pmu_blocks=[0,1],pmu_event_sets={},phase='Frozen trained-indirect versus one-call-edge lift exploration; fresh seeds, both own NOP controls',primary_miss='sum of all3 FE_L2/request; reduction in both blocks against base and own NOP; strongest minimum paired-log point reduction retained for independent confirmation; no E2E promotion from this screen'))
print(json.dumps(static,indent=2))
