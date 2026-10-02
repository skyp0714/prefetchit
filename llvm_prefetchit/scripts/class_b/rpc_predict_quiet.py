#!/usr/bin/env python3
"""Restart the whole exploratory stage after authorized external-load removal."""
import argparse
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load
from rpc_predict_run import run, SCRIPTS


def main(root):
    assert load(root/'quiet_recovery_protocol.json')['valid']
    assert not (root/'quiet_coverage_screen').exists()
    assert not (root/'production_selection.json').exists()
    (root/'source_versions'/(b.sha(__file__)+'.py')).write_bytes(Path(__file__).read_bytes())
    run(root,'lean_measure_quiet',['python3',SCRIPTS/'rpc_predict_lean.py','measure',root,'--quiet'])
    run(root,'diagnostics',['python3',SCRIPTS/'rpc_predict_diagnostics.py',root])
    run(root,'residual_analysis_final',['python3',SCRIPTS/'rpc_predict_analysis.py',root])
    run(root,'conditions_final',['python3',SCRIPTS/'rpc_predict_conditions.py',root])
    b.save(root/'all_measurements_complete.json',dict(valid=True,epoch=time.time(),
        primary_selection='quiet_coverage_screen',external_load_records='coverage_screen'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    main(parser.parse_args().root)
