from pathlib import Path
import datetime,json,os,signal,sys,time
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from lean_evaluate import evaluate
from lean_timeline_summary import summarize
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_lean_20260928')
def now():return datetime.datetime.now(datetime.timezone.utc)
def read(path):return json.loads(path.read_text())
record=dict(status='Waiting for both frozen independent confirmations',started_utc=now().isoformat())
b.save(r/'late_sequence.json',record)
while True:
    try:complete=read(r/'confirmation_sequence.json').get('complete')
    except (FileNotFoundError,json.JSONDecodeError):complete=False
    if complete:break
    if now()>=datetime.datetime(2026,9,28,12,30,tzinfo=datetime.timezone.utc):
        raise RuntimeError('Confirmation unexpectedly overran late-phase budget; inspect active work before proceeding')
    time.sleep(5)
# Only the waiting supervisor is stopped. Its accepted-timing child has now
# finished both campaigns and all platform/module restoration checks.
old=3611888;cmd=Path(f'/proc/{old}/cmdline')
if cmd.exists():
    assert cmd.read_bytes().split(b'\0')[:2]==[b'python3',str(r/'run_remaining.py').encode()]
    os.kill(old,signal.SIGTERM);os.kill(old,signal.SIGCONT)
    for _ in range(100):
        if not cmd.exists():break
        time.sleep(.02)
    else:raise RuntimeError('Old diagnostic supervisor did not exit')
record.update(status='Confirmations complete; preparing V5',confirmation_finished_utc=now().isoformat())
b.save(r/'late_sequence.json',record)
v4=read(r/'screen_v4_spec.json');selection=read(r/'v4_selection.json');diag=read(r/'gate_diag_build.json')
oldpair=[Path(p) for arm in (selection['selected'],selection['matched_nop']) for p in v4['arms'][arm]['overrides'].values()]
confirmed=any(read(r/f'confirmation_c{c}/evaluation.json')['decisions']['selected_candidate']['confirmed'] for c in (4,16))
new_ok=False;screen=False
try:
    if now()<datetime.datetime(2026,9,28,12,23,tzinfo=datetime.timezone.utc):
        b.run(['python3',r/'build_v5.py'],r/'build_v5.log')
        new_ok=True
        if now()<datetime.datetime(2026,9,28,12,23,tzinfo=datetime.timezone.utc):
            b.run(['python3',repo/'llvm_prefetchit/scripts/class_b/lean_study.py',r/'screen_v5_spec.json'],r/'screen_v5.log')
            result=evaluate(r/'screen_v5');screen=True
            b.save(r/'v5_decision.json',dict(promoted=False,exploratory_only=True,decisions=result['decisions'],
                interpretation='Two-block mechanism screen. No independent V5 promotion and no pooling with V4 confirmations.'))
            if not result['decisions']['callees_ungated_it0']['point_eligible']:
                setting=read(r/'screen_v5_spec.json')['arms']['callees_ungated_nop']
                remove_generated([Path(p) for p in setting['overrides'].values()],r/'v5_rejected_nop_cleanup.json','V5 point criteria failed. NOP has no diagnostic use; compact results and hashes retained. PF remains active for residual-miss diagnostics only.')
        else:
            b.save(r/'v5_screen_omitted.json',dict(utc=now().isoformat(),reason='Predeclared12:23UTC admission boundary passed after build/audit; no performance observation used.'))
    else:
        b.save(r/'v5_build_omitted.json',dict(utc=now().isoformat(),reason='Confirmations passed the predeclared late build/screen admission boundary.'))
except Exception as error:
    b.save(r/'v5_stage_failure.json',dict(utc=now().isoformat(),error=repr(error),new_ok=new_ok,screen=screen,
        reason='Retain compact failure evidence; invalid V5 is excluded and original selected pair remains active diagnostic fallback.'))
    paths=[p for tag in ('lean_v5_callees_ungated','lean_v5_callees_ungated_it0')
        for key,exe in b.SERVICES.items() for name in (exe,exe+'.nop')
        if (p:=r/'builds'/tag/key/name).exists()]
    if paths:remove_generated(paths,r/'v5_failed_cleanup.json','Failed V5 follow-up; source/commands/build logs, available audits, hashes and exclusion reason retained. No failed binary is used for diagnostics.')
    new_ok=False
# Old selected pair is an active fallback until the new screen/audit succeeds.
if new_ok and not confirmed:
    remove_generated(oldpair,r/'v4_confirmation_rejected_cleanup.json','Both independent V4 confirmation criteria failed. V5 follow-up validated; old selected pair is no longer needed as diagnostic fallback. All compact outcomes retained.')
new=read(r/'v5_build.json')['overrides'] if new_ok else v4['arms'][selection['selected']]['overrides']
module=v4['module'];options=v4['clock_options']
common=dict(module=module,clock_options=options,concurrency=4,seed=61001)
trials=[dict(common,name='gate_counter_c4',overrides=diag['overrides'],clock=True,services=['movie','compose','rating'],
    periods=[],gate_stats=True,gate_only=True,original_gated=diag['original_gated'])]
for name,overrides in [('base_c4',v4['arms']['base']['overrides']),('v5_c4' if new_ok else 'v4_fallback_c4',new)]:
    trials.append(dict(common,name=name,overrides=overrides,clock=False,services=['movie'],periods=[4093]))
protocol=dict(out=str(r/'diagnostics_late'),trials=trials,
    purpose='Late separate MovieId schedule-age/target coverage and all3 gate counters; no E2E claims.',
    supersedes=['diagnostics_v4.json','diagnostics_c16.json'],
    reason='V4 post-ROI mechanism evidence motivated a new ungated-callee E2E screen. Diagnostic breadth reduced prospectively to honor7hour budget; original protocols retained, never executed.',
    limitation='One current PEBS sample period and MovieId only; cannot claim current all-service or C16 age-distribution validation.',
    v5_valid=new_ok,v5_screen_complete=screen)
b.save(r/'diagnostics_late.json',protocol)
if now()<datetime.datetime(2026,9,28,12,40,tzinfo=datetime.timezone.utc):
    b.run(['python3',repo/'llvm_prefetchit/scripts/class_b/lean_timeline.py','campaign',r/'diagnostics_late.json'],r/'diagnostics_late.log')
    summary=summarize(r/'diagnostics_late')
    record['diagnostic_records']=len(summary['rows']);record['diagnostics_complete']=True
else:
    b.save(r/'diagnostics_late_omitted.json',dict(utc=now().isoformat(),reason='Predeclared12:40UTC admission boundary passed; leave time for required final report and cleanup.'))
    record['diagnostics_complete']=False
record.update(status='Late phases finished; final report/cleanup pending',complete=True,v5_valid=new_ok,v5_screen_complete=screen,completed_utc=now().isoformat())
b.save(r/'late_sequence.json',record);print(json.dumps(record),flush=True)
