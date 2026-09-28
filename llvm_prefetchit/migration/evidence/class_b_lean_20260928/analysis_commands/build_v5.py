from pathlib import Path
import gzip,json,shutil,subprocess,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,dense_study as d,lean_plan as p,lean_it0,lean_profile
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_lean_20260928');b.space(r)
assert json.loads((r/'confirmation_sequence.json').read_text()).get('complete'),'Never build during accepted confirmation timing'
assert not Path('/sys/module/prefetchit_sched_clock').exists()
assert not subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project=codex-b-fullset-media'],text=True).strip()
tag='lean_v5_callees_ungated';policy='lean_meta_callees_static_ungated'
paths=list((repo/'llvm_prefetchit/lib').glob('*'))+[repo/'llvm_prefetchit/scripts/class_b/dense_build.py',Path(__file__)]
for path in paths:
 if path.is_file():
  relative=path.relative_to(repo) if path.is_relative_to(repo) else Path(path.name)
  dest=r/'sources_v5'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
b.save(r/'sources_v5.json',{str(path):b.sha(path) for path in paths if path.is_file()})
b.build(r,policy,tag,r/'plugin_v4c',callees_file=r/'profile_v3/functions.txt')
d.audit(r,{'callees_ungated':tag},'v5_')
allowed=set((r/'profile_v3/functions.txt').read_text().splitlines())
base=json.loads((r/'screen_v4_spec.json').read_text())['arms']['base']['overrides']
images=[];converted={};targets={}
for key,exe in b.SERVICES.items():
 source=r/'builds'/tag/key/exe;image=p.read_image(source);images.append(image)
 ranges,_=lean_profile.symbol_ranges(source);entries={}
 for item in ranges:entries.setdefault(item['start'],set()).update(item['names'])
 original,_=lean_profile.symbol_ranges(base[key]);original_names={name for row in original for name in row['names']}
 assert image['records'] and all(row['active'] and row['direct'] and row['target'] in entries and entries[row['target']]&allowed for row in image['records'])
 names={name for row in image['records'] for name in entries[row['target']] if name in allowed}
 assert names<=original_names,(key,names-original_names)
 symbols=subprocess.check_output(['nm',source],text=True)
 assert '__prefetchit_gate_' not in symbols and '__prefetchit_sched_slots' not in symbols
 dest=r/'builds'/(tag+'_it0')/key/exe;dest.parent.mkdir(parents=True)
 converted[key]=lean_it0.patch(source,dest,b.sha(source));p.read_image(dest)
 targets[key]=dict(target_names=sorted(names),all_targets_original_main_definitions=True,no_gate_or_clock_symbols=True)
assert not (r/'builds'/tag/'sched_runtime.o').exists()
with gzip.open(r/'v5_metadata.json.gz','wt') as f:json.dump(images,f,separators=(',',':'))
b.save(r/'v5_build.json',dict(policy=policy,tag=tag,overrides={k:v['path'] for k,v in converted.items()},audits=converted,targets=targets,
 interpretation='Same callee allowlist and source budget, gates/runtime disabled. Placement and code generation may change; not an exact machine-code gate-only ablation.'))
remove_generated([r/'builds'/tag/key/exe for key,exe in b.SERVICES.items()],r/'v5_ready_cleanup.json','Ungated callee IT0 and exact-layout NOP audited; unused intermediate T1 images removed after sources, metadata, patch records and hashes retained.')
v4=json.loads((r/'screen_v4_spec.json').read_text());design=json.loads((r/'v5_design.json').read_text())
arms=dict(base=v4['arms']['base'],callees_ungated_nop=dict(clock=False,controls=['base'],
 overrides={k:str(r/'builds'/tag/k/(exe+'.nop')) for k,exe in b.SERVICES.items()}),
 callees_ungated_it0=dict(clock=False,controls=['base','callees_ungated_nop'],overrides={k:v['path'] for k,v in converted.items()}))
b.save(r/'screen_v5_spec.json',dict(out=str(r/'screen_v5'),arms=arms,module=v4['module'],clock_options=v4['clock_options'],
 blocks=2,concurrency=4,roi_s=60,seedbase=60001,pmu_blocks=[0],pmu_event_sets={},
 phase='Late exploratory mechanism follow-up; not independent confirmation and not pooled with V4',design=design))
print('V5 ungated callee build, original-binding and exact-NOP/IT0 audits complete.',flush=True)
