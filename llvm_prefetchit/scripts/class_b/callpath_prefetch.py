#!/usr/bin/env python3
"""Learn future miss targets at earlier direct calls, without moving old code."""
import argparse
import collections
import gzip
import heapq
import json
from pathlib import Path
import signal
import struct
import sys

import dense_build as b
from backend_prefetch import BACKENDS, observed_rows
from dense_cause_analysis import Code, category
from e2e_lbr import remove_generated
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
import call_stub_prefetch as stubs


def select(rows, max_sites=256, max_hints=1024, per_site=4, min_gain=8, goal=.5):
    """Lazy greedy sampled-miss cover; bound both dispatch sites and hint count.

    Counts are conditional on sampled misses. They are not branch probabilities
    or expected hardware hint accuracy. Fresh whole-stack timing prices both the
    extra direct jump and hints against a same-layout NOP twin.
    """
    candidates=collections.defaultdict(set); anchors={}
    for index,row in enumerate(rows):
        anchors.setdefault(row['line'],row['target'])
        for site in row['sites']:
            candidates[site,row['line']].add(index)
    candidates={pair:ids for pair,ids in candidates.items() if len(ids)>=min_gain}
    heap=[(-len(ids),site,line) for (site,line),ids in candidates.items()]
    heapq.heapify(heap); covered=set(); chosen=[]; sites=collections.Counter()
    while heap and len(chosen)<max_hints and len(covered)<goal*len(rows):
        _,site,line=heapq.heappop(heap)
        if sites[site]>=per_site or (not sites[site] and len(sites)>=max_sites):continue
        ids=candidates[site,line]; gain=len(ids-covered)
        if gain<min_gain:continue
        # Stale scores are upper bounds; refresh until the popped pair is best.
        current=(-gain,site,line)
        if heap and current>heap[0]:
            heapq.heappush(heap,current);continue
        chosen.append(dict(site=site,target=anchors[line],gain=gain,observations=len(ids)))
        sites[site]+=1;covered.update(ids)
    return dict(choices=chosen,sites=len(sites),hints=len(chosen),covered=len(covered),samples=len(rows),
                settings=dict(max_sites=max_sites,max_hints=max_hints,per_site=per_site,min_gain=min_gain,goal=goal),
                rule='Greedy independent line coverage, at most four targets per earlier executed call; stop at 50% sampled training cover or fixed budget.')


