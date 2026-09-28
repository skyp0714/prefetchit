from pathlib import Path
import sys,json,shutil,gzip
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,dense_study as d,lean_plan as p,lean_it0,lean_profile
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_coverage_20260928');old=Path('/storage/prefetchit/class_b_lean_20260928')
tag='coverage_paths';b.space(r)
assert (r/'indirect_profile/summary.json').exists()
summary=json.load(open(r/'indirect_profile/summary.json'))
names=set((r/'functions.txt').read_text().splitlines())|set(summary['target_names'])
(r/'indirect_functions.txt').write_text('\n'.join(sorted(names))+'\n')
b.build(r,tag,tag,r/'plugin_paths',callees_file=r/'indirect_functions.txt',indirect_file=r/'indirect_profile/indirect_targets.json')
d.audit(r,{tag:tag},tag+'_')
base=json.load(open(r/'protocol.json'))['baseline']['overrides'];allowed=set((r/'indirect_functions.txt').read_text().splitlines())
images=[];converted={};targets={}
for key,exe in b.SERVICES.items():
 source=r/'builds'/tag/key/exe;image=p.read_image(source);images.append(image)
 ranges,_=lean_profile.symbol_ranges(source);entries={}
 for x in ranges:entries.setdefault(x['start'],set()).update(x['names'])
 original,_=lean_profile.symbol_ranges(base[key]);original_names={n for x in original for n in x['names']}
 assert image['records'] and all(x['active'] and x['direct'] and x['target'] in entries and entries[x['target']]&allowed for x in image['records'])
 names={n for x in image['records'] for n in entries[x['target']] if n in allowed}
 assert names<=original_names,(key,names-original_names)
 dest=r/'builds'/(tag+'_it0')/key/exe;dest.parent.mkdir(parents=True)
 converted[key]=lean_it0.patch(source,dest,b.sha(source));p.read_image(dest)
 targets[key]=dict(target_names=sorted(names),all_targets_original_main_definitions=True,static_hints=len(image['records']),executable_bytes=image['executable_bytes'])
with gzip.open(r/(tag+'_metadata.json.gz'),'wt') as f:json.dump(images,f,separators=(',',':'))
b.save(r/(tag+'_build.json'),dict(policy=tag,overrides={k:v['path'] for k,v in converted.items()},audits=converted,targets=targets))
remove_generated([r/'builds'/tag/key/exe for key,exe in b.SERVICES.items()],r/(tag+'_ready_cleanup.json'),'IT0/NOP audited; intermediate T1 images superseded, compact records retained')
print(json.dumps({k:dict(targets=len(v['target_names']),hints=v['static_hints'],executable_bytes=v['executable_bytes']) for k,v in targets.items()}),flush=True)
