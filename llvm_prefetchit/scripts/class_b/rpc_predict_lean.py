#!/usr/bin/env python3
"""Remove inactive timing-control detours without moving any enabled hint."""
import argparse
import copy
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load
from rpc_predict_run import campaign, run, SCRIPTS
from temporal_path_confirm import cleanup


def prepare(root):
    assert load(root/'measurement_complete.json')['valid']
    assert (root/'lean_predeclared.json').exists()
    b.space(root);arms=load(root/'arms.json');nominee=load(root/'screen_decision.json')['nominee']
    arm=copy.deepcopy(arms[nominee]);nop=copy.deepcopy(arm);builds={};total_restored=0
    for service,source in arms[nominee]['overrides'].items():
        b.space(root);source=Path(source);record=load(Path(str(source)+'.json'))
        raw=bytearray(source.read_bytes());active={h['va'] for h in record['hints']};restored=[]
        for patch in record['patches']:
            if not any(patch['stub']<=va<max(patch['terminal_jumps'])+5 for va in active):
                before=raw[patch['offset']:patch['offset']+5].hex()
                assert before==patch['replacement']
                raw[patch['offset']:patch['offset']+5]=bytes.fromhex(patch['expected'])
                restored.append(dict(site=patch['site'],offset=patch['offset'],before=before,after=patch['expected']))
        total_restored+=len(restored)
        for hint in record['hints']:assert raw[hint['offset']:hint['offset']+7]==bytes.fromhex(hint['original'])
        output=root/'builds'/'lean'/service/source.name;output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(raw);output.chmod(0o755)
        twin=root/'builds'/'lean_nop'/service/source.name;twin.parent.mkdir(parents=True,exist_ok=True)
        for hint in record['hints']:raw[hint['offset']:hint['offset']+7]=bytes.fromhex(hint['nop'])
        twin.write_bytes(raw);twin.chmod(0o755)
        meta=dict(record,sha256=b.sha(output),nop_sha256=b.sha(twin),restored_inactive_calls=restored,
            timing_pair_source=str(source),timing_pair_sha256=b.sha(source),variant='lean',nop_path=str(twin))
        b.save(Path(str(output)+'.json'),meta)
        b.save(Path(str(twin)+'.json'),dict(meta,sha256=b.sha(twin),hints=[],variant='lean_nop'))
        arm['overrides'][service]=str(output);nop['overrides'][service]=str(twin)
        builds[service]=dict(binary=str(output),sha256=b.sha(output),nop=str(twin),nop_sha256=b.sha(twin),restored_sites=len(restored))
    arms.update(lean=arm,lean_nop=nop);b.save(root/'arms.json',arms)
    prepared=load(root/'prepared_candidates.json');prepared['lean']=dict(arm=arm,nop=nop,builds=builds)
    b.save(root/'prepared_candidates.json',prepared)
    result=dict(valid=True,nominee=nominee,restored_sites=total_restored,builds=builds,epoch=time.time(),source_sha256=b.sha(__file__),
        interpretation='Original E8 call restored only at new-hint-disabled phase sites; incumbent callee/stub remains. Enabled hints, target addresses and executable layout unchanged. Dead mapped bytes remain; executed detours decrease.')
    b.save(root/'lean_prepared.json',result)
    print(result)


def measure(root):
    assert load(root/'lean_prepared.json')['valid'];arms=load(root/'arms.json')
    for index,name in enumerate(('lean','lean_nop')):
        spec=root/('smoke_'+name+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'smoke'/name),seed=1020501+index))
        run(root,'smoke_'+name,['python3',SCRIPTS/'rpc_route_followup.py','platform_smoke',spec])
        assert load(root/'smoke'/name/'result.json')['valid']
    # Timing pairs have finished all required captures. Retire their generated
    # executables immediately; keep their patches, measurements and source.
    cleanup(root,['early','late','split','nop'],[arms['full'],arms['original'],arms['lean'],arms['lean_nop']], 'timing_pair_cleanup.json')
    campaign(root,'lean_confirmation',arms,['full','lean','lean_nop'],5,1020601)
    b.save(root/'lean_complete.json',dict(valid=True,epoch=time.time(),trials=15))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','measure']);parser.add_argument('root',type=Path)
    args=parser.parse_args();globals()[args.action](args.root)
