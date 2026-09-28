"""Post-diagnostic attribution from retained IP aggregates; no trace or ELF reads."""
from collections import Counter
from pathlib import Path
import gzip,json,subprocess
r=Path('/storage/prefetchit/class_b_lean_20260928')
root=r/'diagnostics_late'
def read(p):return json.loads(p.read_text())
def gz(p):
 with gzip.open(p,'rt') as f:return json.load(f)
assert read(root/'complete.json')
v5=read(r/'v5_build.json') if (r/'v5_build.json').exists() and read(r/'late_sequence.json')['v5_valid'] else None
target_names=set(v5['targets']['movie']['target_names']) if v5 else None
rows=[]
for ip_path in sorted(root.glob('*/movie_p*/main_ip_counts.json.gz')):
 data=gz(ip_path);symbols=gz(ip_path.parent.parent/'movie.symbols.json.gz')
 assert data['binary_sha256']==symbols['binary_sha256']
 ranges=symbols['ranges'];locations={}
 entry_lines={s['start']//64 for s in ranges if target_names is not None and set(s['names'])&target_names}
 for row in data['rows']:
  ip=int(row['va'],16);matches=[s for s in ranges if s['start']<=ip<s['end']]
  if len(matches)!=1:locations[row['va']]=('unmapped' if not matches else 'ambiguous',None,None)
  else:
   s=matches[0];entry=ip//64==s['start']//64
   targeted=bool(set(s['names'])&target_names) if target_names is not None else None
   locations[row['va']]=('entry_cache_line' if entry else 'later_cache_line',tuple(s['names']),targeted)
 populations={'all_mapped_main':data['rows'],
  'age10_20_mapped_main':[x for x in data['age_rows'] if 10<=data['bins_us'][x['bin_index']]<20]}
 groups={}
 for population,items in populations.items():
  counts=Counter();functions=Counter();targeted_counts=Counter();total=0;entry_line_events=0
  for item in items:
   n=item['estimated_events'];kind,names,targeted=locations[item['va']]
   total+=n;counts[kind]+=n
   if int(item['va'],16)//64 in entry_lines:entry_line_events+=n
   if names:functions[names]+=n
   if targeted is not None:targeted_counts[('targeted_function_' if targeted else 'untargeted_function_')+kind]+=n
  assert sum(counts.values())==total
  if target_names is not None:assert sum(targeted_counts.values())+counts['unmapped']+counts['ambiguous']==total
  top=[]
  for names,n in functions.most_common(12):
   demangled=subprocess.check_output(['c++filt',*names],text=True).splitlines()
   top.append(dict(names=list(names),demangled=demangled,estimated_events=n,share_pct_of_main=100*n/total if total else None))
  groups[population]=dict(estimated_events=total,counts=dict(counts),
   v5_selected_entry_line_events=entry_line_events if target_names is not None else None,
   v5_selected_entry_line_pct_of_main=100*entry_line_events/total if total and target_names is not None else None,
   pct_of_main={k:100*v/total for k,v in counts.items()} if total else {},
   v5_selected_function_counts=dict(targeted_counts),
   v5_selected_function_pct_of_main={k:100*v/total for k,v in targeted_counts.items()} if total else {},top_functions=top)
 if 'v5_c4' in ip_path.parent.parent.name and target_names is not None:
  overlap=read(ip_path.parent/'target_overlap.json')
  assert groups['all_mapped_main']['v5_selected_entry_line_events']==sum(x.get('static_target_line',0) for x in overlap['bins'])
 rows.append(dict(name=ip_path.parent.parent.name,binary_sha256=data['binary_sha256'],groups=groups))
(r/'final_residual_locations.json').write_text(json.dumps(dict(rows=rows,
 v5_target_function_names=sorted(target_names) if target_names is not None else None,
 interpretation='Secondary descriptive attribution from retained main-image PEBS retirement IP aggregates. Entry-cache-line means the 64B line containing the unique owning function start, not all first64bytes. Exact symbol aliases share one range; overlaps/unmapped remain explicit. V5-selected function classification uses actual audited target names, applied separately in each binary. It is not dynamic hint coverage, a fill success rate, or evidence of a BTB/FDIP cause. Remaining sampled misses exclude avoided misses.'),indent=2,ensure_ascii=False)+'\n')
print('Wrote residual location classification for',len(rows),'captures')
