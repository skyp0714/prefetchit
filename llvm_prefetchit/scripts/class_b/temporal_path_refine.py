#!/usr/bin/env python3
"""Add trace-supported next-line targets at existing calls, then test stub layout."""
import argparse
import collections
import copy
import json
from pathlib import Path
import re
import subprocess

import dense_build as b
from temporal_path_analysis import load_original_images, files, read, target_for, observed_calls, choose, stubs
from temporal_path_residual import policies


def base_arm(root,name):
    prepared=json.loads((root/'prepared_candidates.json').read_text())
    if name in prepared:return prepared[name]['arm']
    return json.loads((root/'arms.json').read_text())[name]


def deployed_policies(arm,known):
    paths=set(arm['overrides'].values())|{arm['mongo_binary']}
    for values in arm.get('libraries',{}).values():paths.update(values.values())
    result={}
    for path in paths:
        digest=b.sha(path)
        if digest in known:
            record=known[digest]
            assert record['original_instruction_addresses_unchanged'] and 'hybrid' not in record
            source=record['source_sha256']
            assert source not in result or result[source]['sha256']==digest
            result[source]=dict(record,binary=path)
    return result


def next_line_description(source_sha,call,target_sha,target):
    """Only extend a preceding target in this exact observed call's bundle."""
    local=call['targets'];external=call.get('got_targets',[]);line=target//64
    if len(local)+len(external)>=8:return None
    existing={(source_sha,t//64) for t in local}
    existing.update((t['target_sha'],t['target']//64) for t in external)
    if (target_sha,line) in existing or (target_sha,line-1) not in existing:return None
    if source_sha==target_sha:return dict(kind='local',target=target)
    previous=next(t for t in external if t['target_sha']==target_sha and t['target']//64==line-1)
    addend=target-previous['anchor']
    if not -(1<<31)<=addend<1<<31:return None
    return dict(kind='cross',target=target,got=previous['got'],anchor=previous['anchor'],addend=addend)


def share_anchors(source_sha,plan,anchors):
    """Keep target addresses, but reuse one observed GOT anchor per image."""
    result=copy.deepcopy(plan)
    for call in result['calls']:
        before={(t['target_sha'],t['target']) for t in call.get('got_targets',[])}
        for target in call.get('got_targets',[]):
            choices=anchors[source_sha,target['target_sha']]
            chosen=min(choices,key=lambda value:(-value['observations'],value['got']))
            addend=target['target']-chosen['anchor']
            assert -(1<<31)<=addend<1<<31
            target.update(got=chosen['got'],anchor=chosen['anchor'],addend=addend)
        if call.get('got_targets'):call['got_targets'].sort(key=lambda t:(t['got'],t['addend']))
        assert before=={(t['target_sha'],t['target']) for t in call.get('got_targets',[])}
    return result


def select_neighbors(root,base,phase,deployed,known):
    images=load_original_images(root);rows=[];quality=collections.Counter();inputs=[]
    calls={(digest,row['site']):row for digest,record in deployed.items() for row in record['plan']['calls']}
    paths=files(root,phase,'l2');assert len(paths)==12,paths
    for path in paths:
        protocol=json.loads((path.parents[2]/'protocol.json').read_text())
        assert protocol['arm']==base,(path,protocol['arm'],base)
        data=read(path);digests=[known[d]['source_sha256'] if d in known else d for d in data['digests']]
        inputs.append(dict(path=str(path),sha256=b.sha(path),samples=len(data['rows'])))
        for sample in data['rows']:
            quality['all_samples']+=1
            if sample['dso']<0:quality['unmapped']+=1;continue
            target_sha=digests[sample['dso']]
            if target_sha not in images:quality['unsupported_image']+=1;continue
            target=target_for(images[target_sha],sample)
            if target is None:quality['outside_original_instruction_boundaries']+=1;continue
            sites={}
            for site,age in observed_calls(sample,digests,images,64,8192).items():
                if site not in calls:continue
                description=next_line_description(site[0],calls[site],target_sha,target)
                if description is not None:sites[site]=dict(description,age=age)
            quality['eligible_samples']+=bool(sites)
            rows.append(dict(target_sha=target_sha,target=target,line=target//64,sites=sites,
                weight=data['period']/data['requests'],service=data['service'],age_us=sample['age_us']))
    frequency=json.loads((root/'analysis/call_frequency.json').read_text())
    rates={(v['sha'],v['site']):v['per_request'] for v in frequency['rates']}
    selected=choose(rows,rates,frequency['floor'],max_sites=1024,max_hints=1024,per_site=1,min_gain=4,goal=.75,cross_cost=1)
    selected.update(quality=dict(quality),inputs=inputs,base=base,phase=phase,
        covered_all_sample_fraction=selected['covered']/quality['all_samples'],
        rule='At most one new target per existing direct call. Require an existing target in the preceding line of the same destination ELF and the source call in the actual bounded LBR at 64..8192 completed-branch cycles. Preserve every old hint, eight total per site; cross-DSO targets reuse that existing GOT anchor.',
        interpretation='Residual diagnosis is training, not an independent coverage test. Frozen candidates require fresh clean E2E and new diagnostic validation. A completed-branch-cycle proxy is not issue-to-fetch lead.')
    return selected


def build_variants(root,base,selected,deployed):
    from e2e_lbr import remove_generated
    original_arm=base_arm(root,base);prepared=json.loads((root/'prepared_candidates.json').read_text());new_records={}
    groups=collections.defaultdict(list)
    for choice in selected['choices']:groups[choice['source_sha']].append(choice)
    anchor_path=root/'analysis/got_anchors.json'
    anchors={(row['source'],row['target']):row['entries'] for row in json.loads(anchor_path.read_text())['anchors']}
    variants=[(base+'_aligned',False,'cache_line',False)]
    if selected['choices']:
        variants += [(base+'_neighbor',True,'compact',False)]
    variants.append((base+'_shared_anchor',False,'compact',True))
    for name,add_neighbors,alignment,shared_anchor in variants:
        arm=copy.deepcopy(original_arm);nop=copy.deepcopy(original_arm);remap={};builds={};generated=[]
        try:
            for digest,old in deployed.items():
                b.space(root);plan=copy.deepcopy(old['plan']);plan['stub_alignment']=alignment
                by_site={call['site']:call for call in plan['calls']};choices=groups[digest] if add_neighbors else []
                for choice in choices:
                    row=by_site[choice['site']]
                    assert next_line_description(digest,row,choice['target_sha'],choice['target']) is not None
                    if choice['kind']=='local':row['targets'].append(choice['target'])
                    else:
                        row.setdefault('got_targets',[]).append({k:choice[k] for k in ('got','anchor','addend','target','target_sha')})
                for call in by_site.values():
                    if call.get('got_targets'):call['got_targets'].sort(key=lambda t:(t['got'],t['addend']))
                if shared_anchor:plan=share_anchors(digest,plan,anchors)
                source=Path(old['source']);out=root/'builds'/name/digest/source.name
                b.save(root/'plans'/name/(digest+'.json'),dict(plan=plan,source=str(source),base_binary=old['binary'],
                    base_sha256=old['sha256'],kept_choices=choices,skipped=[],source_sha256=b.sha(__file__),builder_sha256=b.sha(stubs.__file__),
                    shared_anchor=shared_anchor,anchor_evidence_sha256=b.sha(anchor_path) if shared_anchor else None))
                record=stubs.build(source,plan,out);generated += [out,Path(str(out)+'.nop')]
                builds[digest]=dict(binary=str(out),nop=str(out)+'.nop',sha256=record['sha256'],nop_sha256=record['nop_sha256'],
                    extra_instruction_bytes=record['extra_instruction_bytes'],sites=len(by_site),new_hints=len(choices),
                    cross_hints=sum(c['kind']=='cross' for c in choices),hints=len(record['hints']))
                remap[old['binary']]=str(out)
            for destination,suffix in ((arm,''),(nop,'.nop')):
                destination['overrides']={k:remap.get(v,v)+suffix if v in remap else v for k,v in destination['overrides'].items()}
                v=destination['mongo_binary'];destination['mongo_binary']=remap[v]+suffix if v in remap else v
                destination['libraries']={k:{path:remap[v]+suffix if v in remap else v for path,v in values.items()} for k,values in destination.get('libraries',{}).items()}
            arm['controls']=['original','mongo',base,name+'_nop'];nop['controls']=['original']
            result=dict(arm=arm,nop=nop,builds=builds,excluded=[],base=base,alignment=alignment,add_neighbors=add_neighbors,
                shared_anchor=shared_anchor,
                anchor_rule='Highest training LBR support per source/destination image; unchanged targets, fewer GOT loads; runtime resolution revalidated in smoke.' if shared_anchor else None)
            prepared[name]=result;new_records[name]=result
            b.save(root/'candidates'/name/'prepared.json',result)
            b.save(root/'prepared_candidates.json',prepared)
            print(json.dumps(dict(stage='refined_built',variant=name,new_hints=sum(v['new_hints'] for v in builds.values()),
                instruction_bytes=sum(v['extra_instruction_bytes'] for v in builds.values()))),flush=True)
        except BaseException as error:
            b.save(root/'candidates'/name/'failure.json',dict(error=repr(error),completed=builds))
            existing=[path for path in generated if path.exists()]
            if existing:remove_generated(existing,root/'candidates'/name/'failure_cleanup.json','Failed refinement; plans, patches, hashes and failure retained.')
            raise
    b.save(root/'prepared_candidates.json',prepared)
    return new_records


def build_native_it0(root,base):
    from e2e_lbr import remove_generated
    prepared=json.loads((root/'prepared_candidates.json').read_text())
    if base not in prepared:return None
    original=prepared[base];name=base+'_native_it0';result=copy.deepcopy(original)
    arm=result['arm'];remap={};generated=[];changed=0
    try:
        for digest,entry in original['builds'].items():
            if entry['binary']==arm['mongo_binary']:continue
            source=Path(entry['binary']);audit=json.loads(Path(str(source)+'.json').read_text())
            before=source.read_bytes();assert b.sha(source)==entry['sha256']
            data=bytearray(before);changes=[];hints=copy.deepcopy(audit['hints'])
            for hint in hints:
                if hint.get('kind')=='t1_got':continue
                offset=hint['offset'];assert data[offset:offset+7].hex()==hint['original']
                assert data[offset:offset+3]==bytes.fromhex('0f1815')
                data[offset+2]=0x3d
                changes.append(dict(offset=offset+2,before='15',after='3d',va=hint['va']))
                hint.update(original=data[offset:offset+7].hex(),kind='it0')
            if not changes:continue
            restored=bytearray(data)
            for change in changes:restored[change['offset']]=0x15
            assert restored==before
            nop=bytearray(data)
            for hint in hints:
                value=bytes.fromhex(hint['nop']);nop[hint['offset']:hint['offset']+len(value)]=value
            assert stubs.sha(nop)==audit['nop_sha256']
            b.space(root);out=root/'builds'/name/digest/source.name;out.parent.mkdir(parents=True)
            out.write_bytes(data);out.chmod(0o755);generated.append(out)
            record=dict(audit,sha256=b.sha(out),hints=hints,nop_path=entry['nop'],opcode_transform=dict(source=str(source),
                source_sha256=entry['sha256'],tool_sha256=b.sha(__file__),changes=changes,
                same_layout=True,same_targets=True,same_nop=True,
                rule='Local native/server-library hints become IT0; MongoDB and all register/GOT T1 hints stay unchanged. No schedule-age gate or added instructions.'))
            b.save(Path(str(out)+'.json'),record)
            decoded=subprocess.check_output(['objdump','-d','-j','.text.prefetch_calls','--insn-width=16',str(out)],text=True)
            Path(str(out)+'.stubs.asm').write_text(decoded)
            instructions={int(m[1],16):m[2] for line in decoded.splitlines()
                if (m:=re.match(r'^\s*([0-9a-f]+):\s*(?:[0-9a-f]{2}\s+)+\s*(.*?)\s*$',line))}
            assert all(instructions[c['va']].startswith('prefetchit0') for c in changes)
            result['builds'][digest]=dict(entry,binary=str(out),sha256=record['sha256'],new_hints=0,opcode_changed_hints=len(changes))
            remap[str(source)]=str(out);changed+=len(changes)
        assert changed
        arm['overrides']={k:remap.get(v,v) for k,v in arm['overrides'].items()}
        arm['libraries']={k:{p:remap.get(v,v) for p,v in values.items()} for k,values in arm.get('libraries',{}).items()}
        arm['controls']=['original','mongo',base,name+'_nop']
        result.update(base=base,opcode_changed_hints=changed,identical_nop_to_base=True)
        prepared[name]=result;b.save(root/'candidates'/name/'prepared.json',result);b.save(root/'prepared_candidates.json',prepared)
        print(json.dumps(dict(stage='native_it0_built',variant=name,changed_hints=changed)),flush=True)
        return name
    except BaseException as error:
        b.save(root/'candidates'/name/'failure.json',dict(error=repr(error),base=base,changed_hints=changed))
        if generated:remove_generated(generated,root/'candidates'/name/'failure_cleanup.json','Rejected opcode candidate; byte patches, hashes and decode evidence retained.')
        raise


def prepare(root,base,phase):
    out=root/'refinement'/base;out.mkdir(parents=True,exist_ok=False);b.space(root)
    known=policies(root);deployed=deployed_policies(base_arm(root,base),known)
    assert deployed
    selected=select_neighbors(root,base,phase,deployed,known)
    b.save(out/'selection.json',selected)
    result=build_variants(root,base,selected,deployed)
    it0=build_native_it0(root,base)
    from temporal_path_compact import prepare as compact
    compact_name=compact(root,base)
    b.save(out/'complete.json',dict(valid=True,variants=list(result)+([it0] if it0 else [])+([compact_name] if compact_name else []),neighbors_selected=bool(selected['choices'])))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--base',required=True);p.add_argument('--phase',required=True)
    a=p.parse_args();prepare(a.root,a.base,a.phase)
