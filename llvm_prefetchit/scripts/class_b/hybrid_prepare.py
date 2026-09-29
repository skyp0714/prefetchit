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
    # Freeze the corrected continuation-line policy before hybrid timing.
    # The old uncorrected policy stays in the preceding independent screen.
    correction=parent/'split_target_refine';assert (correction/'complete.json').exists()
    cost=json.loads((correction/'prepared.json').read_text());base_name='cost75_split'
    assert b.sha(cost['binary'])==cost['sha256']
    prior=json.loads(Path(cost['binary']+'.json').read_text())
    from dense_cause_analysis import Code
    code=Code(prepared['reference'])
    calls=prior['plan']['calls'];sites={row['site'] for row in calls};scores=collections.defaultdict(collections.Counter);anchors={}
    observation_files=sorted((parent/'callpath/observations').glob('train_*.json.gz'));assert len(observation_files)==3
    for path in observation_files:
        with gzip.open(path,'rt') as stream:rows=json.load(stream)
        for row in rows:
            length,_,_=code.get(row['ip']);assert length
            if row['ip']//64!=(row['ip']+length-1)//64:
                target=row['ip']+length;assert target in code.instructions
                row=dict(row,line=target//64,target=target)
            anchors.setdefault(row['line'],row['target'])
            for site in set(row['sites'])&sites:scores[site][row['line']]+=1
    del code
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
        base_name=base_name,base_sha256=cost['sha256'],
        selection='Retain every corrected cost75_split T1 placement. At its first qualifying scheduler epoch, issue its T1 target set as IT0, then extend to at most eight unique target lines ranked by training miss observations at the same earlier call. Split instructions use the next real instruction start in their continuation line. Heldout and performance are not used to select targets.',
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
        result=dict(reference=prepared['reference'],cost75=cost,base_name=base_name,hybrid=str(main),nop=str(main)+'.nop',
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


def sparse(prepared,diagnostic,root,max_groups=64,coverage=.9):
    """Use independent gate diagnostics, never E2E results, to reduce guards."""
    root.mkdir(parents=True,exist_ok=False);b.space(root)
    main=Path(prepared['hybrid']);audit=json.loads(Path(str(main)+'.json').read_text())
    observed=json.loads(Path(diagnostic).read_text());assert observed['valid']
    scores=collections.defaultdict(lambda:[0]*4)
    for service in ['user-review-mongodb','movie-review-mongodb','review-storage-mongodb']:
        for index,counts in observed['site_delta'][service].items():
            assert all(n>=0 for n in counts)
            for i,value in enumerate(counts):scores[int(index)][i]+=value
    total=sum(values[1] for values in scores.values());assert total>0
    chosen=[];covered=0
    for index,values in sorted(scores.items(),key=lambda item:(-item[1][1],item[0])):
        if not values[1] or len(chosen)>=max_groups or covered>=coverage*total:break
        chosen.append(index);covered+=values[1]
    assert chosen
    groups=audit['hybrid']['site_groups'];wanted={site for group in groups if group['index'] in chosen for site in group['sites']}
    plan=dict(audit['plan'],calls=[dict(row,hybrid_gate=row['site'] in wanted) for row in audit['plan']['calls']])
    b.save(root/'plan.json',plan)
    b.save(root/'selection.json',dict(diagnostic=str(diagnostic),diagnostic_sha256=b.sha(diagnostic),
        max_groups=max_groups,coverage_goal=coverage,selected_groups=chosen,selected_calls=len(wanted),
        observed_bursts=total,retained_observed_bursts=covered,retained_burst_fraction=covered/total,
        checks_all=sum(observed['delta'][service]['checks'] for service in ['user-review-mongodb','movie-review-mongodb','review-storage-mongodb']),
        per_site_checks='Not collected. Atomic per-site counters record infrequent first-epoch outcomes only; the total hot-path check counter is per CPU.',
        site_counts=dict(scores),source_sha256=b.sha(__file__),
        rule='At most 64 canonical stub groups, ranked by observed first-epoch burst count, stopping at 90% of those bursts. All other selected calls keep plain T1 with no RDPID, clock read or gate.',
        limitation='Counts come from a separate intrusive diagnostic. Removing gates can move the first retained gate later; a second diagnostic checks actual activity, without reselection. Original application addresses and all ordinary T1 target lists remain unchanged.'))
    try:
        result={}
        for name,diagnostic_mode in [('sparse',False),('sparse_diag',True)]:
            output=root/'builds'/name/'mongod'
            record=stubs.build(prepared['reference'],plan,output,hybrid=dict(diagnostic=diagnostic_mode))
            result[name]=dict(binary=str(output),nop=str(output)+'.nop',sha256=record['sha256'],nop_sha256=record['nop_sha256'],
                extra_instruction_bytes=record['extra_instruction_bytes'],extra_mapped_bytes=record['extra_mapped_bytes'],
                gated_groups=sum(g['gated'] for g in record['hybrid']['site_groups']))
        b.save(root/'prepared.json',result)
        remove_generated([Path(result['sparse_diag']['nop'])],root/'unused_diagnostic_nop_cleanup.json',
            'Sparse gate diagnostic has no E2E role; retain source and audit before removing its unused NOP executable.')
        return result
    except BaseException as error:
        b.save(root/'failure.json',dict(error=repr(error)))
        paths=[p for p in (root/'builds').rglob('*') if p.is_file() and not p.is_symlink() and p.name in ['mongod','mongod.nop']]
        remove_generated(paths,root/'failed_sparse_cleanup.json','Sparse hybrid preparation rejected; plans, source, patches and failure retained.')
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);p.add_argument('root',type=Path);a=p.parse_args();prepare(a.parent,a.root)
