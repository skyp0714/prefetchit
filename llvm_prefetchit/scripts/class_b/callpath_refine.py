#!/usr/bin/env python3
"""Reuse retained call-path observations for a higher-cover or earlier policy.

The first 50%-coverage screen remains frozen. A later policy needs more than
50% address/path cover to have room for late/dropped/evicted hints while aiming
for a 50% measured miss reduction. Selection uses training samples only.
"""
import argparse
import collections
import gzip
import json
from pathlib import Path
import struct
import dense_build as b
from callpath_prefetch import select,coverage,stubs
from dense_cause_analysis import Code,category
from e2e_lbr import remove_generated


def prepare(source,out,minimum=64,goal=.75,max_sites=1024,build=False,frequency_path=None,continuation_probe=None):
    assert (source/'complete.json').exists(),'Finish active call-path measurements first'
    assert minimum in (64,128,512,1024) and .5<=goal<=.9 and 1<=max_sites<=2048
    out.mkdir(parents=True,exist_ok=False);b.space(out)
    prior=json.loads((source/'prepared.json').read_text());reference=Path(prior['reference'])
    quality=json.loads((source/'profile_quality.json').read_text())
    assert b.sha(reference)==quality['reference_sha256']
    protocol=dict(source=str(source),reference=str(reference),reference_sha256=b.sha(reference),
        minimum_retired_age=minimum,maximum_retired_age=8192,coverage_goal=goal,max_sites=max_sites,
        max_hints=max_sites*4,per_site=4,min_gain=8,source_sha256=b.sha(__file__),
        selector_sha256=b.sha(Path(__file__).with_name('callpath_prefetch.py')),
        builder_sha256=b.sha(stubs.__file__),
        rule='Train-only greedy cover. Heldout is evaluated after freezing choices. This is a subsequent policy, not an amendment to completed screen arms.',
        limitation='Retired LBR age is not issue-to-fetch lead; selected cover is not measured miss elimination.')
    code=None
    if continuation_probe is not None:
        probe=Path(continuation_probe)
        assert json.loads((probe/'complete.json').read_text())['valid']
        observed={row['kind']:row['split_start_samples'] for row in json.loads((probe/'samples.json').read_text())}
        assert observed['nop']>100 and observed['first']>100 and observed['second']<.1*observed['first']
        protocol['target_model']=dict(probe=str(probe),sha256=b.sha(probe/'samples.json'),
            rule='For an instruction spanning 64-byte lines, use the next instruction start in its continuation line. Other targets unchanged. This is a modeled missing line, not a measured service fetch address. Train-only selection; heldout never selects targets.')
        code=Code(reference)
    b.save(out/'protocol.json',protocol)
    phases={};input_records=[]
    services=json.loads((source/'protocol.json').read_text())['training_services']
    for phase in ['train','heldout']:
        rows=[]
        # Keep the original sample ordering so each line's first valid target
        # instruction remains the same when only the lead/budget changes.
        for name in services:
            path=source/'observations'/(phase+'_'+name+'.json.gz')
            assert b.sha(path)==quality['records'][phase+':'+name]['observations_sha256']
            with gzip.open(path,'rt') as stream:observed=json.load(stream)
            requests=json.loads((source/'profiles'/phase/name/'request_window.json').read_text())['completed_requests']
            for row in observed:
                if code is not None:
                    length,_,_=code.get(row['ip']);assert length
                    if row['ip']//64!=(row['ip']+length-1)//64:
                        target=row['ip']+length;assert target in code.instructions
                        assert target//64==(row['ip']+length-1)//64
                        row.update(target=target,line=target//64)
                row['sites']=[site for site,ages in row['ages'] if any(minimum<=age<=8192 for age in ages)]
                row['miss_weight']=257/requests
            rows.extend(observed)
            input_records.append(dict(path=str(path),sha256=b.sha(path),samples=len(observed)))
        assert rows;phases[phase]=rows
    if frequency_path is None:
        chosen=select(phases['train'],max_sites=max_sites,max_hints=max_sites*4,goal=goal)
    else:
        from call_cost_selector import select as cost_select
        frequency=json.loads(Path(frequency_path).read_text())
        assert frequency['valid'] and frequency['reference_sha256']==b.sha(reference)
        assert set(frequency['records'])==set(services)
        rates=collections.Counter();floor=0
        for record in frequency['records'].values():
            assert record['valid']
            rates.update({int(site):value for site,value in record['direct_call_estimates'].items()})
            floor+=record['zero_sample_cost_floor_per_request']
        chosen=cost_select(phases['train'],rates,floor,max_sites=max_sites,max_hints=max_sites*4,goal=goal)
        chosen['frequency_source']=dict(path=str(frequency_path),sha256=b.sha(frequency_path),
            selector_sha256=b.sha(Path(__file__).with_name('call_cost_selector.py')))
    assert chosen['sites'] and chosen['hints']
    chosen['heldout']=coverage(phases['heldout'],chosen['choices'])
    chosen['inputs']=input_records
    # Preserve the selected-path age distribution, including older recurring
    # occurrences when a more recent occurrence is also visible.
    selected=collections.defaultdict(set)
    for row in chosen['choices']:selected[row['site']].add(row['target']//64)
    age_records={}
    for phase,rows in phases.items():
        near=collections.Counter();early=collections.Counter()
        for row in rows:
            ages=[age for site,values in row['ages'] if row['line'] in selected[site]
                  for age in values if minimum<=age<=8192]
            if not ages:continue
            def band(age):return '64-127' if age<128 else '128-511' if age<512 else '512-2047' if age<2048 else '2048-8192'
            near[band(min(ages))]+=1;early[band(max(ages))]+=1
        age_records[phase]=dict(nearest=dict(near),earliest=dict(early))
    chosen['selected_retired_ages']=age_records
    b.save(out/'selection.json',chosen)
    summary=dict(sites=chosen['sites'],hints=chosen['hints'],
        train_coverage=100*chosen['covered']/chosen['samples'],
        heldout_coverage=100*chosen['heldout']['covered']/chosen['heldout']['samples'])
    print(json.dumps(summary),flush=True)
    if not build:
        b.save(out/'plan_complete.json',dict(summary,compiled=False));return summary
    b.space(out)
    if code is None:code=Code(reference)
    raw=reference.read_bytes();elf=stubs.Elf(raw)
    targets=collections.defaultdict(list)
    for choice in chosen['choices']:targets[choice['site']].append(choice['target'])
    calls=[]
    for site,lines in sorted(targets.items()):
        length,asm,function=code.get(site)
        assert length==5 and category(asm)=='direct_call'
        offset=elf.offset(site,5,True);assert raw[offset]==0xe8
        callee=site+5+struct.unpack_from('<i',raw,offset+1)[0]
        assert callee in code.instructions and all(target in code.instructions for target in lines)
        calls.append(dict(site=site,callee=callee,targets=lines,expected=raw[offset:offset+5].hex(),
                          function=function,callee_function=code.get(callee)[2]))
    plan=dict(sha256=b.sha(reference),calls=calls);b.save(out/'build_plan.json',plan)
    binary=out/'build/mongod';b.space(out)
    record=stubs.build(reference,plan,binary,boundaries=code.instructions)
    del code
    try:
        verified=Code(binary)
        assert all(verified.raw_targets[h['va']]==h['target'] for h in record['hints'])
    except BaseException as error:
        b.save(out/'post_build_failure.json',dict(error=repr(error),binary_sha256=b.sha(binary),patches=str(binary)+'.json'))
        remove_generated([binary,Path(str(binary)+'.nop')],out/'post_build_cleanup.json',
            'Refinement failed post-build decoding; retain sources, plan, patches, hashes and error.')
        raise
    b.save(out/'prepared.json',dict(summary,binary=str(binary),nop=str(binary)+'.nop',reference=str(reference),
        extra_instruction_bytes=record['extra_instruction_bytes'],extra_mapped_bytes=record['extra_mapped_bytes']))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--minimum',type=int,default=64);p.add_argument('--goal',type=float,default=.75)
    p.add_argument('--max-sites',type=int,default=1024);p.add_argument('--build',action='store_true')
    p.add_argument('--frequency',type=Path);p.add_argument('--continuation-probe',type=Path);a=p.parse_args()
    prepare(a.source,a.out,a.minimum,a.goal,a.max_sites,a.build,a.frequency,a.continuation_probe)
