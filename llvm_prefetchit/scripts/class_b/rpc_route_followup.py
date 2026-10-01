#!/usr/bin/env python3
"""Combine typed-worker hints with the incumbent and diagnose modified services."""
import argparse
import copy
import json
from pathlib import Path
import signal
import struct
import time

import dense_build as b
from rpc_route_study import load
import call_stub_prefetch as stubs


def combine(root, choice):
    assert choice in ('rpc_worker', 'rpc_worker_it0')
    b.space(root)
    prepared = load(root/'prepared_candidates.json')
    arms = load(root/'arms.json')
    worker = prepared['rpc_worker']
    full = arms['full_dso']
    name = 'full_'+choice
    assert name not in prepared
    arm, nop, builds = copy.deepcopy(full), copy.deepcopy(full), {}
    for service, row in worker['builds'].items():
        b.space(root)
        source = Path(full['overrides'][service])
        old = load(Path(str(source)+'.json'))
        raw = source.read_bytes();elf = stubs.Elf(raw)
        prior = {p['site']:p for p in old['patches']}
        calls = []
        for selected in row['selections']:
            site = selected['site'];offset = elf.offset(site,5,True)
            assert raw[offset] == 0xe8
            patch = prior.get(site,{})
            assert len(patch.get('targets',[]))+len(patch.get('got_targets',[]))+len(selected['targets']) <= 8
            assert all(t//64 not in {v//64 for v in patch.get('targets',[])} for t in selected['targets'])
            calls.append(dict(site=site,callee=site+5+struct.unpack_from('<i',raw,offset+1)[0],
                              expected=raw[offset:offset+5].hex(),targets=selected['targets']))
        plan = dict(sha256=b.sha(source),calls=calls)
        output = root/'builds'/name/service/source.name
        built = stubs.build(source,plan,output)
        changes = []
        if choice.endswith('_it0'):
            data = bytearray(output.read_bytes())
            for hint in built['hints']:
                instruction = bytes.fromhex(hint['original']);offset = hint['offset']
                assert instruction[:3] == bytes.fromhex('0f1815') and data[offset:offset+7] == instruction
                replacement = bytes.fromhex('0f183d')+instruction[3:]
                data[offset:offset+7] = replacement
                changes.append(dict(offset=offset,old=instruction.hex(),new=replacement.hex()))
                hint.update(original=replacement.hex(),kind='it0')
            output.write_bytes(data)
            built['sha256'] = b.sha(output)
            built['it0_opcode_changes'] = changes
            b.save(Path(str(output)+'.json'),built)
        after = stubs.Elf(output.read_bytes())
        for hint in old['hints']:
            instruction = bytes.fromhex(hint['original']);offset = after.offset(hint['va'],len(instruction),True)
            assert after.data[offset:offset+len(instruction)] == instruction
        arm['overrides'][service] = str(output);nop['overrides'][service] = str(output)+'.nop'
        builds[service] = dict(binary=str(output),nop=str(output)+'.nop',sha256=b.sha(output),
            nop_sha256=b.sha(str(output)+'.nop'),sites=built['call_sites'],hints=len(built['hints']),
            extra_instruction_bytes=built['extra_instruction_bytes'],preserved_previous_hints=len(old['hints']),
            selections=row['selections'],it0_hints=len(changes))
        b.save(root/'plans'/name/(service+'.json'),dict(plan=plan,source=str(source),
            opcode_changes=changes,source_worker_policy=choice,source_sha256=b.sha(__file__),
            rule='Same 23 typed-worker future targets on the intact full incumbent. Keep every earlier local/GOT hint and address.'))
    arm['controls'] = ['original','full_dso','no_dso',choice,name+'_nop']
    nop['controls'] = ['full_dso']
    prepared[name] = dict(arm=arm,nop=nop,builds=builds,worker_policy=choice)
    arms[name] = arm;arms[name+'_nop'] = nop
    b.save(root/'prepared_candidates.json',prepared);b.save(root/'arms.json',arms)
    digest = b.sha(__file__)
    (root/'source_versions'/(digest+'.py')).write_bytes(Path(__file__).read_bytes())
    b.save(root/'combined_prepared.json',dict(name=name,worker_policy=choice,epoch=time.time(),
        sites=sum(v['sites'] for v in builds.values()),hints=sum(v['hints'] for v in builds.values()),
        extra_code_bytes=sum(v['extra_instruction_bytes'] for v in builds.values()),
        preservation='All old app hints, DSO hints, Mongo policy and their original addresses preserved.'))
    print(json.dumps(load(root/'combined_prepared.json')),flush=True)


def smoke(spec):
    import balanced_backend as balanced
    import fullset as h
    import media_system_study as system
    from backend_prefetch import bind_mongodb,audit_backends
    from media_library_study import bind_libraries,audit_libraries
    system.configure();out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(spec,purpose='Combined-policy functional smoke and loaded binary/library hash audit; no timing claim.'))
    stack=client=None
    try:
        with bind_libraries(out,spec),bind_mongodb(out,spec['mongo_binary']):
            stack=h.start(out,'media',spec['overrides'],8)
        system.audit_native(stack,out,spec['overrides']);audit_backends(stack,out,spec['mongo_binary'])
        audit_libraries(stack,out,spec)
        client=balanced.start_client(out,20,spec['seed'],warmup=5)
        assert client.wait(timeout=90)==0;client=None;stack.check()
        info=load(out/'load/load.json')
        assert info['mapping_preserved'] and not info['steady_errors'] and info['completed']>100
        b.save(out/'result.json',dict(valid=True,load=info,libraries_verified=True))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)


def diagnostic_trial(spec):
    import backend_study
    import media_system_study as system
    import split_hybrid_study as diagnostic
    from media_library_study import bind_libraries
    system.configure();system.audited_start(spec)
    diagnostic.MONITORED={k:v for k,v in system.MONITORED.items() if k in ('movie','compose','rating')}
    assert len(diagnostic.MONITORED)==3
    diagnostic.EVENTS.update(translation='cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_L1,config1=0x12/u,'
        'cpu/event=0x11,umask=0x10,cmask=1,name=ITLB_WALK_ACTIVE/u,'
        'cpu/event=0x12,umask=0xe,name=DTLB_LOAD_WALKS/u,cpu/event=0x13,umask=0xe,name=DTLB_STORE_WALKS/u',
        prefetch=backend_study.EVENTS['prefetch'])
    setting=dict(spec,diagnostic_roi_s=5,service_event_sets=['cache','translation','topdown','prefetch'],
        purpose='Separate PMU for the three modified app services; pool counters include entire workload. No endpoint inference.')
    with bind_libraries(Path(spec['out']),setting):diagnostic.trial(setting)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['combine','smoke','platform_smoke','diagnostic_trial','platform_diagnostic'])
    parser.add_argument('path',type=Path);parser.add_argument('--choice',choices=['rpc_worker','rpc_worker_it0']);a=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if a.action=='combine':combine(a.path,a.choice)
    elif a.action.startswith('platform_'):
        import fullset as h
        spec=load(a.path);action='smoke' if a.action=='platform_smoke' else 'diagnostic_trial'
        h.platform(Path(spec['out']),['python3',__file__,action,str(a.path)])
    else:globals()[a.action](load(a.path))