def coverage(rows,choices):
    selected=collections.defaultdict(set)
    for c in choices:selected[c['site']].add(c['target']//64)
    return dict(samples=len(rows),covered=sum(any(row['line'] in selected[s] for s in row['sites']) for row in rows),
                eligible=sum(bool(row['sites']) for row in rows))


def prepare(spec):
    root=Path(spec['root']);binary=Path(spec['reference']);b.space(root)
    b.save(root/'prepare_protocol.json',dict(spec,source_sha256=b.sha(__file__),builder_sha256=b.sha(stubs.__file__),
        observations_sha256=b.sha(Path(__file__).with_name('backend_prefetch.py')),
        rules='Training only: earlier direct calls 64..8192 retired-cycle proxy; 50% main-sample coverage goal; primary <=256 sites/1024 hints, optional wide <=1024 sites/4096 hints if primary misses 50% and wide adds >=5 points; <=4 per site, gain >=8. Heldout is reported, not used to select placements.',
        costs='Original code unchanged except call displacement. New leaf stubs add hints and one direct jump. NOP twin retains this jump and full appended layout.'))
    print(json.dumps(dict(stage='decode_original',binary=str(binary))),flush=True)
    code=Code(binary);raw=binary.read_bytes();elf=stubs.Elf(raw);calls={}
    for site,(length,asm,_) in code.instructions.items():
        if length!=5 or category(asm)!='direct_call':continue
        off=elf.offset(site,5,True)
        if raw[off]!=0xe8:continue
        callee=site+5+struct.unpack_from('<i',raw,off+1)[0]
        if callee not in code.instructions:continue
        calls[site]=dict(site=site,callee=callee,expected=raw[off:off+5].hex(),
            function=code.get(site)[2],callee_function=code.get(callee)[2])
    assert calls
    print(json.dumps(dict(stage='call_inventory',sites=len(calls))),flush=True)
    phases={};quality={};obsolete=[]
    for phase in ['train','heldout']:
        rows=[]
        for name in spec.get('services',BACKENDS):
            folder=root/'profiles'/phase/name
            observed,counts=observed_rows(folder,code,calls,minimum=64,maximum=8192)
            recorded=json.loads((folder/'record_types.json').read_text())['SAMPLE']
            assert counts['all_samples']==recorded and recorded>100
            dest=root/'observations'/(phase+'_'+name+'.json.gz');dest.parent.mkdir(exist_ok=True)
            with gzip.open(dest,'wt') as f:json.dump(observed,f,separators=(',',':'))
            quality[phase+':'+name]=dict(counts,observations_sha256=b.sha(dest),decoded_sha256=b.sha(folder/'samples.txt'))
            rows.extend(observed);obsolete.append(folder/'samples.txt')
            print(json.dumps(dict(stage='observations',phase=phase,service=name,all_samples=recorded,
                main_samples=counts['main_samples'],eligible=counts['eligible_samples'])),flush=True)
        phases[phase]=rows
    b.save(root/'profile_quality.json',dict(records=quality,call_sites=len(calls),reference_sha256=b.sha(binary)))
    remove_generated(obsolete,root/'decoded_cleanup.json','Direct-call observations, ages, denominators and source hashes retained; decoded traces no longer needed.')
    selections={'call256':select(phases['train'])}
    frequencies=collections.Counter(row['line'] for row in phases['train'])
    ranked=sorted(frequencies.values(),reverse=True)
    b.save(root/'address_budget_bound.json',dict(samples=len(phases['train']),unique_lines=len(frequencies),
        unrestricted_top_line_coverage={n:sum(ranked[:n])/len(phases['train']) for n in [64,256,512,1024,2048,4096,8192]},
        limitation='Optimistic sampled address coverage without placement, dynamic issue, lead-time or cache-residency constraints. Not a predicted hardware miss reduction.'))
    low=selections['call256']
    if low['covered']<.5*low['samples']:
        wide=select(phases['train'],max_sites=1024,max_hints=4096)
        b.save(root/'wide_selection_considered.json',wide)
        # Add a separate density arm only when training cover grows >=5 points.
        # No heldout sample or performance outcome participates in this rule.
        if wide['covered']-low['covered']>=.05*low['samples']:selections['call_wide']=wide
    prepared={};records={}
    for name,chosen in selections.items():
        chosen.update(heldout=coverage(phases['heldout'],chosen['choices']),
            train_all_samples=sum(v['all_samples'] for k,v in quality.items() if k.startswith('train:')),
            heldout_all_samples=sum(v['all_samples'] for k,v in quality.items() if k.startswith('heldout:')))
        b.save(root/(name+'_selection.json'),chosen)
        assert chosen['sites'] and chosen['hints']
        print(json.dumps(dict(stage='selected',policy=name,sites=chosen['sites'],hints=chosen['hints'],train_covered=chosen['covered'],
            train_samples=chosen['samples'],heldout=chosen['heldout'])),flush=True)
        grouped=collections.defaultdict(list)
        for row in chosen['choices']:grouped[row['site']].append(row['target'])
        plan=dict(sha256=b.sha(binary),calls=[dict(calls[site],targets=targets) for site,targets in sorted(grouped.items())])
        b.save(root/(name+'_build_plan.json'),plan)
        output=root/'builds'/name/'mongod';b.space(root)
        records[name]=stubs.build(binary,plan,output,boundaries=code.instructions)
        prepared[name]=dict(binary=str(output),nop=str(output)+'.nop',reference=str(binary),
            sites=chosen['sites'],hints=chosen['hints'],train_coverage=100*chosen['covered']/chosen['samples'],
            heldout_coverage=100*chosen['heldout']['covered']/chosen['heldout']['samples'],
            extra_instruction_bytes=records[name]['extra_instruction_bytes'],extra_mapped_bytes=records[name]['extra_mapped_bytes'])
    # Verify each final ELF after freeing the original decoded instruction map.
    del code
    for name,record in records.items():
        output=Path(prepared[name]['binary'])
        try:
            verified=Code(output)
            assert all(verified.raw_targets[h['va']]==h['target'] for h in record['hints'])
            del verified
        except BaseException as error:
            b.save(root/(name+'_post_build_failure.json'),dict(error=repr(error),binary_sha256=b.sha(output),
                nop_sha256=b.sha(str(output)+'.nop'),patch_record=str(output)+'.json'))
            remove_generated([output,Path(str(output)+'.nop')],root/(name+'_post_build_cleanup.json'),
                'Generated call-stub ELF did not pass full post-build decoding. Source, patches, hashes and error retained.')
            raise
    b.save(root/'prepared.json',dict(reference=str(binary),candidates=prepared,
        residual_candidate=max(prepared,key=lambda n:prepared[n]['train_coverage']),
        density_rule='Primary <=256 sites/1024 hints. If train coverage <50%, consider <=1024 sites/4096 hints; build only if training cover rises >=5 percentage points. Four hints/site maximum. Separate NOP twin per policy.'))


def residual_counts(rows,hints):
    lines={target//64 for target in hints.values()}
    def band(age):return '0-63' if age<64 else '64-127' if age<128 else '128-511' if age<512 else '512-2047' if age<2048 else '2048-8192'
    counts=collections.Counter();nearest=collections.Counter();earliest=collections.Counter()
    for row in rows:
        counts['main_samples']+=1;counts['on_selected_target_line']+=row['line'] in lines
        ages=[age for site,values in row['ages'] if hints[site]//64==row['line'] for age in values]
        if not ages:
            counts['no_matching_hint_observed']+=1;continue
        counts['matching_hint_observed']+=1
        counts['matching_hint_age_ge64']+=max(ages)>=64
        counts['matching_hint_age_ge512']+=max(ages)>=512
        nearest[band(min(ages))]+=1;earliest[band(max(ages))]+=1
    return dict(counts),dict(nearest),dict(earliest)


def residual(spec):
    """Distinguish uncovered lines from misses after an observed matching hint.

    Added branches shorten the LBR's effective path span. Absence from the finite
    history is not evidence that no hint ran; retirement age is not issue lead.
    """
    root=Path(spec['root']);binary=Path(spec['binary']);folder=root/'residual'
    assert json.loads((folder/'complete.json').read_text())['valid'];b.space(root)
    code=Code(binary);patches=json.loads(Path(str(binary)+'.json').read_text())
    hints={row['va']:row['target'] for row in patches['hints']}
    assert b.sha(binary)==patches['sha256'] and all(code.raw_targets[s]==t for s,t in hints.items())
    lines={t//64 for t in hints.values()};results={}
    for name in spec['services']:
        source=folder/name
        rows,quality=observed_rows(source,code,hints,minimum=0,maximum=8192)
        recorded=json.loads((source/'record_types.json').read_text())['SAMPLE']
        assert recorded==quality['all_samples'] and recorded>100
        observations=root/'residual_observations'/(name+'.json.gz');observations.parent.mkdir(exist_ok=True)
        with gzip.open(observations,'wt') as stream:json.dump(rows,stream,separators=(',',':'))
        counts,nearest,earliest=residual_counts(rows,hints)
        requests=json.loads((source/'request_window.json').read_text())
        with gzip.open(root/'observations'/('heldout_'+name+'.json.gz'),'rt') as stream:baseline=json.load(stream)
        base_requests=json.loads((root/'profiles/heldout'/name/'request_window.json').read_text())
        baseline_counts=dict(main_samples=len(baseline),on_selected_target_line=sum(row['line'] in lines for row in baseline))
        results[name]=dict(quality=quality,counts=dict(counts),nearest_retired_age=dict(nearest),earliest_retired_age=dict(earliest),
            estimated_events_per_request={k:v*257/requests['completed_requests'] for k,v in counts.items()},
            baseline_heldout=dict(counts=baseline_counts,request_window=base_requests,
                estimated_events_per_request={k:v*257/base_requests['completed_requests'] for k,v in baseline_counts.items()}),
            request_window=requests,observations_sha256=b.sha(observations),decoded_sha256=b.sha(source/'samples.txt'))
        b.save(root/'residual_analysis.json',dict(binary_sha256=b.sha(binary),records=results,
            source_sha256=b.sha(__file__),complete=len(results)==len(spec['services']),
            limitation='Separate diagnostic seeds/windows, no E2E inference. Missing matching hints may lie beyond finite LBR history, whose span changes with added branches. Retired age is not issue-to-fetch time. A remaining target miss does not alone distinguish late issue, dropped hint, or eviction.'))
        remove_generated([source/'samples.txt'],source/'residual_cleanup.json',
            'Complete sparse residual observations, hint-age counts, request denominators and hashes retained; decoded trace no longer needed.')
        print(json.dumps(dict(service=name,counts=dict(counts),estimated_events_per_request=results[name]['estimated_events_per_request'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('spec',type=Path);parser.add_argument('--residual',action='store_true');args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);(residual if args.residual else prepare)(json.loads(args.spec.read_text()))
