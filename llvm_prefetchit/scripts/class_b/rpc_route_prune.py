#!/usr/bin/env python3
"""Test removal of new worker hints that revisit the issuing cache line."""
import argparse
import copy
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load
from rpc_route_finish import run


def prepare(root):
    b.space(root)
    assert load(root/'measurement_complete.json')['valid']
    setting=load(root/'same_line_predeclared.json')
    prepared=load(root/'prepared_candidates.json');parent='full_rpc_worker';name=parent+'_pruned'
    assert name not in prepared
    entry=copy.deepcopy(prepared[parent]);entry['parent']=parent
    checks=[]
    for service in sorted({v['service'] for v in setting['same_line_targets']}):
        b.space(root)
        row=entry['builds'][service];source=Path(row['binary']);assert b.sha(source)==row['sha256']
        original=source.read_bytes();raw=bytearray(original);meta=load(Path(str(source)+'.json'));changed=[]
        for target in setting['same_line_targets']:
            if target['service']!=service:continue
            patch=next(p for p in meta['patches'] if p['site']==target['site'])
            assert target['target']//64==patch['site']//64
            hints=[h for h in meta['hints'] if h['target']==target['target'] and patch['stub']<=h['va']<patch['terminal_jumps'][0]]
            assert len(hints)==1
            h=hints[0];old=bytes.fromhex(h['original']);nop=bytes.fromhex(h['nop']);offset=h['offset']
            assert len(old)==len(nop)==7 and old[:3]==bytes.fromhex('0f1815')
            assert raw[offset:offset+7]==old
            raw[offset:offset+7]=nop
            changed.append(dict(**target,va=h['va'],offset=offset,old=old.hex(),new=nop.hex()))
        restored=bytearray(raw)
        for p in changed:restored[p['offset']:p['offset']+7]=bytes.fromhex(p['old'])
        assert restored==original,'Unintended byte changes'
        output=root/'builds'/name/service/source.name;output.parent.mkdir(parents=True,exist_ok=False)
        output.write_bytes(raw);output.chmod(0o755)
        disabled={p['va'] for p in changed};meta['hints']=[h for h in meta['hints'] if h['va'] not in disabled]
        meta.update(sha256=b.sha(output),output=str(output),
            transform=dict(source=str(source),source_sha256=row['sha256'],changes=changed,
                rule='Only new same-cache-line T1 hints become exact-size NOPs. All branches, addresses, remaining hints and CFI are byte-identical.',
                tool_sha256=b.sha(__file__)))
        b.save(Path(str(output)+'.json'),meta)
        row.update(binary=str(output),sha256=meta['sha256'],hints=len(meta['hints']),disabled_same_line=len(changed))
        entry['arm']['overrides'][service]=str(output)
        checks.append(dict(service=service,source=str(source),binary=str(output),sha256=meta['sha256'],changes=changed,
                           all_other_bytes_identical=True,nop_control=row['nop'],nop_sha256=row['nop_sha256']))
    assert sum(len(c['changes']) for c in checks)==3
    assert sum(row['hints'] for row in entry['builds'].values())==20
    prepared[name]=entry;b.save(root/'prepared_candidates.json',prepared)
    arms=load(root/'arms.json');arms[name]=entry['arm'];arms[name+'_nop']=entry['nop'];b.save(root/'arms.json',arms)
    b.save(root/'same_line_encoding_validation.json',dict(valid=True,disabled_hints=3,remaining_hints=20,checks=checks,
        footprint_note='Binary size and code layout unchanged; this isolates issuance, not code-size removal.'))
    digest=b.sha(__file__);(root/'source_versions'/(digest+'.py')).write_bytes(Path(__file__).read_bytes())


def finish(root,wait_parent):
    if wait_parent:
        while not (root/'measurement_complete.json').exists():
            log=root/'driver_resumed.log'
            assert not log.exists() or 'Traceback' not in log.read_text(),'Parent measurement failed; do not build during unresolved timing'
            time.sleep(10)
    prepare(root)
    scripts=Path(__file__).parent.resolve();name='full_rpc_worker_pruned';arms=load(root/'arms.json')
    smoke=root/('smoke_'+name+'.json')
    b.save(smoke,dict(arms[name],root=str(root),out=str(root/'smoke'/name),seed=1041791))
    run(root,'smoke_'+name,['python3',scripts/'rpc_route_followup.py','platform_smoke',smoke])
    assert load(root/'smoke'/name/'result.json')['valid']
    setting=load(root/'same_line_predeclared.json');names=setting['arms']
    spec=dict(root=str(root),out=str(root/'same_line'),blocks=setting['blocks'],orders=setting['orders'],
        arms={n:dict(arms[n],controls=[c for c in names if c!=n]) for n in names},
        seedbase=setting['seedbase'],order_seed=1041800,trial_script=str(scripts/'temporal_path_trial.py'),
        scope='Fresh, separate equal-layout three-hint ablation. Do not pool with preceding confirmation.',
        predeclared=str(root/'same_line_predeclared.json'))
    path=root/'same_line_spec.json';b.save(path,spec)
    run(root,'same_line',['python3',scripts/'temporal_path_campaign.py','campaign',path])
    assert load(root/'same_line/complete.json')['valid']
    complete=load(root/'measurement_complete.json');complete.update(epoch=time.time(),clean_trials=35,smoke_trials=6,same_line_trials=6)
    b.save(root/'measurement_complete.json',complete)
    b.save(root/'same_line_complete.json',dict(valid=True,epoch=time.time(),trials=6))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--wait-parent',action='store_true')
    args=parser.parse_args();finish(args.root,args.wait_parent)
