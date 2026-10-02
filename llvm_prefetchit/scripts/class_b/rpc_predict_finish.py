#!/usr/bin/env python3
"""Resume diagnostics after a recorded technical rejection, without retiming."""
import argparse
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load
from rpc_predict_run import run, SCRIPTS


def main(root):
    assert load(root/'production_complete.json')['valid']
    assert not (root/'all_measurements_complete.json').exists()
    source=Path(__file__);(root/'source_versions'/(b.sha(source)+'.py')).write_bytes(source.read_bytes())
    run(root,'diagnostics_resumed',['python3',SCRIPTS/'rpc_predict_diagnostics.py',root])
    run(root,'residual_analysis_final',['python3',SCRIPTS/'rpc_predict_analysis.py',root])
    run(root,'conditions_final',['python3',SCRIPTS/'rpc_predict_conditions.py',root])
    b.save(root/'all_measurements_complete.json',dict(valid=True,epoch=time.time(),
        primary_selection='quiet_coverage_screen',external_load_records='coverage_screen',
        recovery='Technical diagnostic rejection retained separately; no clean endpoint trials repeated.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);main(parser.parse_args().root)
