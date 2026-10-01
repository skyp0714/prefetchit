#!/usr/bin/env python3
"""Freeze a RPC nominee, independently confirm its combination, then collect PMU."""
import argparse
import copy
import datetime
import json
from pathlib import Path
import subprocess
import time

import dense_build as b
from rpc_route_study import load
from temporal_path_confirm import select, cleanup


def run(root, label, command):
    b.space(root)
    b.save(root/(label+'_command.json'), dict(epoch=time.time(),command=list(map(str,command))))
    with (root/(label+'.log')).open('w') as output:
        subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,check=True)


def finish(root):
    assert load(root/'screen2/complete.json')['valid']
    scripts=Path(__file__).parent.resolve()
    prepared=load(root/'prepared_candidates.json');arms=load(root/'arms.json')
    decision=select(load(root/'screen2/rows.json'),'no_dso',['rpc_worker','rpc_worker_it0'],2)
    eligible=decision['eligible']
    nominee=max(eligible or ['rpc_worker','rpc_worker_it0'],key=lambda n:decision['means'][n]['geometric_rps'])
    decision.update(epoch=time.time(),nominee=nominee,nominee_passes_guardrails=nominee in eligible,
        note='Nomination for independent testing is not promotion; retain no_dso as an explicit control even when it leads the screen.')
    b.save(root/'screen2_decision.json',decision)
    cleanup(root,[n for n in ['rpc_worker','rpc_worker_it0'] if n!=nominee],
        [arms['original'],arms['full_dso'],arms['no_dso'],prepared[nominee]['arm'],prepared[nominee]['nop']],
        'screen2_rejected_cleanup.json')
    run(root,'combined_prepare',['python3',scripts/'rpc_route_followup.py','combine',root,'--choice',nominee])
    arms=load(root/'arms.json');combined='full_'+nominee
    spec=root/('smoke_'+combined+'.json')
    b.save(spec,dict(arms[combined],root=str(root),out=str(root/'smoke'/combined),seed=1040501))
    run(root,'smoke_'+combined,['python3',scripts/'rpc_route_followup.py','platform_smoke',spec])
    assert load(root/'smoke'/combined/'result.json')['valid']
    now=datetime.datetime.now(datetime.timezone.utc)
    blocks=4 if (now.hour,now.minute)<=(13,55) else 3
    names=['original','full_dso','no_dso',nominee,combined]
    controls={name:dict(copy.deepcopy(arms[name]),controls=[n for n in names if n!=name]) for name in names}
    # Every policy has mean ordinal position two in either the three- or
    # four-block schedule. Freeze this without inspecting confirmation data.
    base=['full_dso',nominee,'original',combined,'no_dso']
    if blocks==3:
        orders=[base,[base[i] for i in [3,4,0,1,2]],[base[i] for i in [2,4,1,3,0]]]
    else:
        rotated=base[2:]+base[:2]
        orders=[base,list(reversed(base)),rotated,list(reversed(rotated))]
    assert all(sum(order.index(name) for order in orders)==2*blocks for name in names)
    setting=dict(root=str(root),out=str(root/'confirmation'),arms=controls,blocks=blocks,orders=orders,
        seedbase=1040601,order_seed=1040600,trial_script=str(scripts/'temporal_path_trial.py'),
        scope='Fresh independent full-request confirmation; five arms include both DSO-free and full-incumbent RPC changes. No PMU.',
        budget_rule='Four blocks if confirmation starts by13:55UTC, otherwise three; fixed before first confirmation endpoint.',
        no_adaptive_stopping=True)
    b.save(root/'confirmation_spec.json',setting)
    b.save(root/'confirmation_selection.json',dict(nominee=nominee,combined=combined,blocks=blocks,epoch=time.time(),
        point_screen_winner=decision['selected'],promoted=False,rule='Confirm the frozen nominee without switching to a different screen policy based on confirmation noise.'))
    run(root,'confirmation',['python3',scripts/'temporal_path_campaign.py','campaign',root/'confirmation_spec.json'])
    assert load(root/'confirmation/complete.json')['valid']
    # This contrast was frozen before confirmation: hints versus exact NOP on
    # the full incumbent. Endpoint values from these PMU trials are discarded.
    prepared=load(root/'prepared_candidates.json')
    diag=root/'diagnostics';diag.mkdir(exist_ok=False)
    source_files=[scripts/n for n in ['rpc_route_followup.py','split_hybrid_study.py','backend_study.py',
        'media_system_study.py','fullset.py','balanced_backend.py','balanced_load.py','media_library_study.py',
        'backend_prefetch.py','hybrid_campaign.py','dense_causes.py']]
    hashes={str(path):b.sha(path) for path in source_files}
    for path in source_files:
        snapshot=root/'source_versions'/(hashes[str(path)]+'.py')
        if not snapshot.exists():snapshot.write_bytes(path.read_bytes())
    b.save(diag/'protocol.json',dict(arms=[combined+'_nop',combined],source_hashes=hashes,
        services=['movie','compose','rating'],purpose='Three modified apps plus separate pool user/kernel PMU; not latency/throughput evidence.'))
    for index,(name,kind) in enumerate([(combined+'_nop','nop'),(combined,'arm')]):
        assert all(b.sha(path)==value for path,value in hashes.items())
        spec=diag/(f'{index:02d}_{name}.json')
        b.save(spec,dict(prepared[combined][kind],out=str(spec.with_suffix('')),seed=1040701,reverse_pmu=bool(index)))
        run(root,'diagnostic_'+name,['python3',scripts/'rpc_route_followup.py','platform_diagnostic',spec])
        assert load(spec.with_suffix('')/'result.json')['valid']
    b.save(diag/'complete.json',dict(valid=True,trials=2))
    b.save(root/'measurement_complete.json',dict(valid=True,epoch=time.time(),clean_trials=14+len(names)*blocks,
        diagnostic_trials=2,smoke_trials=5,nominee=nominee,combined=combined))
    print(json.dumps(load(root/'measurement_complete.json')),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    finish(parser.parse_args().root)
