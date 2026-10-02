#!/usr/bin/env python3
"""Rebuild only active RPC hints, retaining target/phase and incumbent code."""
import argparse
import copy
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load
import call_stub_prefetch as stubs
from rpc_predict_run import campaign, run, SCRIPTS
from temporal_path_confirm import cleanup, select


def prepare(root):
    assert load(root/'measurement_complete.json')['valid']
    assert (root/'lean_compaction_amendment.json').exists()
    b.space(root);arms=load(root/'arms.json');nominee=load(root/'screen_decision.json')['nominee']
    arm=copy.deepcopy(arms[nominee]);nop=copy.deepcopy(arm);builds={};total_restored=0
    for service,source in arms[nominee]['overrides'].items():
        b.space(root);source=Path(source);record=load(Path(str(source)+'.json'))
        active={h['va'] for h in record['hints']};omitted=[];calls=[]
        for patch in record['patches']:
            targets=[target for rank,target in enumerate(patch['targets']) if patch['stub']+7*rank in active]
            if targets:calls.append(dict(site=patch['site'],callee=patch['callee'],expected=patch['expected'],targets=targets))
            else:omitted.append(patch['site'])
        total_restored+=len(omitted)
        assert sum(len(p['targets']) for p in calls)==len(record['hints'])
        incumbent=Path(arms['full']['overrides'][service]);plan=dict(sha256=b.sha(incumbent),calls=calls)
        output=root/'builds'/'lean'/service/source.name;twin=Path(str(output)+'.nop')
        b.save(root/'plans'/'lean'/(service+'.json'),dict(source=str(incumbent),plan=plan,nominee=nominee,
            omitted_inactive_sites=omitted,removed_inactive_hint_slots=len(record['all_new_hint_slots'])-len(active)))
        built=stubs.build(incumbent,plan,output)
        after=stubs.Elf(output.read_bytes())
        for hint in load(Path(str(incumbent)+'.json'))['hints']:
            instruction=bytes.fromhex(hint['original']);offset=after.offset(hint['va'],len(instruction),True)
            assert after.data[offset:offset+len(instruction)]==instruction
        assert {p['site']:p['targets'] for p in built['patches']}=={p['site']:p['targets'] for p in calls}
        meta=dict(built,omitted_inactive_calls=omitted,
            timing_pair_source=str(source),timing_pair_sha256=b.sha(source),variant='lean',nop_path=str(twin))
        b.save(Path(str(output)+'.json'),meta)
        b.save(Path(str(twin)+'.json'),dict(meta,sha256=b.sha(twin),hints=[],variant='lean_nop'))
        arm['overrides'][service]=str(output);nop['overrides'][service]=str(twin)
        builds[service]=dict(binary=str(output),sha256=b.sha(output),nop=str(twin),nop_sha256=b.sha(twin),
            omitted_sites=len(omitted),active_hints=len(built['hints']),per_site_hint_slots=sum(len(p['targets']) for p in calls),
            old_extra_instruction_bytes=record['extra_instruction_bytes'],
            extra_instruction_bytes=built['extra_instruction_bytes'])
    arms.update(lean=arm,lean_nop=nop);b.save(root/'arms.json',arms)
    prepared=load(root/'prepared_candidates.json');prepared['lean']=dict(arm=arm,nop=nop,builds=builds)
    b.save(root/'prepared_candidates.json',prepared)
    result=dict(valid=True,nominee=nominee,restored_sites=total_restored,builds=builds,epoch=time.time(),source_sha256=b.sha(__file__),
        interpretation='Only active hints rebuilt on intact incumbent: same target list, relative target order and RPC phase. Inactive sites and disabled slots are omitted. Appended stub addresses/layout change; all preexisting code and hint addresses are preserved. Fresh exact-layout NOP twin controls the compact build; do not pool its results with the timing-pair build.')
    b.save(root/'lean_prepared.json',result)
    print(result)


def measure(root):
    assert load(root/'lean_prepared.json')['valid'];arms=load(root/'arms.json')
    run(root,'wide_prepare',['python3',SCRIPTS/'rpc_predict_wide.py',root]);arms=load(root/'arms.json')
    run(root,'reply_prepare',['python3',SCRIPTS/'rpc_predict_reply.py',root]);arms=load(root/'arms.json')
    run(root,'reply_it0_prepare',['python3',SCRIPTS/'rpc_predict_reply_it0.py',root]);arms=load(root/'arms.json')
    for index,name in enumerate(('lean','lean_nop','wide','wide_nop','reply','reply_nop','reply_it0')):
        spec=root/('smoke_'+name+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'smoke'/name),seed=1020501+index))
        run(root,'smoke_'+name,['python3',SCRIPTS/'rpc_route_followup.py','platform_smoke',spec])
        assert load(root/'smoke'/name/'result.json')['valid']
    # Timing pairs have finished all required captures. Retire their generated
    # executables immediately; keep their patches, measurements and source.
    cleanup(root,['early','late','split','nop'],[arms[n] for n in ('full','original','lean','lean_nop','wide','wide_nop','reply','reply_nop','reply_it0')], 'timing_pair_cleanup.json')
    names=['full','lean','wide','reply','reply_it0'];orders=[]
    for offset in (0,2):
        order=names[offset:]+names[:offset];orders.extend([order,list(reversed(order))])
    assert all(sum(order.index(n) for order in orders)==8 for n in names)
    campaign(root,'coverage_screen',arms,names,4,1020601,orders=orders)
    decision=select(load(root/'coverage_screen/rows.json'),'full',['lean','wide','reply','reply_it0'],4)
    nominee=max(decision['eligible'] or ['lean','wide','reply','reply_it0'],key=lambda n:decision['means'][n]['geometric_rps'])
    decision.update(nominee=nominee,promoted=False,epoch=time.time(),blocks=6)
    b.save(root/'production_selection.json',decision)
    # Extract residual evidence before retiring the rejected implementation.
    for name in ('lean','wide','reply','reply_it0'):
        spec=root/('profile_'+name+'.json')
        b.save(spec,dict(arms[name],root=str(root),out=str(root/'profiles'/name),services=list(arms[name]['overrides']),
            kinds=['l2'],capture_s=8,seed=1020401,phase='coverage',arm=name))
        run(root,'profile_'+name,['python3',SCRIPTS/'temporal_path_study.py','platform_capture',spec])
        assert load(root/'profiles'/name/'complete.json')['valid']
    run(root,'coverage_residual_analysis',['python3',SCRIPTS/'rpc_predict_analysis.py',root])
    cleanup(root,[n for n in ('lean','wide','reply','reply_it0') if n!=nominee],
        [arms[n] for n in ('full','original',nominee,nominee+'_nop')], 'coverage_screen_cleanup.json')
    names=['original','full',nominee,nominee+'_nop'];orders=[]
    for offset in range(3):
        order=names[offset:]+names[:offset];orders.extend([order,list(reversed(order))])
    assert all(sum(order.index(n) for order in orders)==9 for n in names)
    campaign(root,'production_confirmation',arms,names,6,1020801,orders=orders)
    b.save(root/'production_complete.json',dict(valid=True,epoch=time.time(),trials=24,nominee=nominee))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','measure']);parser.add_argument('root',type=Path)
    args=parser.parse_args();globals()[args.action](args.root)
