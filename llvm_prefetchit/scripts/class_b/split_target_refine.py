#!/usr/bin/env python3
"""Retarget existing T1 slots using the continuation line of split instructions.

This freezes every call, stub, instruction address and hint count. The model
assumes the continuation line is responsible for split-IP samples; a separate
native calibration is required and the service experiment tests that assumption.
"""
import argparse
from collections import defaultdict,Counter
import gzip
import heapq
import json
from pathlib import Path
import re
import struct
import subprocess
import dense_build as b
from callpath_prefetch import stubs
from dense_cause_analysis import Code
from e2e_lbr import remove_generated


def choose(rows,groups,capacities,original):
    candidates=defaultdict(set);anchors={};weights=[]
    for index,row in enumerate(rows):
        anchors.setdefault(row['line'],row['target']);weights.append(row['weight'])
        for group in {groups[site] for site in row['sites'] if site in groups}:
            candidates[group,row['line']].add(index)
    heap=[(-sum(weights[i] for i in ids),group,line) for (group,line),ids in candidates.items() if len(ids)>=8]
    heapq.heapify(heap);covered=set();selected=defaultdict(list);decisions=[]
    while heap:
        _,group,line=heapq.heappop(heap)
        if len(selected[group])>=capacities[group]:continue
        unseen=candidates[group,line]-covered
        if len(unseen)<8:continue
        gain=sum(weights[i] for i in unseen);score=(-gain,group,line)
        if heap and score>heap[0]:heapq.heappush(heap,score);continue
        selected[group].append(anchors[line]);covered.update(unseen)
        decisions.append(dict(stub=group,target=anchors[line],gain_samples=len(unseen),weighted_gain=gain))
    for group,targets in original.items():
        lines={target//64 for target in selected[group]}
        for target in targets:
            if len(selected[group])==capacities[group]:break
            if target//64 not in lines:selected[group].append(target);lines.add(target//64)
        assert len(selected[group])==capacities[group] and len(lines)==capacities[group]
    return dict(selected),decisions


def coverage(rows,groups,selected):
    lines={group:{t//64 for t in targets} for group,targets in selected.items()}
    covered=[r for r in rows if any(r['line'] in lines[groups[s]] for s in r['sites'] if s in groups)]
    return dict(samples=len(rows),covered=len(covered),weighted_total=sum(r['weight'] for r in rows),
        weighted_covered=sum(r['weight'] for r in covered))


def prepare(parent,out):
    calibration=json.loads((parent/'split_fetch_probe/complete.json').read_text());assert calibration['valid']
    probe=json.loads((parent/'split_fetch_probe/samples.json').read_text())
    samples={r['kind']:r['split_start_samples'] for r in probe}
    assert samples['nop']>100 and samples['first']>100 and samples['second']<.1*samples['first'],samples
    out.mkdir(parents=True,exist_ok=False);b.space(out)
    prior=json.loads((parent/'callpath_coverage75/prepared.json').read_text())
    source=Path(prior['candidates']['cost75']['binary']);audit=json.loads(Path(str(source)+'.json').read_text())
    assert b.sha(source)==audit['sha256'];reference=Path(prior['reference'])
    b.save(out/'protocol.json',dict(source=str(source),source_sha256=audit['sha256'],reference_sha256=b.sha(reference),
        runner_sha256=b.sha(__file__),calibration_sha256=b.sha(parent/'split_fetch_probe/samples.json'),
        rule='All call sites, canonical groups, hint slots and instruction addresses frozen at cost75. Greedy train-only weighted coverage within existing per-stub capacities. Use last instruction-byte line for split samples, otherwise original sampled line; preserve old targets in unused slots. Heldout never selects targets.',
        limitation='Continuation-line attribution is a model motivated by a known cold-line probe. A PEBS IP does not reveal which line missed in the service, and selected path coverage does not prove accepted or useful prefetches.'))
    code=Code(reference);groups={p['site']:p['stub'] for p in audit['patches']};original={}
    for patch in audit['patches']:
        if patch['stub'] in original:assert original[patch['stub']]==patch['targets']
        else:original[patch['stub']]=patch['targets']
    capacities={group:len(targets) for group,targets in original.items()}
    source_root=parent/'callpath';quality=json.loads((source_root/'profile_quality.json').read_text())
    services=json.loads((source_root/'protocol.json').read_text())['training_services'];phases={};inputs=[];split_targets={}
    for phase in ['train','heldout']:
        corrected=[];legacy=[];counts=Counter()
        for service in services:
            path=source_root/'observations'/(phase+'_'+service+'.json.gz')
            assert b.sha(path)==quality['records'][phase+':'+service]['observations_sha256']
            with gzip.open(path,'rt') as stream:rows=json.load(stream)
            requests=json.loads((source_root/'profiles'/phase/service/'request_window.json').read_text())['completed_requests']
            inputs.append(dict(path=str(path),sha256=b.sha(path),samples=len(rows),requests=requests))
            for row in rows:
                ip=row['ip'];length,_,_=code.get(ip);assert length
                sites=[site for site,ages in row['ages'] if any(64<=age<=8192 for age in ages)]
                prior_row=dict(line=row['line'],target=row['target'],sites=sites,weight=257/requests)
                legacy.append(prior_row);counts['samples']+=1
                if ip//64!=(ip+length-1)//64:
                    # Next real instruction start is in the continuation line.
                    # T1 permits arbitrary bytes, but retain instruction anchors.
                    target=ip+length;assert target in code.instructions
                    assert target//64==(ip+length-1)//64
                    split_targets[ip]=target
                    counts['split']+=1;corrected.append(dict(prior_row,line=target//64,target=target))
                else:corrected.append(prior_row)
        phases[phase]=dict(corrected=corrected,legacy=legacy,counts=dict(counts))
    selected,decisions=choose(phases['train']['corrected'],groups,capacities,original)
    summary={phase:dict(counts=records['counts'],
        legacy_original=coverage(records['legacy'],groups,original),
        continuation_original=coverage(records['corrected'],groups,original),
        continuation_retarget=coverage(records['corrected'],groups,selected)) for phase,records in phases.items()}
    b.save(out/'selection.json',dict(selected=selected,decisions=decisions,summary=summary,inputs=inputs))
    b.save(out/'split_targets.json',dict(targets=split_targets,reference_sha256=b.sha(reference),
        rule='Deterministic instruction-byte spans only; no sample weights or performance outcomes. Heldout lengths may appear in this map but cannot select a training target absent from training.'))
    raw=source.read_bytes();data=bytearray(raw);changes=[];new_hints=[];positions={}
    for group,targets in selected.items():
        for index,target in enumerate(targets):positions[group+index*7]=target
    assert len(positions)==len(audit['hints'])
    elf=stubs.Elf(raw)
    for hint in audit['hints']:
        va=hint['va'];offset=hint['offset'];target=positions[va]
        assert elf.offset(va,7,True)==offset and raw[offset:offset+7].hex()==hint['original']
        assert raw[offset:offset+3]==bytes.fromhex('0f1815') and target in code.instructions
        assert -(1<<31)<=target-va-7<(1<<31)
        replacement=bytes.fromhex('0f1815')+struct.pack('<i',target-va-7)
        data[offset:offset+7]=replacement
        if target!=hint['target']:changes.append(dict(va=va,offset=offset+3,original=raw[offset+3:offset+7].hex(),replacement=replacement[3:].hex(),old_target=hint['target'],target=target))
        new_hints.append(dict(hint,target=target,original=replacement.hex()))
    reverse=bytearray(data)
    for change in changes:reverse[change['offset']:change['offset']+4]=bytes.fromhex(change['original'])
    assert bytes(reverse)==raw and len(data)==len(raw) and changes
    # Replacing the same slots by their original NOPs must recover the exact
    # already-measured NOP twin; no new executable NOP copy is needed.
    nop=bytearray(data)
    for hint in new_hints:nop[hint['offset']:hint['offset']+7]=bytes.fromhex(hint['nop'])
    assert stubs.sha(nop)==audit['nop_sha256']
    binary=out/'mongod';b.space(out)
    try:
        binary.write_bytes(data);binary.chmod(source.stat().st_mode)
        b.run(['objdump','-d','-j','.text.prefetch_calls','--insn-width=16',binary],out/'stubs.asm')
        found={}
        for line in (out/'stubs.asm').read_text().splitlines():
            match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$',line)
            if not match or int(match[1],16) not in positions:continue
            target=re.search(r'#\s*([0-9a-f]+)',match[3]);assert target and match[3].startswith('prefetcht1')
            assert len(bytes.fromhex(match[2]))==7
            found[int(match[1],16)]=int(target[1],16)
        assert found==positions
        record=dict(audit,sha256=b.sha(binary),hints=new_hints,retarget=dict(parent=str(source),
            parent_sha256=audit['sha256'],changes=changes,only_displacements_changed=True,
            exact_existing_nop_preserved=True,extra_instruction_bytes=0,source_sha256=b.sha(__file__)))
        for patch in record['patches']:patch['targets']=selected[patch['stub']]
        for call in record['plan']['calls']:call['targets']=selected[groups[call['site']]]
        b.save(Path(str(binary)+'.json'),record)
        b.save(out/'prepared.json',dict(binary=str(binary),sha256=record['sha256'],nop=prior['candidates']['cost75']['nop'],
            changed_hints=len(changes),hints=len(new_hints),call_sites=len(groups),extra_instruction_bytes=0,summary=summary))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error),changes=changes))
        remove_generated([binary] if binary.exists() else [],out/'cleanup.json','Split-line retarget rejected; retain settings, changes, source and hashes.')
        raise
    b.save(out/'complete.json',dict(valid=True,scope='Binary validation only. Service performance pending.'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);p.add_argument('out',type=Path);a=p.parse_args();prepare(a.parent,a.out)
