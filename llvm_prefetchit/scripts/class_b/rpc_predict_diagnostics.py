#!/usr/bin/env python3
"""Full-system PMU after clean endpoints; no profiled timing enters speedup."""
import argparse
from pathlib import Path
import signal
import time

import dense_build as b
from rpc_route_study import load
from rpc_predict_run import run, SCRIPTS
import fullset as h


def main(root):
    assert load(root/'production_complete.json')['valid'];arms=load(root/'arms.json')
    candidate=load(root/'production_selection.json')['nominee']
    run(root,'pmu_preflight',['python3',SCRIPTS/'temporal_path_final_pmu.py','preflight',root])
    for index,(name,suite) in enumerate([('full','core'),(candidate,'core'),(candidate,'extra'),('full','extra')]):
        label=name+'_'+suite;spec=root/('pmu_'+label+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'diagnostics'/label),arm=name,suite=suite,
            seed=1020701,reverse_pmu=bool(index%2)))
        run(root,'pmu_'+label,['python3',SCRIPTS/'temporal_path_final_pmu.py','platform_trial',spec])
        assert load(root/'diagnostics'/label/'result.json')['valid']
    run(root,'pmu_summary',['python3',SCRIPTS/'temporal_path_metrics.py',root])
    assert load(root/'profiles'/candidate/'complete.json')['valid']
    import media_system_study as system
    for name in ('full',candidate):
        spec=root/('profile_mongo_'+name+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'mongo_profiles'/name),services=list(system.MONGO),
            kinds=['l2'],capture_s=8,seed=1020401,phase='mongo_residual',arm=name))
        run(root,'profile_mongo_'+name,['python3',SCRIPTS/'temporal_path_study.py','platform_capture',spec])
        assert load(root/'mongo_profiles'/name/'complete.json')['valid']
    b.save(root/'diagnostics_complete.json',dict(valid=True,epoch=time.time()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    main(parser.parse_args().root)
