#!/usr/bin/env python3
"""One fixed follow-up using RPC callers recovered by corrected stack unwinding."""
import argparse
import collections
import copy
import gzip
import json
from pathlib import Path
import struct
import subprocess
import time

import dense_build as b
from dense_cause_analysis import Code, category
import call_stub_prefetch as stubs
from rpc_route_study import load
from rpc_predict_run import campaign,run,SCRIPTS
from temporal_path_analysis import read
from temporal_path_confirm import cleanup,select


def prepare(parent):
    root=parent/'stack_followup';root.mkdir(exist_ok=False);(root/'source_versions').mkdir();b.space(root)
    train=parent/'callchain/unwind_probe/observations.json.gz'
    assert load(train.parent/'normalization_comparison.json')['same_sample_identities_and_leaf_addresses']
    b.save(root/'protocol.json',dict(epoch=time.time(),source_sha256=b.sha(__file__),training=str(train),training_sha256=b.sha(train),
        hypothesis='Previously unassociated main-ELF misses can be predicted from live RPC caller frames once perf load-bias decoding is repaired.',
        policy='Compose only. Up to eight new T1 target lines per RPC at the existing first normal handler call. Require unique stack-only RPC attribution and a live physical handler frame at/after that call. Skip targets with a matching incumbent issuer in bounded LBR; preserve all incumbent hints. Use decoded continuation instruction for straddling miss IPs. At least 10 samples per RPC/line.',
        validation='One frozen candidate, exact-layout new-hints-only NOP, and full incumbent; four paired blocks with balanced order, fresh stacks, 50s warmup and 60s clean ROI. No candidate selection from these endpoints or performance-based retries. Then one Compose L2 profile per full/candidate.',
        selection='Positive lower individual paired-log t95 throughput bound versus full; CPU <=+0.5%, p99 <=+2%. NOP causality reported separately. Do not combine with earlier stages or infer original-relative speedup by multiplying effects.',
        scope='All nine apps, unchanged incumbent MongoDB and DSO policies. Only Compose main ELF modified; no new kernel or DSO instrumentation.'))
    arms=load(parent/'arms.json');base=arms['full'];source=Path(base['overrides']['compose'])
    old=load(Path(str(source)+'.json'));code=Code(source);raw=source.read_bytes();elf=stubs.Elf(raw)
    inventory=load(parent/'rpc_inventory.json')['compose'];anchors={v['method']:v for v in load(parent/'model.json')['compose']['choices']}
    methods={v['method']:v for v in inventory['methods']}
    with gzip.open(train,'rt') as stream:data=json.load(stream)
    main=data['names'].index('/custom/ComposeReviewService');assert data['catalog'][data['names'][main]]['sha256']==b.sha(source)
    issuers={jump:{t//64 for t in patch['targets']} for patch in old['patches'] for jump in patch['terminal_jumps']}
    counts=collections.defaultdict(collections.Counter);addresses={};quality=collections.Counter()
    for row in data['rows']:
        quality['all']+=1
        if row['address'][0]!=main:quality['outside_main']+=1;continue
        if row['category']!='stack_only_unique':quality['not_new_unique_context']+=1;continue
        method=row['stack_context']['labels'][0]
        if method not in anchors:quality['no_anchor']+=1;continue
        anchor=anchors[method]['late'];handler=methods[method]['handler'];ip=row['address'][1]
        if not any(not f['inlined'] and f['address'][0]==main and max(anchor,handler['va'])<=f['address'][1]<handler['va']+handler['size'] for f in row['frames']):
            quality['no_post_anchor_physical_handler_frame']+=1;continue
        length=code.get(ip)[0]
        if not length:quality['undecoded']+=1;continue
        target=ip+length if ip//64!=(ip+length-1)//64 else ip
        if not code.get(target)[0]:quality['no_decoded_continuation']+=1;continue
        line=target//64
        if line in {anchor//64,(anchor+4)//64}:quality['issuer_line']+=1;continue
        if handler['va']<=ip<anchor:quality['before_anchor']+=1;continue
        if any(e[0]==main and line in issuers.get(e[1],set()) for e in row['edges']):
            quality['already_witnessed']+=1;continue
        quality['eligible']+=1;counts[method][line]+=1;addresses[line]=min(addresses.get(line,target),target)
    calls=[];choices=[];original=Code(Path(inventory['source']))
    for method,weights in sorted(counts.items()):
        selected=[(line,n) for line,n in weights.most_common() if n>=10][:8]
        if not selected:continue
        site=anchors[method]['late'];offset=elf.offset(site,5,True);assert raw[offset]==0xe8
        # Recheck the original handler entry dominance used by the timing study.
        prefix=[(ip,v[1]) for ip,v in original.instructions.items() if methods[method]['handler']['va']<=ip<site]
        assert not any(category(asm) in ('direct_call','indirect_call','conditional_branch','direct_jump','indirect_jump','return') for ip,asm in prefix)
        targets=[addresses[line] for line,n in selected]
        calls.append(dict(site=site,callee=site+5+struct.unpack_from('<i',raw,offset+1)[0],expected=raw[offset:offset+5].hex(),targets=targets))
        choices.append(dict(method=method,site=site,targets=targets,samples=[n for line,n in selected]))
    assert calls,'No supported stack-only targets; do not fabricate a policy'
    plan=dict(sha256=b.sha(source),calls=calls);b.save(root/'model.json',dict(quality=dict(quality),choices=choices,plan=plan))
    output=root/'builds/stack/compose'/source.name;record=stubs.build(source,plan,output,boundaries=code.instructions)
    after=stubs.Elf(output.read_bytes())
    for hint in old['hints']:
        instruction=bytes.fromhex(hint['original']);offset=after.offset(hint['va'],len(instruction),True)
        assert after.data[offset:offset+len(instruction)]==instruction
    record.update(variant='stack',nop_path=str(output)+'.nop');b.save(Path(str(output)+'.json'),record)
    b.save(Path(str(output)+'.nop.json'),dict(record,sha256=b.sha(str(output)+'.nop'),hints=[],variant='stack_nop'))
    candidate=copy.deepcopy(base);nop=copy.deepcopy(base);candidate['overrides']['compose']=str(output);nop['overrides']['compose']=str(output)+'.nop'
    b.save(root/'arms.json',dict(original=arms['original'],full=base,stack=candidate,stack_nop=nop))
    b.save(root/'prepared.json',dict(valid=True,source_sha256=b.sha(__file__),binary=str(output),nop=str(output)+'.nop',
        sha256=b.sha(output),nop_sha256=b.sha(str(output)+'.nop'),hints=len(record['hints']),sites=len(calls),extra_instruction_bytes=record['extra_instruction_bytes'],preserved_hints=len(old['hints'])))
    (root/'source_versions'/(b.sha(__file__)+'.py')).write_bytes(Path(__file__).read_bytes())
    return root


def run_followup(parent):
    root=prepare(parent);arms=load(root/'arms.json')
    observer=subprocess.Popen(['python3',SCRIPTS/'rpc_predict_environment.py',root],stdout=(root/'environment.log').open('w'),stderr=subprocess.STDOUT)
    try:
        for index,name in enumerate(('stack','stack_nop')):
            spec=root/('smoke_'+name+'.json');b.save(spec,dict(arms[name],root=str(root),out=str(root/'smoke'/name),seed=1022701+index))
            run(root,'smoke_'+name,['python3',SCRIPTS/'rpc_route_followup.py','platform_smoke',spec])
            assert load(root/'smoke'/name/'result.json')['valid']
        names=['full','stack','stack_nop'];orders=[names,list(reversed(names)),['stack','stack_nop','full'],['full','stack_nop','stack']]
        assert all(sum(v.index(n) for v in orders)==4 for n in names)
        campaign(root,'confirmation',arms,names,4,1022801,orders)
        for name in ('full','stack'):
            spec=root/('profile_'+name+'.json');b.save(spec,dict(arms[name],root=str(root),out=str(root/'profiles'/name),services=['compose'],kinds=['l2'],capture_s=8,seed=1022901,arm=name))
            run(root,'profile_'+name,['python3',SCRIPTS/'temporal_path_study.py','platform_capture',spec])
        code=Code(Path(arms['full']['overrides']['compose']));lines={t//64 for c in load(root/'model.json')['choices'] for t in c['targets']};profiles={}
        for name in ('full','stack'):
            data=read(root/'profiles'/name/'compose/l2/observations.json.gz');main=data['names'].index('/custom/ComposeReviewService');q=collections.Counter()
            for row in data['rows']:
                weight=data['period']/data['requests'];q['all']+=weight
                if row['dso']!=main:continue
                q['main']+=weight;ip=row['ip'];length=code.get(ip)[0]
                if ip//64 in lines:q['fixed_start_lines']+=weight
                if length and (ip+length-1)//64 in lines:q['fixed_end_lines']+=weight
            profiles[name]=dict(per_request=dict(q),period=data['period'],requests=data['requests'])
        b.save(root/'profile_summary.json',dict(arms=profiles,scope='Compose-only independent PEBS profiles; approximate per-request normalization. Fixed target lines, starting and ending instruction-line models; no full-system L2 claim.'))
        evaluation=load(root/'confirmation/evaluation.json');c=evaluation['e2e']['stack']['full']
        promoted=c['inverse_rps']['speedup_ci95'][0]>1 and c['stack_cpu']['cost_reduction_pct']>=-.5 and c['p99_ms']['cost_reduction_pct']>=-2
        b.save(root/'decision.json',dict(promoted=promoted,selected='stack' if promoted else 'full',comparison=c,
            nop_comparison=evaluation['e2e']['stack']['stack_nop'],epoch=time.time()))
        if not promoted:cleanup(root,['stack'],[arms['original'],arms['full']],'rejected_cleanup.json')
        b.save(root/'all_measurements_complete.json',dict(valid=True,clean_trials=12,smokes=2,profile_captures=2,epoch=time.time()))
        from rpc_predict_results import dedup_references
        dedup_references(root)
    finally:
        if observer.poll() is None:
            observer.terminate();observer.wait(timeout=10)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);run_followup(p.parse_args().parent)
