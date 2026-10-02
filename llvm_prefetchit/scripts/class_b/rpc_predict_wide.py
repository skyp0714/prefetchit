#!/usr/bin/env python3
"""Widen the same RPC-conditioned training policy to sixteen distinct lines."""
import argparse
import bisect
import collections
import copy
from pathlib import Path
import struct
import time

import dense_build as b
from dense_cause_analysis import Code
import call_stub_prefetch as stubs
from rpc_route_study import load
from temporal_path_analysis import read


def prepare(root,span=False):
    assert (root/'wide_predeclared.json').exists()
    if span:assert (root/'straddle_amendment.json').exists()
    variant='wide_span' if span else 'wide'
    assert load(root/'measurement_complete.json')['valid']
    arms=load(root/'arms.json');inventory=load(root/'rpc_inventory.json');old_model=load(root/'model.json')
    base=arms['full'];arm=copy.deepcopy(base);nop=copy.deepcopy(base);builds={};model={}
    for service,info in inventory.items():
        b.space(root);source=Path(base['overrides'][service]);code=Code(Path(info['source']));emitted=Code(source)
        old=load(Path(str(source)+'.json'));raw=source.read_bytes();elf=stubs.Elf(raw)
        ranges=sorted((p['stub'],max(p['terminal_jumps'])+5,p['site']) for p in old['patches']);starts=[r[0] for r in ranges]
        contexts={};pre_functions=set();anchors={c['method']:c for c in old_model[service]['choices']}
        for method in info['methods']:
            for key in ('handler','processor'):contexts[code.get(method[key]['va'])[2]]=method['method']
            pre_functions.update([code.get(method['args_callee'])[2],code.get(method['processor']['va'])[2]])
        def origin(ip):
            i=bisect.bisect_right(starts,ip)-1
            return (ranges[i][2],True) if i>=0 and ip<ranges[i][1] else (ip,False)
        def context(ip):return contexts.get(code.get(origin(ip)[0])[2])
        trace=Path(old_model[service]['training']);assert b.sha(trace)==old_model[service]['training_sha256']
        data=read(trace);main=data['digests'].index(old['sha256'])
        targeted={t//64 for p in old['patches'] for t in p['targets']};counts=collections.defaultdict(collections.Counter)
        addresses={};kinds={};geometry=collections.Counter()
        for row in data['rows']:
            if row['dso']!=main:continue
            ip=row['ip'];mapped,is_stub=origin(ip);fn=code.get(mapped)[2]
            if not emitted.get(ip)[0] or fn in pre_functions:continue
            label=context(ip)
            if label is None:
                for sd,fr,td,to,*_ in row['edges']:
                    label=context(fr) if sd==main else None
                    if label is None and td==main:label=context(to)
                    if label is not None:break
            if label not in anchors:continue
            a=anchors[label];target=ip;length=emitted.get(ip)[0]
            geometry['associated_samples']+=1
            if ip//64!=(ip+length-1)//64:
                geometry['straddling_samples']+=1
                if emitted.get(ip+length)[0]:
                    geometry['continuation_decoded_samples']+=1
                    if span:target=ip+length
                else:geometry['no_decoded_continuation_samples']+=1
            line=target//64
            issuing={a['early']//64,a['late']//64}
            if span:issuing.update({(a['early']+4)//64,(a['late']+4)//64})
            if line in targeted or line in issuing:continue
            if fn==code.get(a['handler'])[2] and mapped<a['late']:continue
            counts[label][line]+=1;addresses[line]=min(addresses.get(line,target),target)
            kinds[line]='incumbent_stub' if is_stub else 'original_main'
        choices=[];calls=[]
        for method,anchor in anchors.items():
            selected=[(line,n) for line,n in counts[method].most_common() if n>=3][:16]
            targets=[addresses[line] for line,n in selected]
            if not span:
                count=len(anchor['targets'])
                assert [t//64 for t in targets[:count]]==[t//64 for t in anchor['targets']],(service,method,'Training prefix changed')
                # Preserve exact frozen instruction addresses for the common prefix.
                targets[:count]=anchor['targets']
            choices.append(dict(method=method,early=anchor['early'],late=anchor['late'],targets=targets,
                counts=[n for line,n in selected],kinds=[kinds[line] for line,n in selected]))
            for parity,phase in enumerate(('early','late')):
                phase_targets=targets[parity::2]
                if not phase_targets:continue
                site=anchor[phase];offset=elf.offset(site,5,True);assert raw[offset]==0xe8
                calls.append(dict(site=site,callee=site+5+struct.unpack_from('<i',raw,offset+1)[0],
                    expected=raw[offset:offset+5].hex(),targets=phase_targets))
        model[service]=dict(training=str(trace),training_sha256=b.sha(trace),choices=choices,geometry=dict(geometry),
            target_rule='Decoded continuation instruction for straddling IPs; otherwise sampled IP' if span else 'Sampled starting IP; frozen prefix retained')
        if not calls:continue
        plan=dict(sha256=b.sha(source),calls=calls);output=root/'builds'/variant/service/source.name
        b.save(root/'plans'/variant/(service+'.json'),dict(source=str(source),plan=plan,choices=choices))
        built=stubs.build(source,plan,output)
        after=stubs.Elf(output.read_bytes())
        for hint in old['hints']:
            instruction=bytes.fromhex(hint['original']);offset=after.offset(hint['va'],len(instruction),True)
            assert after.data[offset:offset+len(instruction)]==instruction
        twin=Path(str(output)+'.nop');built.update(variant=variant,nop_path=str(twin))
        b.save(Path(str(output)+'.json'),built)
        b.save(Path(str(twin)+'.json'),dict(built,sha256=b.sha(twin),hints=[],variant=variant+'_nop'))
        arm['overrides'][service]=str(output);nop['overrides'][service]=str(twin)
        builds[service]=dict(binary=str(output),sha256=b.sha(output),nop=str(twin),nop_sha256=b.sha(twin),
            active_hints=len(built['hints']),extra_instruction_bytes=built['extra_instruction_bytes'])
        print(service,len(built['hints']),flush=True)
    assert builds,'No usable continuation-aware targets'
    arms.update({variant:arm,variant+'_nop':nop});b.save(root/'arms.json',arms)
    prepared=load(root/'prepared_candidates.json');prepared[variant]=dict(arm=arm,nop=nop,builds=builds)
    b.save(root/'prepared_candidates.json',prepared);b.save(root/(variant+'_model.json'),model)
    b.save(root/(variant+'_prepared.json'),dict(valid=True,builds=builds,epoch=time.time(),source_sha256=b.sha(__file__)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--span',action='store_true')
    args=parser.parse_args();prepare(args.root,args.span)
