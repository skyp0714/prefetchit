#!/usr/bin/env python3
"""Spend existing split75 hint slots on newly observed residual miss lines."""
import argparse
import collections
import gzip
import hashlib
import heapq
import json
from pathlib import Path
import struct
import dense_build as b
from dense_cause_analysis import Code
from e2e_lbr import remove_generated


def mask_rows(rows, slots_for_site=None):
    groups=collections.defaultdict(list)
    for row in rows: groups[row['line']].append(row)
    masks={}
    for line, values in groups.items():
        table=collections.defaultdict(int)
        for index,row in enumerate(values):
            for site,ages in row['ages']:
                if not any(64<=age<=8192 for age in ages): continue
                for slot in slots_for_site.get(site,[]) if slots_for_site is not None else [site]:
                    table[slot] |= 1<<index
        masks[line]=dict(table)
    return masks


def union(table,line,slots):
    result=0
    for slot in slots: result |= table.get(line,{}).get(slot,0)
    return result


def coverage(table,assignments):
    return sum(union(table,line,slots).bit_count() for line,slots in assignments.items())


def original_rows(parent,phase,code):
    rows=[];inputs=[]
    for path in sorted((parent/'callpath/observations').glob(phase+'_*.json.gz')):
        with gzip.open(path,'rt') as stream: values=json.load(stream)
        for row in values:
            length=code.get(row['ip'])[0];assert length
            if row['ip']//64!=(row['ip']+length-1)//64: row['line']=(row['ip']+length)//64
        inputs.append(dict(path=str(path),sha256=b.sha(path),samples=len(values)));rows.extend(values)
    assert len(inputs)==3
    return rows,inputs


def patch(binary,audit,targets,out,code):
    b.space(out);data=bytearray(binary.read_bytes());changes=[];hints=[]
    for hint in audit['hints']:
        va=hint['va'];offset=hint['offset'];target=targets[va];assert target in code.instructions
        before=bytes(data[offset:offset+7]);assert before.hex()==hint['original'] and before[:3]==bytes.fromhex('0f1815')
        after=before[:3]+struct.pack('<i',target-va-7);data[offset:offset+7]=after
        if before!=after:changes.append(dict(offset=offset,before=before.hex(),after=after.hex()))
        hints.append(dict(hint,target=target,original=after.hex()))
    restored=bytearray(data)
    for row in changes:restored[row['offset']:row['offset']+7]=bytes.fromhex(row['before'])
    assert hashlib.sha256(restored).hexdigest()==audit['sha256']
    nop=bytearray(data)
    for hint in hints:nop[hint['offset']:hint['offset']+7]=bytes.fromhex(hint['nop'])
    assert hashlib.sha256(nop).hexdigest()==audit['nop_sha256']
    patches=[dict(row,targets=[targets[row['stub']+7*j] for j in range(len(row['targets']))]) for row in audit['patches']]
    calls=[{key:row[key] for key in old} for old,row in zip(audit['plan']['calls'],patches)]
    dest=out/'mongod';dest.write_bytes(data);dest.chmod(0o755)
    record=dict(audit,sha256=b.sha(dest),hints=hints,patches=patches,plan=dict(audit['plan'],calls=calls),
        residual_retarget=dict(source=str(binary),source_sha256=audit['sha256'],source_tool_sha256=b.sha(__file__),
            changes=changes,identical_nop_sha256=audit['nop_sha256'],only_hint_displacements_changed=True))
    b.save(Path(str(dest)+'.json'),record)
    try:
        verified=Code(dest);assert all(verified.raw_targets[h['va']]==h['target'] for h in hints)
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)))
        remove_generated([dest],out/'failed_cleanup.json','Decode failed; source, input, plan, patch and hashes retained.');raise
    return dict(binary=str(dest),sha256=record['sha256'],changed_slots=len(changes),identical_nop=True,
        extra_instruction_bytes=record['extra_instruction_bytes'],additional_instruction_bytes=0)


