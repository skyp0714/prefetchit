from pathlib import Path
import json,gzip,sys
sys.path.insert(0,'/home/hnpark2/prefetchit/llvm_prefetchit/scripts/class_b')
import dense_build as b
r=Path('/storage/prefetchit/class_b_coverage_20260928')
def h(s):
 n=14695981039346656037
 for c in s.encode():n=((n^c)*1099511628211)&((1<<64)-1)
 return n
profile=json.load(open(r/'indirect_profile/indirect_targets.json'))['callers'];a=json.load(gzip.open(r/'indirect_profile/aggregates.json.gz','rt'));out={}
for label,tag in [('indirect','coverage_indirect'),('lift','coverage_indirect_lift')]:
 ims=json.load(gzip.open(r/(tag+'_metadata.json.gz'),'rt'));byservice={Path(x['path']).parent.name:x for x in ims};out[label]={}
 for k,im in byservice.items():
  symbols=json.load(gzip.open(r/(k+'_'+label+'_symbols.json.gz'),'rt'))['ranges'];names={name:s['start'] for s in symbols for name in s['names']};actual={(int(x['function'],16),x['target']) for x in im['records']}
  edges=a[k]['phases']['heldout']['edges'];selected=[x for x in edges if any(x['target'] in profile.get(n,[]) for n in x['caller_names'])]
  matched=[x for x in selected if any((h(n),names.get(x['target'])) in actual for n in x['caller_names'])]
  alln=sum(x['samples'] for x in selected);matchn=sum(x['samples'] for x in matched)
  out[label][k]=dict(selected_heldout_edge_samples=alln,exact_caller_target_pair_present_samples=matchn,pct_of_selected=100*matchn/alln if alln else 0,limitations='Existence of a hint in the linked caller, not proof the runtime path executes it before the miss; hashes source function names. Structural association only.')
b.save(r/'linked_indirect_pair_coverage.json',dict(results=out,source_sha256=b.sha(__file__),profile_sha256=b.sha(r/'indirect_profile/indirect_targets.json'),aggregate_sha256=b.sha(r/'indirect_profile/aggregates.json.gz')))
