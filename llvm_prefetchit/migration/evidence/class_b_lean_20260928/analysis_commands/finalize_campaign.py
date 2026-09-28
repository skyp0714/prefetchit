from pathlib import Path
import datetime,json,subprocess,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_lean_20260928');b.space(r)
def read(path):return json.loads(path.read_text())
assert read(r/'confirmation_sequence.json').get('complete')
assert read(r/'late_sequence.json').get('complete'),'Finish late measurements and extract results before cleanup'
assert not Path('/sys/module/prefetchit_sched_clock').exists()
assert not subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project=codex-b-fullset-media'],text=True).strip()
v4=read(r/'screen_v4_spec.json');selection=read(r/'v4_selection.json')
confirmations={str(c):read(r/f'confirmation_c{c}/evaluation.json') for c in (4,16)}
passes={c:d['decisions']['selected_candidate']['confirmed'] for c,d in confirmations.items()}
v4_keep=any(passes.values());keep={};remove=[]
for arm in (selection['selected'],selection['matched_nop']):
 for path in v4['arms'][arm]['overrides'].values():
  p=Path(path)
  if v4_keep:
   assert p.exists();keep[p]='Independent V4 E2E criterion passed at at least one declared concurrency; reference/control artifact'
  elif p.exists():remove.append(p)
v5_keep=False
if (r/'screen_v5/complete.json').exists():
 d=read(r/'screen_v5/evaluation.json');v5_keep=d['decisions']['callees_ungated_it0']['point_eligible']
for tag in ('lean_v5_callees_ungated','lean_v5_callees_ungated_it0'):
 for key,exe in b.SERVICES.items():
  for name in (exe,exe+'.nop'):
   path=r/'builds'/tag/key/name
   if not path.exists():continue
   if v5_keep and ((tag=='lean_v5_callees_ungated' and name==exe+'.nop') or (tag=='lean_v5_callees_ungated_it0' and name==exe)):
    keep[path]='Current exploratory V5 reference/control awaiting independent replication; not a confirmed improvement'
   else:remove.append(path)
for path in read(r/'gate_diag_build.json')['overrides'].values():
 if Path(path).exists():remove.append(Path(path))
# Remove only known Kbuild-generated files; retain the reference module and sources.
for pattern in ('*.o','*.mod','*.mod.c','*.order','*.symvers','.*.cmd'):
 remove.extend(p for p in (r/'kernel_v1').glob(pattern) if p.is_file() and not p.is_symlink())
if remove:
 remove_generated(sorted(set(remove)),r/'final_unused_cleanup.json','All diagnostics completed or explicitly omitted by time budget. Remove rejected/unmeasured executable/control/counter and unused Kbuild artifacts after compact results, sources, commands, patch records and hashes were retained.')
for path in v4['arms']['base']['overrides'].values():keep[Path(path)]='Original no-prefetch control; preserved'
keep[r/'plugin_v4c/PrefetchITPass.so']='Current validated compiler plugin reference for reproducing recorded policies'
keep[r/'kernel_v1/prefetchit_sched_clock.ko']='Current ABI2 scheduler clock reference module'
retained=[]
for path,reason in keep.items():
 assert path.is_file() and not path.is_symlink()
 retained.append(dict(path=str(path),bytes=path.stat().st_size,sha256=b.sha(path),reason=reason))
b.save(r/'artifact_retention.json',dict(retained=retained,
 baseline_sources_inputs_packages_shared_dependencies='Preserved; no symlink traversal or NAS transfer',
 v4_confirmed_reference=v4_keep,v5_exploratory_reference=v5_keep))
ten=False
for c,d in confirmations.items():
 if not passes[c]:continue
 x=d['comparisons']['selected_candidate']['base'];t=d['throughput']['selected_candidate']['base']
 ten |= any(x[k]['ci95_pct'][0]>=10 for k in ('mean_ms','p99_ms')) or t['ci95_pct'][0]>=10
record=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),ten_percent_e2e_confirmed=ten,
 v4_selected=selection['selected'],v4_confirmed_by_concurrency=passes,
 v5_independently_confirmed=False,v5_exploratory_reference_retained=v5_keep,
 independent_evaluation_sha256={c:b.sha(r/f'confirmation_c{c}/evaluation.json') for c in (4,16)},
 scope='MovieId, ComposeReview and Rating simultaneous policy changes in the full Media stack; C4 and near-plateau C16. Late V5 is a separate C4 screen, not pooled.',
 diagnostic_scope=read(r/'diagnostics_late.json')['limitation'],
 diagnostic_completed=read(r/'late_sequence.json')['diagnostics_complete'],
 original_all3_two_period_and_c16_age_protocols='Superseded prospectively by V5 follow-up; never executed.',
 stopped_services=True,module_unloaded=True)
b.save(r/'final_decision.json',record)
print(json.dumps(record,indent=2))
