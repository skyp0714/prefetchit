#!/usr/bin/env python3
"""Pause only a campaign parent; validate new code after its trial has exited."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import dense_build as b
from hybrid_campaign import tests


def run(parent,pid):
    root=parent/'hybrid_native_preflight';root.mkdir(exist_ok=False);b.space(root)
    proc=Path('/proc')/str(pid)
    command=proc.joinpath('cmdline').read_bytes().split(b'\0')
    assert command[1].endswith(b'/backend_study.py') and command[2]==b'campaign'
    assert command[3].decode()==str(parent/'callpath_coverage75/screen_spec.json')
    identity=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]
    child_ids=proc.joinpath('task',str(pid),'children').read_text().split();assert len(child_ids)==1
    child=Path('/proc')/child_ids[0];args=child.joinpath('cmdline').read_bytes().split(b'\0')
    assert any(value.endswith(b'/run_platform.py') for value in args)
    trial_spec=Path(next(value.decode() for value in args if value.endswith(b'.json') and b'/screen/' in value))
    trial=Path(json.loads(trial_spec.read_text())['out']);platform=trial.with_name(trial.name+'_platform')
    record=dict(parent_pid=pid,parent_start_ticks=identity,child_pid=int(child_ids[0]),trial=str(trial),
        source_sha256=b.sha(__file__),pause_requested_epoch=time.time(),
        rule='SIGSTOP only the outer campaign process waiting for its platform child. The current trial and platform restoration continue normally. Build/test only after that child exits and all recorded platform states are restored.')
    b.save(root/'intermission.json',record)
    stopped=False
    try:
        os.kill(pid,signal.SIGSTOP);stopped=True
        deadline=time.monotonic()+600
        while child.exists():
            if child.joinpath('stat').read_text().rsplit(')',1)[1].split()[0]=='Z':break
            assert time.monotonic()<deadline,'Trial did not finish before bounded intermission timeout'
            time.sleep(1)
        result=json.loads((trial/'result.json').read_text());assert result['valid']
        checks=[]
        for before in platform.rglob('*_before.json'):
            after=before.with_name(before.name.replace('_before','_restored'))
            checks.append(after.exists() and json.loads(before.read_text())==json.loads(after.read_text()))
        assert checks and all(checks),'Platform restoration not complete'
        record.update(trial_finished_epoch=time.time(),restoration_checks=len(checks));b.save(root/'intermission.json',record)
        tests(root)
        paths=[b.REPO/'llvm_prefetchit/tools/call_stub_prefetch.py',b.REPO/'llvm_prefetchit/tools/hybrid_call_assembly.py',
            b.REPO/'llvm_prefetchit/tests/test_call_stub_prefetch.py',b.REPO/'llvm_prefetchit/tests/test_callpath_instruction_hint.py',
            b.REPO/'llvm_prefetchit/scripts/class_b/callpath_instruction_hint.py']
        b.save(root/'native_test_sources.json',dict(passed=True,sha256={str(path):b.sha(path) for path in paths}))
        shim=root/'hybrid_map.so';shim_source=b.REPO/'llvm_prefetchit/kernel/sched_clock/hybrid_map.c'
        try:
            b.run(['gcc','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',shim_source,'-o',shim],root/'shim_build.log')
            b.run(['readelf','--version-info',shim],root/'shim_versions.log')
            b.run(['/usr/bin/env','LD_PRELOAD='+str(shim),'/bin/true'],root/'shim_passthrough.log')
            b.save(root/'shim_build.json',dict(binary=str(shim),sha256=b.sha(shim),source_sha256=b.sha(shim_source),
                validation='Warning-clean shared-library build and passthrough for an unmodified executable. Real clock-device mapping remains pending.'))
        except BaseException:
            from e2e_lbr import remove_generated
            if shim.exists():remove_generated([shim],root/'shim_rejected_cleanup.json','Shim preflight rejected; preserve source, commands and output.')
            raise
        b.save(root/'complete.json',dict(valid=True,native_tests_passed=True))
    except BaseException as error:b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        if stopped:
            assert proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]==identity
            os.kill(pid,signal.SIGCONT)
        record.update(resumed_epoch=time.time(),resumed=stopped);b.save(root/'intermission.json',record)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);p.add_argument('pid',type=int);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    run(a.parent,a.pid)
