#!/usr/bin/env python3
"""Use the known outgoing RPC reply type after its header has been received."""
import argparse
import bisect
import collections
import copy
from pathlib import Path
import re
import struct
import subprocess
import time

import dense_build as b
from dense_cause_analysis import Code, category
import call_stub_prefetch as stubs
from rpc_route_study import load
from temporal_path_analysis import read


def prepare(root):
    assert (root/'reply_predeclared.json').exists();assert load(root/'measurement_complete.json')['valid']
    arms=load(root/'arms.json');inventory=load(root/'rpc_inventory.json');training=load(root/'model.json')
    arm=copy.deepcopy(arms['lean']);nop=copy.deepcopy(arm);builds={};model={}
    for service,info in inventory.items():
        b.space(root);original=Path(info['source']);code=Code(original)
        symbols=[line.split() for line in subprocess.check_output(['nm','-S','--defined-only',original],text=True).splitlines()]
        symbols=[v for v in symbols if len(v)==4 and v[2] in 'TtWw']
        names=subprocess.check_output(['c++filt'],input='\n'.join(v[3] for v in symbols)+'\n',text=True).splitlines()
        names={v[3]:name for v,name in zip(symbols,names)};functions=collections.defaultdict(list)
        for ip,(_,asm,fn) in code.instructions.items():functions[fn].append(ip)
        anchors={};recv_context={};result_context=collections.defaultdict(set)
        for fn,ips in functions.items():
            match=re.match(r'media_service::(\w+Service)Client::recv_(\w+)\(',names.get(fn,''))
            if not match:continue
            candidates=[]
            for ip in ips:
                length,asm,_=code.get(ip)
                if length!=5 or category(asm)!='direct_call':continue
                callee=int(asm.split()[1],16);dest=code.get(callee)[2]
                if '_presult4readE' in dest:candidates.append((ip,callee,dest))
            if len(candidates)!=1:continue
            site,callee,result_fn=candidates[0];label=':'.join(match.groups())
            anchors[label]=dict(site=site,result_callee=callee,recv_function=fn,result_function=result_fn)
            recv_context[fn]=label;result_context[result_fn].add(label)
        if not anchors:model[service]=dict(anchors={},choices=[]);continue
        incumbent=load(Path(arms['full']['overrides'][service]+'.json'))
        ranges=sorted((p['stub'],max(p['terminal_jumps'])+5,p['site']) for p in incumbent['patches']);starts=[v[0] for v in ranges]
        prior_sites={p['site']:p for p in incumbent['patches']}
        def origin(ip):
            i=bisect.bisect_right(starts,ip)-1
            return (ranges[i][2],True) if i>=0 and ip<ranges[i][1] else (ip,False)
        def recv(ip):
            mapped,_=origin(ip);label=recv_context.get(code.get(mapped)[2])
            return (label,mapped>=anchors[label]['site']) if label else None
        trace=Path(training[service]['training']);assert b.sha(trace)==training[service]['training_sha256']
        data=read(trace);main=data['digests'].index(incumbent['sha256'])
        counts=collections.defaultdict(collections.Counter);addresses={};kinds={};quality=collections.Counter()
        for row in data['rows']:
            quality['all']+=1
            if row['dso']!=main:continue
            ip=row['ip'];mapped,is_stub=origin(ip);fn=code.get(mapped)[2]
            if not is_stub and not code.get(ip)[0]:continue
            own=recv(ip);label=None
            if own:
                if not own[1]:continue
                label=own[0]
            else:
                result_labels=result_context.get(fn,set())
                if len(result_labels)==1:label=next(iter(result_labels))
                else:
                    for sd,fr,td,to,*_ in row['edges']:
                        seen=recv(fr) if sd==main else None
                        if seen is None and td==main:seen=recv(to)
                        if seen is not None:
                            label=seen[0] if seen[1] else None
                            break
            if label is None:continue
            quality['post_header_associated']+=1;line=ip//64;site=anchors[label]['site']
            existing=prior_sites.get(site,{}).get('targets',[])
            if line==site//64 or any(t//64==line for t in existing):continue
            counts[label][line]+=1;addresses[line]=min(addresses.get(line,ip),ip)
            kinds[line]='incumbent_stub' if is_stub else 'original_main'
        source=Path(arms['lean']['overrides'][service]);raw=source.read_bytes();elf=stubs.Elf(raw)
        calls=[];choices=[]
        for label,weights in counts.items():
            selected=[(line,n) for line,n in weights.most_common() if n>=3][:8]
            if not selected:continue
            anchor=anchors[label];site=anchor['site'];offset=elf.offset(site,5,True);assert raw[offset]==0xe8
            targets=[addresses[line] for line,n in selected]
            calls.append(dict(site=site,callee=site+5+struct.unpack_from('<i',raw,offset+1)[0],expected=raw[offset:offset+5].hex(),targets=targets))
            choices.append(dict(reply_type=label,**anchor,targets=targets,counts=[n for line,n in selected],kinds=[kinds[line] for line,n in selected]))
        model[service]=dict(anchors=anchors,choices=choices,quality=dict(quality),training=str(trace),training_sha256=b.sha(trace))
        if not calls:continue
        output=root/'builds'/'reply'/service/source.name;plan=dict(sha256=b.sha(source),calls=calls)
        b.save(root/'plans'/'reply'/(service+'.json'),dict(source=str(source),plan=plan,choices=choices,
            rule='Typed client presult.read call after response header receipt. Original training only. NOP disables additional reply hints; incoming-RPC policy remains.'))
        built=stubs.build(source,plan,output);after=stubs.Elf(output.read_bytes())
        for hint in load(Path(str(source)+'.json'))['hints']:
            instruction=bytes.fromhex(hint['original']);offset=after.offset(hint['va'],len(instruction),True)
            assert after.data[offset:offset+len(instruction)]==instruction
        twin=Path(str(output)+'.nop');built.update(variant='reply',nop_path=str(twin))
        b.save(Path(str(output)+'.json'),built)
        b.save(Path(str(twin)+'.json'),dict(built,sha256=b.sha(twin),hints=[],variant='reply_nop'))
        arm['overrides'][service]=str(output);nop['overrides'][service]=str(twin)
        builds[service]=dict(binary=str(output),sha256=b.sha(output),nop=str(twin),nop_sha256=b.sha(twin),
            active_hints=len(built['hints']),extra_instruction_bytes=built['extra_instruction_bytes'])
        print(service,len(built['hints']),flush=True)
    b.save(root/'reply_model.json',model)
    assert builds,'No supported reply targets; model retained for revision before timing'
    arms.update(reply=arm,reply_nop=nop);b.save(root/'arms.json',arms)
    prepared=load(root/'prepared_candidates.json');prepared['reply']=dict(arm=arm,nop=nop,builds=builds)
    b.save(root/'prepared_candidates.json',prepared);b.save(root/'reply_model.json',model)
    b.save(root/'reply_prepared.json',dict(valid=True,builds=builds,epoch=time.time(),source_sha256=b.sha(__file__)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);prepare(parser.parse_args().root)
