from pathlib import Path
import datetime,json,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from lean_evaluate import evaluate
r=Path('/storage/prefetchit/class_b_lean_20260928')
assert (r/'gate_diag_build.json').exists(),'Finish all diagnostic builds before accepted timing'
assert (r/'diagnostics_v4.json').exists(),'Freeze diagnostic comparison before confirmation observations'
record=dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),steps=[])
b.save(r/'confirmation_sequence.json',record)
for concurrency in (4,16):
    b.space(r)
    destination=r/f'confirmation_c{concurrency}'
    assert not destination.exists(),str(destination)
    command=['python3',repo/'llvm_prefetchit/scripts/class_b/lean_study.py',destination.with_suffix('.json')]
    b.run(command,r/f'confirmation_c{concurrency}.log')
    result=evaluate(destination,'selected_candidate','matched_nop')
    step=dict(concurrency=concurrency,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        evaluation_sha256=b.sha(destination/'evaluation.json'),decision=result['decisions'],means=result['means'])
    record['steps'].append(step);b.save(r/'confirmation_sequence.json',record)
    print(json.dumps(step),flush=True)
record['complete']=True;b.save(r/'confirmation_sequence.json',record)
