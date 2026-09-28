from pathlib import Path
import datetime,json,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from lean_timeline_summary import summarize
r=Path('/storage/prefetchit/class_b_lean_20260928')
record=dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),steps=[])
b.save(r/'remaining_sequence.json',record)
b.run(['python3',r/'run_confirmations.py'],r/'confirmation_sequence.log')
record['steps'].append('Both independent confirmations completed and evaluated');b.save(r/'remaining_sequence.json',record)
for phase in ('diagnostics_v4','diagnostics_c16'):
    now=datetime.datetime.now(datetime.timezone.utc)
    if phase=='diagnostics_c16' and now>=datetime.datetime(2026,9,28,12,33,tzinfo=datetime.timezone.utc):
        b.save(r/'diagnostics_c16_admission.json',dict(run=False,utc=now.isoformat(),
            reason='Predeclared time-only budget boundary passed; no performance-based omission.'))
        break
    b.space(r)
    b.save(r/(phase+'_admission.json'),dict(run=True,utc=now.isoformat(),
        reason='All clean E2E timings complete; time-only admission boundary satisfied.'))
    command=['python3',repo/'llvm_prefetchit/scripts/class_b/lean_timeline.py','campaign',r/(phase+'.json')]
    b.run(command,r/(phase+'.log'))
    summary=summarize(r/phase)
    record['steps'].append(dict(phase=phase,records=len(summary['rows']),pebs_captures=sum(not v.get('gate_only') for v in summary['rows']),counter_service_windows=sum(bool(v.get('gate_only')) for v in summary['rows']),
        completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    b.save(r/'remaining_sequence.json',record)
record['complete']=True;b.save(r/'remaining_sequence.json',record)
print(json.dumps(record),flush=True)
