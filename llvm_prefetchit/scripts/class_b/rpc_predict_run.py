#!/usr/bin/env python3
"""Frozen RPC timing experiment and independent endpoint confirmation."""
import argparse
import copy
import json
from pathlib import Path
import signal
import subprocess
import time

import dense_build as b
from rpc_route_study import load
from temporal_path_confirm import select, cleanup

SCRIPTS=Path(__file__).parent.resolve()


def run(root,label,command):
    b.space(root)
    b.save(root/(label+'_command.json'),dict(epoch=time.time(),command=list(map(str,command))))
    print(json.dumps(dict(stage=label,epoch=time.time())),flush=True)
    with (root/(label+'.log')).open('w') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)


def campaign(root,label,arms,names,blocks,seed,orders=None):
    controls={n:dict(copy.deepcopy(arms[n]),controls=[v for v in names if v!=n]) for n in names}
    # Odd block counts: cyclic rotation avoids one fixed arm always running last.
    if orders is None:orders=[names[i%len(names):]+names[:i%len(names)] for i in range(blocks)]
    spec=dict(root=str(root),out=str(root/label),arms=controls,blocks=blocks,orders=orders,
        seedbase=seed,order_seed=seed-1,trial_script=str(SCRIPTS/'temporal_path_trial.py'),no_adaptive_stopping=True)
    b.save(root/(label+'_spec.json'),spec)
    run(root,label,['python3',SCRIPTS/'temporal_path_campaign.py','campaign',root/(label+'_spec.json')])
    assert load(root/label/'complete.json')['valid']


def main(root):
    arms=load(root/'arms.json');assert load(root/'prepared.json')['valid']
    (root/'source_versions'/(b.sha(__file__)+'.py')).write_bytes(Path(__file__).read_bytes())
    for index,name in enumerate(('early','late','split','nop')):
        spec=root/('smoke_'+name+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'smoke'/name),seed=1020100+index))
        run(root,'smoke_'+name,['python3',SCRIPTS/'rpc_route_followup.py','platform_smoke',spec])
        assert load(root/'smoke'/name/'result.json')['valid']
    campaign(root,'screen',arms,['full','early','late','split','nop'],3,1020201)
    decision=select(load(root/'screen/rows.json'),'full',['early','late','split'],3)
    nominee=max(decision['eligible'] or ['early','late','split'],key=lambda n:decision['means'][n]['geometric_rps'])
    decision.update(nominee=nominee,promoted=False,epoch=time.time())
    b.save(root/'screen_decision.json',decision)
    # Early/late/NOP remain active causal-diagnostic controls until fresh traces finish.
    rejected=[v for v in ('early','late','split') if v!=nominee and v not in ('early','late')]
    cleanup(root,rejected,[arms['full'],arms['original'],arms[nominee],arms['early'],arms['late'],arms['nop']], 'screen_cleanup.json')
    campaign(root,'confirmation',arms,['full',nominee,'original'],5,1020301)
    b.save(root/'endpoint_complete.json',dict(valid=True,nominee=nominee,clean_trials=30,epoch=time.time()))
    # Four independent, perturbing PEBS captures: timing pair, NOP, incumbent.
    for index,name in enumerate(dict.fromkeys(['full','early','late','nop',nominee])):
        spec=root/('profile_'+name+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'profiles'/name),services=list(arms[name]['overrides']),
            kinds=['l2'],capture_s=8,seed=1020401,phase='rpc_predict',arm=name))
        run(root,'profile_'+name,['python3',SCRIPTS/'temporal_path_study.py','platform_capture',spec])
        assert load(root/'profiles'/name/'complete.json')['valid']
    b.save(root/'measurement_complete.json',dict(valid=True,nominee=nominee,epoch=time.time()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    main(parser.parse_args().root)