def prepare(parent,root):
    assert json.loads((root/'residual_diagnostics/complete.json').read_text())['valid']
    out=root/'residual_retarget';out.mkdir(exist_ok=False);b.space(out)
    initial=json.loads((root/'prepared_complete.json').read_text());binary=Path(initial['arms']['split75']['mongo_binary'])
    b.save(root/'followup_amendment.json',dict(before_any_followup_timing=True,
        replaced_candidate='lead_swap',replacement='residual_t1',
        reason='Coverage-preserving timing swaps changed only 0.4 percentage points of original heldout early coverage. Fresh split75 residual diagnostics place about 95% of modeled remaining misses outside selected target lines. Test targeted residual coverage, retaining the independent stronger lead512 arm and its NOP.',
        scope_correction='Residual PEBS captures cover the two review MongoDBs, as explicit analysis records show. The diagnostic protocol prose incorrectly said Mongo3. Full endpoint load includes MovieId; the E2E PMU screen still covers all three MongoDBs.'))
    unused=root/'lead_swap/mongod'
    if unused.exists():
        assert str(unused) not in {v['mongo_binary'] for v in initial['arms'].values()}
        remove_generated([unused],root/'lead_swap/superseded_cleanup.json',
            'Superseded before E2E by residual-target candidate after independent diagnosis; no performance result exists for this candidate. Preserve train/check statistics, byte patches, source and binary/NOP hashes.')
    audit=json.loads(Path(str(binary)+'.json').read_text());assert b.sha(binary)==audit['sha256']
    targets={row['va']:row['target'] for row in audit['hints']};original_targets=dict(targets)
    site_slots={row['site']:[row['stub']+7*j for j in range(len(row['targets']))] for row in audit['patches']}
    assert sum(map(len,site_slots.values()))==len(targets)
    slot_groups={slot:group for group in site_slots.values() for slot in group}
    assignments=collections.defaultdict(set)
    for slot,target in targets.items():assignments[target//64].add(slot)
    original={line:set(slots) for line,slots in assignments.items()}
    b.save(out/'protocol.json',dict(base=str(binary),base_sha256=audit['sha256'],source_sha256=b.sha(__file__),
        maximum_changed_slots=203,original_training_coverage_loss_limit_pp=1.0,minimum_new_residual_samples=8,
        rule='Use the first half of retained split75 residual observations per review MongoDB to select target replacements. At most 10% of hint slots, no extra instructions, fixed slot count at every call, no duplicate target line at a call. Preserve original train coverage within 1 percentage point. Never lose currently covered residual-train samples. Greedy largest new residual-sample coverage; each slot changes at most once. Only ages 64..8192 qualify.',
        validation='Second residual halves are a within-capture check, not independent heldout: aggregate residual diagnostics were already inspected. Original heldout is evaluated after choices freeze. Fresh E2E seeds and PMU provide separate validation.',
        limitation='Residual miss counts do not prove a missing fetch address; split continuation lines use the calibrated model. Retired age is not issue lead. Per-target dynamic frequency changes although total hint slots/executions and code layout are fixed.'))
    code=Code(binary);old_rows,old_inputs=original_rows(parent,'train',code)
    old_masks=mask_rows(old_rows,site_slots);old_count=coverage(old_masks,assignments)
    minimum=old_count-int(len(old_rows)*.01);old_samples=len(old_rows);del old_rows
    training=[];validation=[];inputs=[];anchors={}
    source=root/'residual_diagnostics/split75'
    assert json.loads((source/'analysis.json').read_text())['complete']
    for path in sorted(source.glob('*_observations.json.gz')):
        with gzip.open(path,'rt') as stream:rows=json.load(stream)
        midpoint=len(rows)//2;training.extend(rows[:midpoint]);validation.extend(rows[midpoint:])
        inputs.append(dict(path=str(path),sha256=b.sha(path),train=midpoint,check=len(rows)-midpoint))
        for row in rows[:midpoint]:anchors.setdefault(row['line'],row['target'])
    assert len(inputs)==2
    residual=mask_rows(training);residual_before=coverage(residual,assignments)
    heap=[]
    for line,slots in residual.items():
        already=union(residual,line,assignments[line])
        for slot,bits in slots.items():
            assert slot in targets
            gain=(bits&~already).bit_count()
            if gain>=8:heap.append((-gain,slot,line))
    heapq.heapify(heap);changes=[];changed=set();current_old=old_count
    while heap and len(changed)<203:
        _,slot,line=heapq.heappop(heap)
        if slot in changed or line==targets[slot]//64:continue
        if any(targets[s]//64==line for s in slot_groups[slot]):continue
        previous=targets[slot]//64
        before=union(residual,previous,assignments[previous])
        after=union(residual,previous,assignments[previous]-{slot})
        if before&~after:continue
        gain=(residual[line][slot]&~union(residual,line,assignments[line])).bit_count()
        if gain<8:continue
        if heap and (-gain,slot,line)>heap[0]:heapq.heappush(heap,(-gain,slot,line));continue
        lost=(union(old_masks,previous,assignments[previous])&~union(old_masks,previous,assignments[previous]-{slot})).bit_count()
        added=(old_masks.get(line,{}).get(slot,0)&~union(old_masks,line,assignments[line])).bit_count()
        if current_old-lost+added<minimum:continue
        changes.append(dict(slot=slot,previous=targets[slot],target=anchors[line],residual_gain=gain,original_lost=lost,original_added=added))
        assignments[previous].remove(slot);assignments[line].add(slot);targets[slot]=anchors[line]
        current_old+=added-lost;changed.add(slot)
    assert changes and coverage(old_masks,assignments)==current_old>=minimum
    frozen=dict(changes=changes,original_training_samples=old_samples,original_train_before=old_count,
        original_train_after=current_old,residual_train_samples=len(training),residual_train_before=residual_before,
        residual_train_after=coverage(residual,assignments),inputs=inputs,original_inputs=old_inputs)
    b.save(out/'selection_frozen.json',frozen)
    check_masks=mask_rows(validation)
    heldout,heldout_inputs=original_rows(parent,'heldout',code);heldout_masks=mask_rows(heldout,site_slots)
    selected=dict(frozen,residual_check_samples=len(validation),residual_check_before=coverage(check_masks,original),
        residual_check_after=coverage(check_masks,assignments),original_heldout_samples=len(heldout),
        original_heldout_before=coverage(heldout_masks,original),original_heldout_after=coverage(heldout_masks,assignments),
        original_heldout_inputs=heldout_inputs)
    b.save(out/'selection.json',selected)
    result=patch(binary,audit,targets,out,code)
    b.save(out/'complete.json',dict(result,valid=True));print(json.dumps(dict(result,selection={k:v for k,v in selected.items() if isinstance(v,int)})),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('parent',type=Path);parser.add_argument('root',type=Path)
    args=parser.parse_args();prepare(args.parent,args.root)
