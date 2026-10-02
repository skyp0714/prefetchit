#!/usr/bin/env python3
"""Durable sequential continuation; never overlap analysis/builds with timing."""
import argparse
import os
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load
from rpc_predict_run import run, SCRIPTS


def main(root,pid,resume=False):
    protocol='continuation_resume_protocol.json' if resume else 'continuation_protocol.json'
    assert not (root/protocol).exists()
    b.save(root/protocol,dict(epoch=time.time(),wait_for_pid=pid,resume=resume,
        wait_for=str(root/'measurement_complete.json'),source_sha256=b.sha(__file__),
        sequence=['residual analysis','lean prepare','lean independent confirmation','separate PMU and lean profile','final residual analysis'],
        rule='Every stage requires its predecessor completion marker. No builds or analysis during clean endpoint trials. Failures stop this continuation with command/log retained.'))
    (root/'source_versions'/(b.sha(__file__)+'.py')).write_bytes(Path(__file__).read_bytes())
    while not (root/'measurement_complete.json').exists():
        os.kill(pid,0)
        time.sleep(10)
    assert load(root/'measurement_complete.json')['valid']
    if resume:
        assert load(root/'lean_prepared.json')['valid']
        assert (root/'straddle_amendment.json').exists() and not (root/'coverage_screen').exists()
    else:
        run(root,'residual_analysis',['python3',SCRIPTS/'rpc_predict_analysis.py',root])
        run(root,'lean_prepare',['python3',SCRIPTS/'rpc_predict_lean.py','prepare',root])
    run(root,'lean_measure_resumed' if resume else 'lean_measure',['python3',SCRIPTS/'rpc_predict_lean.py','measure',root])
    run(root,'diagnostics',['python3',SCRIPTS/'rpc_predict_diagnostics.py',root])
    run(root,'residual_analysis_final',['python3',SCRIPTS/'rpc_predict_analysis.py',root])
    b.save(root/'all_measurements_complete.json',dict(valid=True,epoch=time.time()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('pid',type=int)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();main(args.root,args.pid,args.resume)
