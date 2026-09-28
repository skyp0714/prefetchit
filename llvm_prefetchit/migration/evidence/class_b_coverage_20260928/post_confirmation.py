from pathlib import Path
import datetime, json, subprocess, sys
r=Path('/storage/prefetchit/class_b_coverage_20260928')
assert (r/'confirmation/complete.json').exists()
steps=[]
for name in ('diagnose_selected.py','summarize_residual.py','finish_confirmation.py',
             'final_retention.py','audit_finished.py'):
    command=[sys.executable,str(r/name)]
    print('Starting '+name,flush=True)
    start=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (r/(name.removesuffix('.py')+'.driver.log')).open('w') as f:
        subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=True)
    steps.append(dict(command=command,start=start,
        finished=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    print('Completed '+name,flush=True)
(r/'post_confirmation_complete.json').write_text(json.dumps(dict(steps=steps),indent=2)+'\n')
print('All diagnostics, decisions, retention and environment audits complete.',flush=True)
