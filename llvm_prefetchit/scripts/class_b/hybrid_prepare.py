#!/usr/bin/env python3
"""Build a bounded first-epoch IT0 burst followed by the retained T1 policy."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import struct
import sys
import dense_build as b
from e2e_lbr import remove_generated
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
import call_stub_prefetch as stubs


def opcode_control(source,dest,early='it0',later='t1'):
    source,dest=Path(source),Path(dest);assert not dest.exists()
    audit=json.loads(Path(str(source)+'.json').read_text());data=bytearray(source.read_bytes())
    assert stubs.sha(data)==audit['sha256'];changes=[];hints=[]
    for hint in audit['hints']:
        offset=hint['offset'];before=bytes(data[offset:offset+7]);assert before.hex()==hint['original']
        kind=early if hint['kind']=='it0' else later
        assert kind in ['it0','t1','nop']
        after=stubs.NOP7 if kind=='nop' else before[:2]+bytes([0x3d if kind=='it0' else 0x15])+before[3:]
        if before!=after:changes.append(dict(offset=offset,before=before.hex(),after=after.hex()))
        data[offset:offset+7]=after;hints.append(dict(hint,original=after.hex(),kind=kind))
    reversed_data=bytearray(data)
    for change in changes:
        o=change['offset'];reversed_data[o:o+7]=bytes.fromhex(change['before'])
    assert stubs.sha(reversed_data)==audit['sha256']
    dest.parent.mkdir(parents=True,exist_ok=True);b.space(dest.parent)
    record=dict(audit,hints=hints,sha256=stubs.sha(data),opcode_control=dict(source=str(source),
        source_sha256=audit['sha256'],early=early,later=later,changes=changes,only_audited_hint_bytes_changed=True))
    b.save(Path(str(dest)+'.json'),record);dest.write_bytes(data);dest.chmod(0o755)
    assert b.sha(dest)==record['sha256']
    return str(dest)


def prepare(parent,root,burst=8):
    assert burst in [8,16]
    root.mkdir(parents=True,exist_ok=False);b.space(root)
    prepared=json.loads((parent/'callpath_coverage75/prepared.json').read_text())
    cost=prepared['candidates']['cost75'];prior=json.loads(Path(cost['binary']+'.json').read_text())
    calls=prior['plan']['calls'];sites={row['site'] for row in calls};scores=collections.defaultdict(collections.Counter);anchors={}
    observation_files=sorted((parent/'callpath/observations').glob('train_*.json.gz'));assert len(observation_files)==3
    for path in observation_files:
        with gzip.open(path,'rt') as stream:rows=json.load(stream)
        for row in rows:
            anchors.setdefault(row['line'],row['target'])
            for site in set(row['sites'])&sites:scores[site][row['line']]+=1
    plan=dict(prior['plan'],calls=[])
    for old in calls:
        targets=list(old['targets']);lines={target//64 for target in targets}
        for line,score in sorted(scores[old['site']].items(),key=lambda pair:(-pair[1],pair[0])):
            if len(targets)>=burst:break
            if line not in lines:targets.append(anchors[line]);lines.add(line)
        plan['calls'].append(dict(old,burst_targets=targets))
    b.save(root/'plan.json',plan)
    b.save(root/'protocol.json',dict(burst_cap=burst,source_sha256=b.sha(__file__),
        training=[dict(path=str(p),sha256=b.sha(p)) for p in observation_files],
        selection='Retain every cost75 T1 placement. At its first qualifying scheduler epoch, issue its T1 target set as IT0, then extend to at most eight unique target lines ranked by training miss observations at the same earlier call. Heldout and performance are not used to select targets.',
        timing='Only the first observed instrumented call per CPU epoch before dense_us; remaining calls use T1. Shared seen-epoch state suppresses subsequent bursts. RDTSCP checks current CPU, epoch and deadline.',
        limitations='No fetch-queue occupancy observation. Saved scheduler time precedes architectural switch; first inserted call can be later than first user instruction. Preemption/migration races affect only hint quality.',
        controls='Exact-layout all-NOP and early-T1/later-T1 controls retain guards, shared mapping, timing logic, branches and unwind records. Original and unguarded cost75 are separate references.'))
    records={}
    try:
        for name,diagnostic in [('hybrid8',False),('hybrid8_diag',True)]:
            output=root/'builds'/name/'mongod';b.space(root)
            records[name]=stubs.build(prepared['reference'],plan,output,hybrid=dict(diagnostic=diagnostic))
        main=root/'builds/hybrid8/mongod'
        early_t1=opcode_control(main,root/'builds/early_t1/mongod',early='t1')
        # A burst-only arm can be activated as a follow-up without rebuilding.
        # Do not create its ELF until that comparison is actually scheduled.
        result=dict(reference=prepared['reference'],cost75=cost,hybrid=str(main),nop=str(main)+'.nop',
            early_t1=early_t1,diagnostic=str(root/'builds/hybrid8_diag/mongod'),burst_cap=burst,
            sites=len(calls),burst_hints=sum(len(r['burst_targets']) for r in plan['calls']),
            records={name:{key:record[key] for key in ['sha256','nop_sha256','extra_instruction_bytes','extra_mapped_bytes','hybrid']} for name,record in records.items()})
        b.save(root/'prepared.json',result)
        diagnostic_nop=Path(result['diagnostic']+'.nop')
        remove_generated([diagnostic_nop],root/'unused_diagnostic_nop_cleanup.json',
            'Diagnostic counters are excluded from E2E; the separate diagnostic NOP is unused. Preserve builder audit and hashes.')
        return result
    except BaseException as error:
        b.save(root/'failure.json',dict(error=repr(error)))
        paths=[p for p in (root/'builds').rglob('*') if p.is_file() and not p.is_symlink() and p.name in ['mongod','mongod.nop']]
        remove_generated(paths,root/'failed_prepare_cleanup.json','Hybrid preparation rejected; source, plans, patches and failure retained.')
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);p.add_argument('root',type=Path);a=p.parse_args();prepare(a.parent,a.root)
