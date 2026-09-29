#!/usr/bin/env python3
"""Run an offline command between fully restored serial campaign trials."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import dense_build as b


def run(spec):
    root=Path(spec['out']);root.mkdir(exist_ok=False);b.space(root)
    pid=spec['pid'];proc=Path('/proc')/str(pid)
    command=[part.decode() for part in proc.joinpath('cmdline').read_bytes().split(b'\0') if part]
    assert command==spec['expected_command'],(command,spec['expected_command'])
    assert command[2]=='campaign' and Path(command[1]).name in ['callpath_frontend_diagnostic.py','balanced_backend.py','hybrid_campaign.py']
    identity=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]
    child_ids=proc.joinpath('task',str(pid),'children').read_text().split();assert len(child_ids)==1
    child=Path('/proc')/child_ids[0]
    args=[v.decode() for v in child.joinpath('cmdline').read_bytes().split(b'\0') if v]
    assert any(value.endswith('/run_platform.py') for value in args)
    assert args[-2]=='trial'
    trial=Path(json.loads(Path(args[-1]).read_text())['out']);platform=trial.with_name(trial.name+'_platform')
    record=dict(spec,identity=identity,trial=str(trial),child_pid=int(child_ids[0]),requested_epoch=time.time(),
        rule='Stop only outer campaign parent waiting for current platform child. Allow active workload and restoration to finish before offline work; always resume identical parent.')
    b.save(root/'intermission.json',record);stopped=False
    try:
        os.kill(pid,signal.SIGSTOP);stopped=True;deadline=time.monotonic()+900
        while child.exists():
            if child.joinpath('stat').read_text().rsplit(')',1)[1].split()[0]=='Z':break
            assert time.monotonic()<deadline
            time.sleep(1)
        assert json.loads((trial/'result.json').read_text())['valid']
        checks=[]
        for before in platform.rglob('*_before.json'):
            restored=before.with_name(before.name.replace('_before','_restored'))
            checks.append(restored.exists() and json.loads(before.read_text())==json.loads(restored.read_text()))
        assert checks and all(checks)
        record.update(trial_finished_epoch=time.time(),restoration_checks=len(checks));b.save(root/'intermission.json',record)
        b.run(spec['offline_command'],root/'offline.log')
        b.save(root/'complete.json',dict(valid=True))
    except BaseException as error:b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        if stopped:
            assert proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]==identity
            os.kill(pid,signal.SIGCONT)
        record.update(resumed=stopped,resumed_epoch=time.time());b.save(root/'intermission.json',record)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    run(json.loads(a.spec.read_text()))
