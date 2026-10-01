#!/usr/bin/env python3
"""Fresh-stack clean endpoint screens for frozen temporal/call-path policies."""
import argparse
import collections
import json
import os
from pathlib import Path
import random
import signal
import struct
import time

import balanced_backend as balanced
from backend_prefetch import bind_mongodb,audit_backends
import dense_build as b
import fullset as h
from fullset_study import summarize
from media_library_study import bind_libraries,audit_libraries
import media_system_study as system
from mechanism_report import evaluate
from temporal_path_study import catalog_process


def audit_got_targets(root,out,stack,spec):
    """Check loaded anchors under ASLR after warmup, outside all timed ROIs."""
    prepared=json.loads((root/'prepared_candidates.json').read_text())[spec['candidate']]
    records={}
    for digest,entry in prepared['builds'].items():
        record=json.loads(Path(entry['binary']+'.json').read_text());records[entry['sha256']]=record
    checks=[];summary=collections.Counter()
    services=dict(system.NATIVE)
    for key,name in system.MONGO.items():services[key]=(name,'mongod','32-39')
    for key,(name,_,_) in services.items():
        pid=stack.states[name]['State']['Pid'];folder=out/'got_audit'/key;folder.mkdir(parents=True)
        catalog=catalog_process(pid,root,folder)
        by_original={};by_sha={}
        for path,entry in catalog.items():
            record=records.get(entry['sha256']);origin=record['source_sha256'] if record else entry['sha256']
            by_original[origin]=(path,entry);by_sha[entry['sha256']]=(path,entry)
        with Path(f'/proc/{pid}/mem').open('rb',buffering=0) as memory:
            for digest,(path,entry) in by_sha.items():
                if digest not in records:continue
                record=records[digest];biases={m['bias'] for m in entry['mappings']};assert len(biases)==1
                bias=next(iter(biases));seen=set()
                for patch in record['patches']:
                    for target in patch.get('got_targets',[]):
                        token=(target['got'],target['target_sha'],target['anchor'])
                        if token in seen:continue
                        seen.add(token);memory.seek(bias+target['got']);value=struct.unpack('<Q',memory.read(8))[0]
                        assert target['target_sha'] in by_original,(key,path,target)
                        target_path,target_entry=by_original[target['target_sha']]
                        target_bias={m['bias'] for m in target_entry['mappings']};assert len(target_bias)==1
                        expected=next(iter(target_bias))+target['anchor']
                        if value==expected:state='resolved_expected'
                        elif any(m['start']<=value<m['end'] for m in entry['mappings']):state='unresolved_in_source_image'
                        else:state='unexpected_target'
                        summary[state]+=1;checks.append(dict(service=key,source=path,got=target['got'],target=target_path,
                            anchor=target['anchor'],observed=value,expected=expected,state=state))
    b.save(out/'got_runtime_validation.json',dict(summary=dict(summary),checks=checks,
        limitation='Snapshot after smoke warmup. Lazy slots still pointing into the source image may not warm the intended target until first resolution; counted explicitly. No validation reads occur in endpoint timing.'))
    assert not summary['unexpected_target'],summary
    assert summary['resolved_expected']>0,summary


def smoke(spec):
    system.configure();out=Path(spec['out']);root=Path(spec['root']);out.mkdir(parents=True,exist_ok=False);b.space(root)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),purpose='Functional smoke and GOT address audit only'))
    stack=client=None
    try:
        with bind_libraries(out,spec),bind_mongodb(out,spec['mongo_binary']):stack=h.start(out,'media',spec['overrides'],8)
        system.audit_native(stack,out,spec['overrides']);audit_backends(stack,out,spec['mongo_binary'])
        if spec.get('libraries'):audit_libraries(stack,out,spec)
        client=balanced.start_client(out,35,spec['seed'],warmup=5);time.sleep(7)
        audit_got_targets(root,out,stack,spec)
        assert client.wait(timeout=90)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text())
        assert info['mapping_preserved'] and not info['steady_errors'] and info['completed']>100
        b.save(out/'result.json',dict(valid=True,load=info))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)


def campaign(spec):
    root=Path(spec['root']);out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(root)
    names=list(spec['arms']);arms=spec['arms']
    source_files=[Path(__file__),Path(system.__file__),Path(balanced.__file__),Path(h.__file__)]
    source_files += [Path(__file__).with_name(name) for name in ('backend_study.py','backend_prefetch.py',
        'media_library_study.py','balanced_load.py')]
    source_files.append(h.HARNESS/'run_platform.py')
    source_hashes={str(path):b.sha(path) for path in source_files}
    for path in source_files:
        saved=root/'source_versions'/(source_hashes[str(path)]+'.py')
        if not saved.exists():saved.write_bytes(path.read_bytes())
    binaries=set()
    for arm in arms.values():
        binaries.update(arm['overrides'].values());binaries.add(arm['mongo_binary'])
        for libraries in arm.get('libraries',{}).values():binaries.update(libraries.values())
    binary_hashes={path:b.sha(path) for path in binaries}
    for name,arm in arms.items():arm['controls']=[c for c in arm.get('controls',[]) if c in arms and c!=name]
    orders=spec.get('orders')
    if orders is None:
        rng=random.Random(spec['order_seed']);base=names[:];rng.shuffle(base)
        orders=[]
        for block in range(spec['blocks']):
            order=base[block%len(base):]+base[:block%len(base)]
            if block//len(base)%2:order.reverse()
            orders.append(order)
    assert len(orders)==spec['blocks'] and all(sorted(o)==sorted(names) for o in orders)
    b.save(out/'protocol.json',dict(spec,orders=orders,monitored=system.MONITORED,source_sha256=b.sha(__file__),
        source_hashes=source_hashes,binary_hashes=binary_hashes,
        endpoint='Balanced C4, full Media compose-review, fresh data/stack per trial, 50s warmup and 60s clean ROI, no profiling.',
        analysis='Paired log ratios with individual t95 intervals. Exploratory screens and independent confirmations stay separate. No performance-based exclusions/retries.'))
    rows=[]
    for block,order in enumerate(orders):
        for name in order:
            assert all(b.sha(path)==digest for path,digest in source_hashes.items()),'Timing harness changed during frozen campaign'
            b.space(root);dest=out/f'{block:02d}_{name}';manifest=dest.with_suffix('.json')
            b.save(manifest,dict(arms[name],out=str(dest),seed=spec['seedbase']+block))
            h.platform(dest,['python3',Path(system.__file__),'trial',manifest])
            result=json.loads((dest/'result.json').read_text());assert result['valid']
            row=dict(block=block,arm=name,valid=True,output=str(dest),achieved_rps=result['pool']['achieved_rps'],pool_util_pct=result['pool_util_pct'],
                metrics=dict(mean_ms=result['pool']['mean_ms'],p99_ms=result['pool']['p99_ms'],stack_cpu=result['whole_stack_cpu_us_per_request'],inverse_rps=1/result['pool']['achieved_rps']))
            rows.append(row);b.save(out/'rows.json',rows);b.save(out/'summary.json',summarize(rows,arms))
            print(json.dumps(dict(stage='clean_trial_complete',**row)),flush=True)
    b.save(out/'complete.json',dict(valid=True,trials=len(rows)));evaluate(out,out/'evaluation.json')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['smoke','campaign','platform_smoke']);p.add_argument('spec',type=Path);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    spec=json.loads(a.spec.read_text())
    if a.action=='platform_smoke':h.platform(Path(spec['out']),['python3',__file__,'smoke',a.spec])
    else:globals()[a.action](spec)
