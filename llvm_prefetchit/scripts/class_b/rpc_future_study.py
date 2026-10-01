#!/usr/bin/env python3
"""Main-ELF-only ablation and RPC-type/live-vtable future code experiments."""
import argparse
import bisect
import collections
import copy
import json
from pathlib import Path
import re
import subprocess
import time

import dense_build as b
from dense_cause_analysis import Code
import call_stub_prefetch as stubs
from temporal_path_analysis import read

PRIOR=Path('/storage/prefetchit/class_b_temporal_20261001')


def inventory(root):
    root.mkdir(parents=True,exist_ok=True);b.space(root)
    assert not (root/'prepared_candidates.json').exists()
    (root/'source_versions').mkdir(exist_ok=True)
    original=json.loads((PRIOR/'arms.json').read_text())['original']
    previous=json.loads((PRIOR/'prepared_candidates.json').read_text())['pathwide_shared_anchor']
    b.save(root/'references.json',dict(original=original,previous=previous,prior=str(PRIOR)))
    result={}
    for key,path in original['overrides'].items():
        code=Code(Path(path));rows=[];omitted=[]
        raw=subprocess.check_output(['nm','-S','--defined-only',path],text=True)
        symbols=[v for line in raw.splitlines() if len(v:=line.split())==4 and v[2] in 'TtWw']
        names=subprocess.check_output(['c++filt'],input='\n'.join(v[3] for v in symbols)+'\n',text=True).splitlines()
        syms=[dict(va=int(v[0],16),size=int(v[1],16),symbol=v[3],name=n) for v,n in zip(symbols,names)]
        service=Path(path).name
        for proc in syms:
            match=re.match(r'media_service::'+service+r'Processor::process_(\w+)\(',proc['name'])
            if not match:continue
            method=match[1]
            handler=[s for s in syms if re.match(r'media_service::\w+Handler::'+method+r'\(',s['name'])]
            if len(handler)!=1:
                omitted.append(dict(method=method,reason='No unique concrete main-ELF handler',handlers=handler));continue
            ins=[(ip,code.get(ip)[1]) for ip in code.addresses if proc['va']<=ip<proc['va']+proc['size']]
            args=[(ip,asm) for ip,asm in ins if 'call' in asm and service+'_'+method+'_args4read' in asm]
            if len(args)!=1:
                omitted.append(dict(method=method,reason='No unique direct args.read',calls=args));continue
            site=args[0][0];before=[(ip,asm) for ip,asm in ins if ip<site]
            bases=[(ip,m[1]) for ip,asm in before if (m:=re.fullmatch(r'mov\s+%rdi,%((?:r1[2-5])|rbx|rbp)',asm))]
            chains=[]
            for assigned,reg in bases:
                if any(re.search(r',%'+reg+r'\s*$',asm) for ip,asm in before if ip>assigned):continue
                for i,(ip,asm) in enumerate(ins):
                    if ip<=site or not re.fullmatch(r'mov\s+0x18\(%'+reg+r'\),%rdi',asm):continue
                    following=ins[i+1:i+24]
                    first_call=next(((a,x) for a,x in following if x.startswith('call')),None)
                    assert first_call,(key,method)
                    callip,op=first_call
                    m=re.fullmatch(r'call\s+\*0x([0-9a-f]+)\(%(\w+)\)',op)
                    if m:slot=int(m[1],16);table=m[2]
                    else:
                        indirect=re.fullmatch(r'call\s+\*%(\w+)',op);assert indirect,(key,method,op)
                        loads=[m for a,x in following if a<callip and (m:=re.fullmatch(r'mov\s+0x([0-9a-f]+)\(%(\w+)\),%'+indirect[1],x))]
                        assert len(loads)==1,(key,method,loads)
                        slot=int(loads[0][1],16);table=loads[0][2]
                    assert any(re.fullmatch(r'mov\s+\(%rdi\),%'+table,x) for a,x in following if a<callip)
                    chains.append(dict(base=reg,offsets=[24,0,slot],handler_call=callip,
                        this_assignment=assigned,iface_load=ip))
            assert len(chains)==1,(key,method,chains)
            record=dict(method=method,processor=proc,handler=handler[0],args_site=site,
                        args_callee=int(re.search(r'call\s+([0-9a-f]+)',args[0][1])[1],16),chain=chains[0])
            # Prefetch only the actual handler's code; rank lines using earlier
            # baseline PEBS, never the clean evaluation request stream.
            sample_path=PRIOR/'profiles/train_native'/key/'l2/observations.json.gz'
            data=read(sample_path);main=data['digests'].index(b.sha(path));counts=collections.Counter()
            lo=handler[0]['va'];hi=lo+handler[0]['size']
            for sample in data['rows']:
                if sample['dso']==main and lo<=sample['ip']<hi:counts[sample['ip']//64]+=1
            entry=[]
            for ip in code.addresses:
                if lo<=ip<hi and (not entry or ip//64!=entry[-1]//64):entry.append(ip)
            targets=entry[:2]
            for line,count in counts.most_common():
                eligible=[ip for ip in entry if ip//64==line]
                if eligible and eligible[0] not in targets:targets.append(eligible[0])
                if len(targets)==8:break
            record.update(static_targets=targets,handler_l2_samples=sum(counts.values()),
                          target_sample_counts={str(t):counts[t//64] for t in targets},
                          training_sha256=b.sha(sample_path),training=str(sample_path))
            rows.append(record)
        assert rows,(key,omitted)
        result[key]=dict(source=path,sha256=b.sha(path),methods=rows,omitted=omitted)
        b.save(root/'rpc_inventory.json',result)
        print(json.dumps(dict(service=key,methods=[dict(method=r['method'],site=hex(r['args_site']),
            chain=r['chain'],handler_samples=r['handler_l2_samples'],targets=len(r['static_targets'])) for r in rows],omitted=omitted)),flush=True)


def prepare(root):
    refs=json.loads((root/'references.json').read_text());previous=refs['previous'];original=refs['original']
    inventory=json.loads((root/'rpc_inventory.json').read_text());prepared={};records={}
    for key,path in dict(original['overrides'],mongo=original['mongo_binary']).items():
        oldpath=previous['arm']['mongo_binary'] if key=='mongo' else previous['arm']['overrides'][key]
        records[key]=json.loads(Path(oldpath+'.json').read_text())
    for name in ('no_dso','rpc_live','rpc_type'):
        arm=copy.deepcopy(original);nop=copy.deepcopy(original);builds={}
        for key,record in records.items():
            b.space(root)
            if key=='mongo' and name!='no_dso':
                arm['mongo_binary']=prepared['no_dso']['arm']['mongo_binary']
                # Incremental NOP disables the RPC bundles. Non-RPC hints,
                # including Mongo, stay enabled; displaced bundles are recorded.
                nop['mongo_binary']=arm['mongo_binary'];continue
            plan=copy.deepcopy(record['plan'])
            plan['calls']=[dict(c,got_targets=[]) for c in plan['calls'] if c['targets']]
            rpc_sites=[]
            if name!='no_dso':
                by_site={c['site']:c for c in plan['calls']}
                source=Path(record['source']);raw=source.read_bytes();elf=stubs.Elf(raw)
                for method in inventory[key]['methods']:
                    site=method['args_site'];offset=elf.offset(site,5,True)
                    # Replace this call's old bundle, recording any displaced
                    # targets. The incremental control keeps that same layout.
                    row=dict(site=site,callee=method['args_callee'],expected=raw[offset:offset+5].hex(),targets=[])
                    if name=='rpc_live':
                        row['runtime_target']=dict(base=method['chain']['base'],offsets=method['chain']['offsets'],addends=[0,64,128,192],
                            live_immutable_chain_proof=dict(source_sha256=record['source_sha256'],method=method['method'],
                                inspected_chain=method['chain'],invariant='Processor owns immutable shared iface throughout args.read and invocation; vtable slot is the exact subsequent handler call.'))
                    else:row['targets']=method['static_targets']
                    rpc_sites.append(dict(site=site,old_bundle=by_site.get(site),method=method['method']))
                    by_site[site]=row
                plan['calls']=sorted(by_site.values(),key=lambda c:c['site'])
            output=root/'builds'/name/key/Path(record['source']).name
            b.save(root/'plans'/name/(key+'.json'),dict(plan=plan,source=record['source'],rpc_sites=rpc_sites,
                rule='No shared-library rewriting or GOT targets; main ELFs only. RPC information is available before args.read.'))
            built=stubs.build(Path(record['source']),plan,output)
            if name!='no_dso':
                raw=bytearray(output.read_bytes());wanted={s['site'] for s in rpc_sites}
                enabled_stubs={p['stub'] for p in built['patches'] if p['site'] in wanted}
                disabled=[]
                for hint in built['hints']:
                    if any(stub<=hint['va']<next(p['terminal_jumps'][0] for p in built['patches'] if p['stub']==stub) for stub in enabled_stubs):
                        raw[hint['offset']:hint['offset']+len(bytes.fromhex(hint['nop']))]=bytes.fromhex(hint['nop']);disabled.append(hint)
                incremental=Path(str(output)+'.rpc_nop');incremental.write_bytes(raw);incremental.chmod(0o755)
                b.save(Path(str(incremental)+'.json'),dict(source=str(output),sha256=b.sha(incremental),disabled_hints=disabled,
                    scope='Only RPC bundles disabled; non-RPC main-ELF and Mongo hints remain enabled. Runtime pointer loads remain. Displaced original RPC bundles are recorded in the plan.'))
                from e2e_lbr import remove_generated
                remove_generated([Path(str(output)+'.nop')],root/'plans'/name/(key+'_unused_all_nop_cleanup.json'),
                    'Use incremental RPC NOP instead; all-hint NOP source/hash/patches retained in binary metadata.')
                nop_path=str(incremental)
            else:nop_path=str(output)+'.nop'
            if key=='mongo':arm['mongo_binary']=str(output);nop['mongo_binary']=nop_path
            else:arm['overrides'][key]=str(output);nop['overrides'][key]=nop_path
            builds[key]=dict(binary=str(output),nop=nop_path,sha256=built['sha256'],nop_sha256=b.sha(nop_path),
                sites=built['call_sites'],hints=len(built['hints']),extra_instruction_bytes=built['extra_instruction_bytes'],rpc_sites=rpc_sites)
            print(json.dumps(dict(stage='build',arm=name,service=key,sites=built['call_sites'],hints=len(built['hints']))),flush=True)
        arm['controls']=['original','no_dso'] if name!='no_dso' else ['original','full_dso']
        prepared[name]=dict(arm=arm,nop=nop,builds=builds)
        b.save(root/'prepared_candidates.json',prepared)
    arms=dict(original=original,full_dso=dict(previous['arm'],controls=['original']))
    arms.update({k:v['arm'] for k,v in prepared.items()})
    b.save(root/'arms.json',arms)


def trace_path(root):
    """Request type plus observed downstream calls, using only prior training."""
    inventory=json.loads((root/'rpc_inventory.json').read_text())
    prepared=json.loads((root/'prepared_candidates.json').read_text());base=prepared['no_dso']
    arm=copy.deepcopy(base['arm']);nop=copy.deepcopy(base['arm']);builds={};selections={}
    for key,info in inventory.items():
        b.space(root);data=read(Path(info['methods'][0]['training']));main=data['digests'].index(info['sha256'])
        record=json.loads(Path(base['builds'][key]['binary']+'.json').read_text());plan=copy.deepcopy(record['plan'])
        by_site={row['site']:row for row in plan['calls']};source=Path(info['source']);elf=stubs.Elf(source.read_bytes());chosen=[]
        for method in info['methods']:
            lo=method['handler']['va'];hi=lo+method['handler']['size'];counts=collections.Counter();addresses={}
            for sample in data['rows']:
                if sample['dso']!=main:continue
                reached=lo<=sample['ip']<hi;age=0
                for sd,fr,td,to,pred,cycles,kind in sample['edges']:
                    if sd==main and lo<=fr<hi and 64<=age<=8192:reached=True;break
                    if cycles is None or cycles>=65535:break
                    age+=cycles
                    if age>8192:break
                if reached:
                    line=sample['ip']//64;counts[line]+=1;addresses[line]=min(addresses.get(line,sample['ip']),sample['ip'])
            targets=method['static_targets'][:2]
            for line,n in counts.most_common():
                if n<3:break
                if all(t//64!=line for t in targets):targets.append(addresses[line])
                if len(targets)==8:break
            site=method['args_site'];off=elf.offset(site,5,True)
            chosen.append(dict(method=method['method'],site=site,targets=targets,supported_samples=sum(counts.values()),
                target_samples={str(t):counts[t//64] for t in targets},old_bundle=by_site.get(site)))
            by_site[site]=dict(site=site,callee=method['args_callee'],expected=elf.data[off:off+5].hex(),targets=targets)
        plan['calls']=sorted(by_site.values(),key=lambda c:c['site']);output=root/'builds/rpc_trace'/key/source.name
        b.save(root/'plans/rpc_trace'/(key+'.json'),dict(plan=plan,choices=chosen,training=info['methods'][0]['training'],
            training_sha256=info['methods'][0]['training_sha256'],
            rule='Two handler entry lines plus up to six main-ELF miss lines observed inside the handler or after its branch in bounded LBR at 64..8192 completed-branch cycles; at least three training samples. A bounded path association is not a complete call graph or a fetch-lead measurement.'))
        built=stubs.build(source,plan,output);raw=bytearray(output.read_bytes());sites={c['site'] for c in chosen}
        ranges=[(p['stub'],p['terminal_jumps'][0]) for p in built['patches'] if p['site'] in sites];disabled=[]
        for hint in built['hints']:
            if any(lo<=hint['va']<hi for lo,hi in ranges):
                raw[hint['offset']:hint['offset']+len(bytes.fromhex(hint['nop']))]=bytes.fromhex(hint['nop']);disabled.append(hint)
        twin=Path(str(output)+'.rpc_nop');twin.write_bytes(raw);twin.chmod(0o755)
        b.save(Path(str(twin)+'.json'),dict(source=str(output),sha256=b.sha(twin),disabled_hints=disabled,
            scope='RPC bundles disabled; all other no-DSO hints remain. Displaced old RPC bundles are recorded.'))
        from e2e_lbr import remove_generated
        remove_generated([Path(str(output)+'.nop')],root/'plans/rpc_trace'/(key+'_unused_all_nop_cleanup.json'),'Unused all-hint NOP superseded by incremental RPC NOP; hashes retained.')
        arm['overrides'][key]=str(output);nop['overrides'][key]=str(twin)
        builds[key]=dict(binary=str(output),nop=str(twin),sha256=built['sha256'],nop_sha256=b.sha(twin),sites=built['call_sites'],
            hints=len(built['hints']),extra_instruction_bytes=built['extra_instruction_bytes'],rpc_sites=chosen)
        selections[key]=chosen
    arm['controls']=['original','no_dso','rpc_type'];prepared['rpc_trace']=dict(arm=arm,nop=nop,builds=builds)
    b.save(root/'prepared_candidates.json',prepared);b.save(root/'trace_selection.json',selections)
    arms=json.loads((root/'arms.json').read_text());arms['rpc_trace']=arm;b.save(root/'arms.json',arms)


def smoke(spec):
    import balanced_backend as balanced
    import fullset as h
    import media_system_study as system
    from backend_prefetch import bind_mongodb,audit_backends
    from media_library_study import audit_libraries
    system.configure();out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(spec,purpose='Functional validation and original DSO hash audit; never a speedup trial.'))
    stack=client=None
    try:
        with bind_mongodb(out,spec['mongo_binary']):stack=h.start(out,'media',spec['overrides'],8)
        system.audit_native(stack,out,spec['overrides']);audit_backends(stack,out,spec['mongo_binary'])
        previous=json.loads((Path(spec['root'])/'references.json').read_text())['previous']['arm']
        originals={key:{target:json.loads(Path(source+'.json').read_text())['source'] for target,source in libs.items()}
                   for key,libs in previous['libraries'].items()}
        audit_libraries(stack,out,dict(libraries=originals))
        client=balanced.start_client(out,20,spec['seed'],warmup=5)
        assert client.wait(timeout=90)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text())
        assert info['mapping_preserved'] and not info['steady_errors'] and info['completed']>100
        b.save(out/'result.json',dict(valid=True,load=info,original_dsos_verified=True))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['inventory','prepare','trace_path','smoke','platform_smoke']);p.add_argument('root',type=Path);a=p.parse_args()
    if a.action=='platform_smoke':
        import fullset as h
        spec=json.loads(a.root.read_text());h.platform(Path(spec['out']),['python3',__file__,'smoke',str(a.root)])
    elif a.action=='smoke':smoke(json.loads(a.root.read_text()))
    else:globals()[a.action](a.root)
