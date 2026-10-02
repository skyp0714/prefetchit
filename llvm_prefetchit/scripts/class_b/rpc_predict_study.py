#!/usr/bin/env python3
"""RPC-conditioned residual targets with byte-identical early/late controls."""
import argparse
import bisect
import collections
import copy
import json
from pathlib import Path
import shutil
import struct
import time

import dense_build as b
from dense_cause_analysis import Code, category
import call_stub_prefetch as stubs
from temporal_path_analysis import read
from rpc_route_study import load

PRIOR = Path('/storage/prefetchit/class_b_rpc_route_20261001')
TRAINING = Path('/storage/prefetchit/class_b_temporal_20261001/profiles/final_native')
VARIANTS = ('early', 'late', 'split', 'nop')


def prepare(root):
    root.mkdir(parents=True, exist_ok=False); b.space(root)
    (root/'source_versions').mkdir()
    refs=load(PRIOR/'references.json'); inventory=load(PRIOR/'rpc_inventory.json')
    b.save(root/'references.json',refs); b.save(root/'rpc_inventory.json',inventory)
    b.save(root/'protocol.json',dict(epoch=time.time(),
        objective='Test RPC-known future residual lines and distinguish issue timing from target/layout effects.',
        scope='Full Media compose-review C4, all nine apps; retain incumbent Mongo and DSO policies unchanged.',
        training=str(TRAINING), evaluation='Fresh requests, never used to select targets.',
        variants='Same eight hint slots per RPC: four before args decoding and four at handler first call. Early/late activate the same four targets once; split activates alternating ranks at opposite phases; NOP disables all new hints. Both stubs remain in all four variants.',
        selection='Residual main-ELF lines absent from all incumbent local target lists, including old stub instructions. At least three samples per RPC context; four highest counts. RPC context comes from sample function or nearest recognizable handler/processor in bounded LBR, mapping old stubs to their original call site. Association is not a full stack.',
        causality='Early and late normal calls execute once for each successfully decoded invocation; validate handler entry prefix has no branch/call before anchor. Errors excluded by zero-error workload checks. No claim of measured hint-to-fetch latency.',
        screen='Three fixed blocks of full/early/late/split/nop. Nominate highest RPS under CPU+0.5% and p99+2% guardrails; independent five-block original/full/nominee confirmation. No performance-based retries or pooling.',
        retention='Preserve compact results, settings, patches, hashes and source before immediate rejected-artifact cleanup.',
        budget_bytes=3*2**30))
    base=refs['previous']['arm']; arms={'original':refs['original'],'full':copy.deepcopy(base)}
    for v in VARIANTS:arms[v]=copy.deepcopy(base)
    models={}; total=collections.Counter(); builds={v:{} for v in VARIANTS}
    for service, info in inventory.items():
        b.space(root); source=Path(base['overrides'][service]); original=Code(Path(info['source']))
        code=Code(source); old=load(Path(str(source)+'.json')); raw=source.read_bytes(); elf=stubs.Elf(raw)
        ranges=sorted((p['stub'],max(p['terminal_jumps'])+5,p['site']) for p in old['patches'])
        starts=[r[0] for r in ranges]; contexts={}; anchors={}
        by_function=collections.defaultdict(list)
        for ip,(_,asm,fn) in original.instructions.items():by_function[fn].append(ip)
        for method in info['methods']:
            name=method['method']; fn=original.get(method['handler']['va'])[2]
            late=next(ip for ip in by_function[fn] if category(original.get(ip)[1])=='direct_call')
            prefix=[(ip,original.get(ip)[1]) for ip in by_function[fn] if ip<late]
            assert not any(category(asm) in ('conditional_branch','direct_jump','indirect_jump','indirect_call','return') for ip,asm in prefix),(service,name,prefix)
            contexts[fn]=name; contexts[original.get(method['processor']['va'])[2]]=name
            # Decoder samples themselves precede the late anchor: do not use as targets.
            anchors[name]=dict(early=method['args_site'],late=late,handler=method['handler']['va'],prefix_instructions=len(prefix))
        def origin(ip):
            i=bisect.bisect_right(starts,ip)-1
            return (ranges[i][2],True) if i>=0 and ip<ranges[i][1] else (ip,False)
        def context(ip):
            ip,_=origin(ip);return contexts.get(original.get(ip)[2])
        trace=TRAINING/service/'l2/observations.json.gz'; data=read(trace)
        main=data['digests'].index(old['sha256']); counts=collections.defaultdict(collections.Counter)
        addresses={}; kinds={}; quality=collections.Counter(); all_lines=collections.Counter()
        targeted={t//64 for p in old['patches'] for t in p['targets']}
        # All methods' decoder/processor lines are excluded; both experimental phases precede selected targets.
        pre_functions={original.get(m[k])[2] for m in info['methods'] for k in ['args_callee']}
        pre_functions.update(original.get(m['processor']['va'])[2] for m in info['methods'])
        for row in data['rows']:
            quality['all']+=1
            if row['dso']!=main:quality['outside_main']+=1;continue
            ip=row['ip']; mapped,is_stub=origin(ip); fn=original.get(mapped)[2]
            kind='incumbent_stub' if is_stub else 'original_main'
            quality[kind]+=1
            if not code.get(ip)[0]:quality['not_decoded']+=1;continue
            if fn in pre_functions:quality['decoder_or_processor']+=1;continue
            label=context(ip)
            if label is None:
                for sd,fr,td,to,*_ in row['edges']:
                    label=context(fr) if sd==main else None
                    if label is None and td==main:label=context(to)
                    if label is not None:break
            if label is None:quality['no_rpc_context']+=1;continue
            quality['rpc_associated']+=1; line=ip//64
            all_lines[line]+=1
            if line in targeted:quality['already_targeted']+=1;continue
            a=anchors[label]
            if line in {a['early']//64,a['late']//64}:continue
            # Do not target handler entry instructions already executed by the late anchor.
            if fn==original.get(a['handler'])[2] and mapped<a['late']:continue
            counts[label][line]+=1;addresses[line]=min(addresses.get(line,ip),ip);kinds[line]=kind
        choices=[];calls=[]; site_phase={}
        for name,weights in counts.items():
            selected=[(line,n) for line,n in weights.most_common() if n>=3][:4]
            if len(selected)<2:continue
            targets=[addresses[line] for line,n in selected]; a=anchors[name]
            choices.append(dict(method=name,**a,targets=targets,counts=[n for line,n in selected],kinds=[kinds[line] for line,n in selected]))
            for phase in ('early','late'):
                site=a[phase];offset=elf.offset(site,5,True);assert raw[offset]==0xe8
                calls.append(dict(site=site,callee=site+5+struct.unpack_from('<i',raw,offset+1)[0],expected=raw[offset:offset+5].hex(),targets=targets))
                site_phase[site]=(phase,targets)
        models[service]=dict(training=str(trace),training_sha256=b.sha(trace),quality=dict(quality),choices=choices,
            events_per_request={k:v*data['period']/data['requests'] for k,v in quality.items()})
        total.update(models[service]['events_per_request'])
        if not calls:continue
        plan=dict(sha256=b.sha(source),calls=calls)
        output=root/'builds'/'template'/service/source.name
        record=stubs.build(source,plan,output,boundaries=code.instructions)
        b.save(root/'plans'/(service+'.json'),dict(source=str(source),plan=plan,choices=choices))
        template=output.read_bytes(); slots={}
        for patch in record['patches']:
            phase,targets=site_phase[patch['site']]
            for rank,target in enumerate(targets):slots[patch['stub']+rank*7]=(phase,rank,target)
        for variant in VARIANTS:
            target=root/'builds'/variant/service/source.name;target.parent.mkdir(parents=True,exist_ok=True)
            binary=bytearray(template); active=[]; changes=[]
            for hint in record['hints']:
                phase,rank,address=slots[hint['va']]
                enable=variant==phase or (variant=='split' and phase==('early' if rank%2==0 else 'late'))
                if enable:active.append(hint)
                else:
                    binary[hint['offset']:hint['offset']+7]=bytes.fromhex(hint['nop']);changes.append(hint['offset'])
            # All incumbent hints and original address locations must survive.
            after=stubs.Elf(binary)
            for hint in old['hints']:
                instruction=bytes.fromhex(hint['original']); off=after.offset(hint['va'],len(instruction),True)
                assert binary[off:off+len(instruction)]==instruction
            target.write_bytes(binary);target.chmod(0o755)
            metadata=dict(record,sha256=b.sha(target),hints=active,all_new_hint_slots=record['hints'],disabled_offsets=changes,variant=variant,
                incumbent_metadata=str(source)+'.json',timing_pair_layout_sha256=b.sha(str(output)+'.nop'))
            b.save(Path(str(target)+'.json'),metadata)
            arms[variant]['overrides'][service]=str(target)
            builds[variant][service]=dict(binary=str(target),sha256=b.sha(target),active_hints=len(active),extra_instruction_bytes=record['extra_instruction_bytes'])
        # Template and its twin are superseded, preserve metadata before deleting.
        removed=[dict(path=str(p),bytes=p.stat().st_size,sha256=b.sha(p)) for p in (output,Path(str(output)+'.nop'))]
        retirement=dict(reason='All four byte-controlled variants materialized; template no longer needed',files=removed,
            bytes_removed=sum(x['bytes'] for x in removed),free_before=shutil.disk_usage(root).free)
        b.save(root/'cleanup'/('template_'+service+'.json'),retirement)
        for r in removed:Path(r['path']).unlink()
        retirement.update(complete=True,free_after=shutil.disk_usage(root).free)
        b.save(root/'cleanup'/('template_'+service+'.json'),retirement);b.space(root)
        print(json.dumps(dict(stage='prepared',service=service,methods=len(choices),active_hints=sum(len(c['targets']) for c in choices))),flush=True)
    for name,arm in arms.items():arm['controls']=[x for x in arms if x!=name]
    b.save(root/'arms.json',arms);b.save(root/'model.json',models);b.save(root/'training_summary.json',dict(total))
    b.save(root/'prepared_candidates.json',{v:dict(arm=arms[v],nop=arms['nop'],builds=builds[v]) for v in VARIANTS})
    for path in [Path(__file__),Path(stubs.__file__)]:
        (root/'source_versions'/(b.sha(path)+'.py')).write_bytes(path.read_bytes())
    b.save(root/'prepared.json',dict(valid=True,epoch=time.time(),builds=builds))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);prepare(parser.parse_args().root)
