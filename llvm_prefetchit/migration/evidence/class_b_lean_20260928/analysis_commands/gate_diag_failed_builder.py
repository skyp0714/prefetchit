from pathlib import Path
import gzip,json,os,shutil,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,lean_plan as p,lean_it0
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_lean_20260928');b.space(r)
assert (r/'screen_v4/complete.json').exists()
retention=json.loads((r/'v4_retention.json').read_text());gated=retention['gated_diagnostic']
name='one_far' if gated=='one_far_it0' else 'callees_static'
tag='lean_v4_gate_diag';policy='lean_meta_'+name+'_diag'
assert not (r/'confirmation_c4').exists(),'Build before independent timings begin'
# Source and target policies frozen before the new diagnostic build.
paths=list((repo/'llvm_prefetchit/lib').glob('*'))+[repo/'llvm_prefetchit/kernel/sched_clock/runtime.c',repo/'llvm_prefetchit/scripts/class_b/dense_build.py',repo/'llvm_prefetchit/scripts/class_b/lean_gate_stats.py']
for path in paths:
 if path.is_file():
  dest=r/'sources_gate_diag'/path.relative_to(repo);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
b.save(r/'sources_gate_diag.json',{str(path.relative_to(repo)):b.sha(path) for path in paths if path.is_file()})
kwargs={'functions_file':r/'profile_v3/functions.txt'} if name=='one_far' else {'callees_file':r/'profile_v3/functions.txt'}
b.build(r,policy,tag,r/'plugin_v4c',**kwargs)
images=[];converted={}
for key,exe in b.SERVICES.items():
 source=r/'builds'/tag/key/exe;image=p.read_image(source);images.append(image)
 dest=r/'builds'/(tag+'_it0')/key/exe;dest.parent.mkdir(parents=True)
 converted[key]=lean_it0.patch(source,dest,b.sha(source));p.read_image(dest)
with gzip.open(r/'gate_diag_metadata.json.gz','wt') as f:json.dump(images,f,separators=(',',':'))
b.save(r/'gate_diag_build.json',dict(policy=policy,original_gated=gated,tag=tag,overrides={k:v['path'] for k,v in converted.items()},audits=converted,
    interpretation='Diagnostic counter build, excluded from all clean E2E comparisons. Counts logical gate outcomes, not successful cache fills.'))
remove_generated([r/'builds'/tag/key/exe for key,exe in b.SERVICES.items()]+[r/'builds'/tag/'sched_runtime.o'],r/'gate_diag_ready_cleanup.json','Counter-enabled IT0 diagnostic is validated; intermediate T1 images/runtime object removed after metadata, patch audit, sources and hashes retained.')
print('Separate gate diagnostic built and audited; independent confirmations may start.')
