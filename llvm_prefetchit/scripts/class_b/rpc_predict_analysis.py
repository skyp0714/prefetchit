#!/usr/bin/env python3
"""Classify held-out RPC residuals using recorded ELF identities and patch ranges."""
import argparse
import bisect
import collections
from pathlib import Path

import dense_build as b
from rpc_route_study import load
from temporal_path_analysis import read
from temporal_path_common import EDGES
from dense_cause_analysis import Code, category


def analyze(root):
    assert load(root/'measurement_complete.json')['valid'], 'Analysis runs after timing/capture'
    refs=load(root/'references.json');arms=load(root/'arms.json');known={}
    base=refs['previous']['arm']
    paths=set(base['overrides'].values())|{base['mongo_binary']}
    for lib in base.get('libraries',{}).values():paths.update(lib.values())
    for source in paths:
        record=load(Path(source+'.json'));known[record['sha256']]=record
    for path in (root/'builds').rglob('*.json'):
        record=load(path)
        if 'hints' in record:known[record['sha256']]=record
    def canonical(digest):
        seen=set()
        while digest in known:
            assert digest not in seen;seen.add(digest);digest=known[digest]['source_sha256']
        return digest
    def chain(digest):
        seen=set()
        while digest in known:
            assert digest not in seen;seen.add(digest)
            record=known[digest];yield record;digest=record['source_sha256']
    # Decode retained incumbent images: original instruction lengths and all
    # incumbent stubs remain identical in the newly appended variants.
    decode_sources={canonical(load(Path(p+'.json'))['sha256']):Path(p) for p in paths}
    decoded={}
    def instruction_info(data,index,ip):
        if index<0:return 0,'unknown'
        digest=data['digests'][index]
        path=decode_sources.get(canonical(digest),Path(data['catalog'][data['names'][index]]['binary']))
        if path not in decoded:decoded[path]=Code(path)
        length,asm,_=decoded[path].get(ip)
        if length:return length,category(asm)
        # The newly appended regions may already have been retired. Recognize
        # their fixed-size hint/NOP slots and jumps from retained patch records.
        for record in chain(digest):
            if 'variant' not in record:continue
            for patch in record['patches']:
                if ip in patch['terminal_jumps']:return 5,'direct_jump'
                if any(ip==patch['stub']+7*rank for rank in range(len(patch['targets']))):
                    return 7,'prefetch' if ip in {h['va'] for h in record['hints']} else 'other'
        return 0,'unknown'
    selected={s:{t//64 for c in row['choices'] for t in c['targets']} for s,row in load(root/'model.json').items()}
    wide_selected={s:{t//64 for c in row['choices'] for t in c['targets']} for s,row in load(root/'wide_model.json').items()} if (root/'wide_model.json').exists() else {}
    span_selected={s:{t//64 for c in row['choices'] for t in c['targets']} for s,row in load(root/'wide_span_model.json').items()} if (root/'wide_span_model.json').exists() else {}
    reply_selected={s:{t//64 for c in row['choices'] for t in c['targets']} for s,row in load(root/'reply_model.json').items()} if (root/'reply_model.json').exists() else {}
    reply_union={s:selected.get(s,set())|reply_selected.get(s,set()) for s in set(selected)|set(reply_selected)}
    output={};sources={}
    phases=[(p,'apps') for p in sorted((root/'profiles').iterdir())]
    if (root/'mongo_profiles').exists():phases += [(p,'mongo') for p in sorted((root/'mongo_profiles').iterdir())]
    for phase,scope in phases:
        if not phase.is_dir() or not (phase/'complete.json').exists():continue
        protocol=load(phase/'protocol.json');name=protocol['arm']
        label=protocol.get('analysis_label',name);phase_key=label if scope=='apps' else 'mongo_'+label
        assert phase_key not in output, ('duplicate profile key',phase_key)
        aggregate=collections.Counter();locations=collections.Counter();targeted=collections.Counter()
        span_counts=collections.Counter();span_fixed=collections.Counter();span_geometry=collections.Counter()
        instruction_kinds=collections.Counter();witness_gaps=collections.Counter();witness_recovery=collections.Counter()
        ages=[collections.Counter() for _ in range(len(EDGES))];exposures=[0.0]*len(EDGES);events=[0.0]*len(EDGES)
        services={};branch=collections.Counter();origins=collections.Counter()
        origin_ages=collections.defaultdict(lambda:[collections.Counter() for _ in EDGES])
        selected_ages=[0.0]*len(EDGES)
        for path in sorted(phase.glob('*/l2/observations.json.gz')):
            data=read(path);service=data['service'];weight=data['period']/data['requests']
            executable=arms[name]['mongo_binary'] if scope=='mongo' else arms[name]['overrides'][service]
            main=data['names'].index(next(n for n in data['names'] if Path(n).name==Path(executable).name))
            origins_by_sha={canonical(d):i for i,d in enumerate(data['digests'])}
            lines=collections.defaultdict(set);ranges=collections.defaultdict(list);jumps={}
            for i,digest in enumerate(data['digests']):
                for record in chain(digest):
                    is_new='variant' in record
                    enabled={h['va'] for h in record['hints']}
                    for patch in record['patches']:
                        reached=set()
                        # New policy has ordinary seven-byte RIP-relative hints;
                        # disabled slots are intentionally absent from active targets.
                        for rank,target in enumerate(patch['targets']):
                            if not is_new or patch['stub']+7*rank in enabled:reached.add((i,target//64))
                        for target in patch.get('got_targets',[]):
                            dest=origins_by_sha.get(canonical(target['target_sha']))
                            if dest is not None:reached.add((dest,target['target']//64))
                        for dest,line in reached:lines[dest].add(line)
                        for jump in patch['terminal_jumps']:jumps[i,jump]=reached
                        ranges[i].append((patch['stub'],max(patch['terminal_jumps'])+5,'new_stub' if is_new else 'incumbent_stub'))
            counts=collections.Counter();local_ages=[collections.Counter() for _ in range(len(EDGES))]
            targets=collections.Counter();sample_locations=collections.Counter()
            for row in data['rows']:
                i=row['dso'];ip=row['ip'];line=ip//64;age=max(0,bisect.bisect_right(EDGES,row['age_us'])-1)
                segment='main' if i==main else 'dso' if i>=0 else 'unmapped'
                in_stub=next((kind for lo,hi,kind in ranges.get(i,[]) if lo<=ip<hi),None)
                history=row['edges']
                if history and tuple(history[0][:2])==(i,ip):history=history[1:]
                witnessed=any((i,line) in jumps.get(tuple(edge[:2]),set()) for edge in history)
                if line in lines[i] and not in_stub:
                    gap=0;usable=True;mispredicted=False;found=False
                    for edge in history:
                        if (i,line) in jumps.get(tuple(edge[:2]),set()):
                            key='unavailable_cycles'
                            if usable:
                                key=next((f'{lo}_{hi}' for lo,hi in zip((0,64,256,1024,4096),(64,256,1024,4096,16384)) if lo<=gap<hi),'16384_plus')
                            witness_gaps[key]+=weight
                            witness_recovery['mispredicted_branch_in_between' if mispredicted else 'no_misprediction_flag_in_between']+=weight
                            found=True;break
                        mispredicted |= edge[4]=='M'
                        cycles=edge[5]
                        if cycles is None or cycles>=65535:usable=False
                        elif usable:gap+=cycles
                    if not found:witness_gaps['no_bounded_witness']+=weight
                if in_stub:cls=in_stub
                elif line in lines[i]:cls='targeted_with_lbr_witness' if witnessed else 'targeted_no_bounded_witness'
                else:cls='not_targeted'
                if i<0:cls='unmapped'
                counts[cls]+=weight;counts['all']+=weight;counts['image_'+segment]+=weight
                local_ages[age][cls]+=weight;sample_locations[segment,i,line,cls]+=weight
                if i==main and line in selected.get(service,set()):
                    targets['selected_lines']+=weight;selected_ages[age]+=weight
                if i==main and line in wide_selected.get(service,set()):targets['wide_selected_lines']+=weight
                if i==main and line in span_selected.get(service,set()):targets['span_selected_lines']+=weight
                if i==main and line in reply_selected.get(service,set()):targets['reply_selected_lines']+=weight
                if i==main and line in reply_union.get(service,set()):targets['incoming_and_reply_lines']+=weight
                if i==main:targets['main_all']+=weight
                length,kind=instruction_info(data,i,ip);instruction_kinds[kind]+=weight
                last=(ip+length-1)//64 if length else line
                span_geometry['decoded' if length else 'undecoded']+=weight
                if last!=line:
                    span_geometry['straddling']+=weight
                    first_targeted=line in lines[i];last_targeted=last in lines[i]
                    key='both_targeted' if first_targeted and last_targeted else 'first_only_targeted' if first_targeted else 'last_only_targeted' if last_targeted else 'neither_targeted'
                    span_geometry[key]+=weight
                if i<0:span_class='unmapped'
                elif in_stub:span_class=in_stub
                elif last not in lines[i]:span_class='not_targeted'
                else:
                    span_witness=any((i,last) in jumps.get(tuple(edge[:2]),set()) for edge in history)
                    span_class='targeted_with_lbr_witness' if span_witness else 'targeted_no_bounded_witness'
                span_counts[span_class]+=weight;span_counts['all']+=weight
                if i==main:
                    for key,sets in [('selected_lines',selected),('wide_selected_lines',wide_selected),
                                     ('span_selected_lines',span_selected),('reply_selected_lines',reply_selected),
                                     ('incoming_and_reply_lines',reply_union)]:
                        if last in sets.get(service,set()):span_fixed[key]+=weight
                if history and history[0][2]==i and 0<=ip-history[0][3]<64:
                    branch['within_64B_after_taken']+=weight
                    branch['prediction_'+history[0][4]]+=weight
                origins[row['origin']]+=weight
            timeline=load(path.with_name('timeline.json'))
            for index,v in enumerate(timeline['bins']):
                exposures[index]+=v['exposure_us'];events[index]+=v['estimated_events']
            for origin,origin_data in timeline['origins'].items():
                for index,v in enumerate(origin_data['bins']):
                    origin_ages[origin][index].update(dict(estimated_events=v['estimated_events'],
                        exposure_us=v['exposure_us'],events_per_request=v['estimated_events']/data['requests']))
            aggregate.update(counts);targeted.update(targets)
            for i,c in enumerate(local_ages):ages[i].update(c)
            services[service]=dict(samples=len(data['rows']),per_request=dict(counts),selected_target_events_per_request=dict(targets),
                quality=timeline['quality'],requests=data['requests'],profile_sha256=b.sha(path),
                schedule={k:timeline.get(k) for k in ('runs_with_prior_out','migrated_pct','median_run_us','median_off_us')})
            sources[str(path)]=b.sha(path)
            for (segment,i,line,cls),value in sample_locations.items():
                locations[service,segment,data['names'][i] if i>=0 else 'unknown',line,cls]+=value
        address_counts=collections.Counter()
        for (service,segment,image,line,classification),value in locations.items():
            address_counts[service,image,line]+=value
        ranked=address_counts.most_common();cumulative=0;coverage_counts={}
        for index,(_,value) in enumerate(ranked,1):
            cumulative+=value
            for fraction in (.5,.9):
                if cumulative>=fraction*aggregate['all']:coverage_counts.setdefault(str(fraction),index)
        concentration=dict(observed_service_image_lines=len(address_counts),
            top_line_share_pct={str(k):100*sum(v for _,v in ranked[:k])/aggregate['all'] for k in (1,10,50,100,500)},
            lines_for_observed_mass=coverage_counts,
            interpretation='Request-normalized sample weights; each service/image/starting cache line counted once after merging witness classes. Sampling concentration, not a true full-run footprint or prefetch performance ceiling.')
        output[phase_key]=dict(scope=scope,policy=name,services=services,per_request=dict(aggregate),selected_target_events_per_request=dict(targeted),
            sampled_address_concentration=concentration,
            sample_instruction_kind_per_request=dict(instruction_kinds),
            targeted_retired_lbr_gap_per_request=dict(witness_gaps),
            targeted_witness_recovery_per_request=dict(witness_recovery),
            lbr_gap_limitation='Sum of available, nonsaturated retired LBR cycle fields between the witnessed stub terminal branch and the newest retired branch. The newest branch-to-sample gap and prefetch-to-terminal-branch gap are unknown; fetch/retirement overlap prevents interpreting this as hardware prefetch lead time. No bounded witness and unusable cycle fields are explicit. Only statically targeted non-stub sampled starting lines are included.',
            continuation_line_model=dict(per_request=dict(span_counts),selected_target_events_per_request=dict(span_fixed),geometry_per_request=dict(span_geometry),
                interpretation='Sensitivity model: if an instruction straddles 64B, classify its last-byte line. The event does not expose which line actually missed; starting-IP and continuation-line classifications are both retained. Unknown lengths remain on the starting line. Static bounded LBR witnesses do not require usable cycle-distance fields.'),
            branch_association_per_request=dict(branch),origin_events_per_request=dict(origins),
            origin_age_bins={origin:[dict(lo_us=EDGES[i],hi_us=EDGES[i+1] if i+1<len(EDGES) else None,**dict(v))
                for i,v in enumerate(values)] for origin,values in origin_ages.items()},
            age_bins=[dict(lo_us=lo,hi_us=EDGES[i+1] if i+1<len(EDGES) else None,events_per_request=dict(ages[i]),
                selected_target_events_per_request=selected_ages[i],sampled_events=events[i],scheduled_exposure_us=exposures[i],
                events_per_scheduled_us=events[i]/exposures[i] if exposures[i] else None) for i,lo in enumerate(EDGES)],
            top_locations=[dict(service=s,segment=seg,image=im,line=line,classification=cls,events_per_request=n)
                for (s,seg,im,line,cls),n in locations.most_common(100)])
    result=dict(arms=output,sources=sources,source_sha256=b.sha(__file__),
        scope='Application and MongoDB process captures are separate named groups, each including mapped DSOs. Kernel is excluded from PEBS; separate pool PMU covers kernel totals.',
        limitations='Retired L2-miss samples, not all speculative L2 code reads. Each service has a separate eight-second window. One capture per arm, descriptive only. Bounded retired LBR can witness execution of a hint stub, not acceptance or completion. No witness is not proof of no issue. Taken-target proximity is not BTB attribution. Switch-in age starts at scheduler selection, not first user instruction. Primary counts use the sampled starting-IP line; the decoded continuation-line sensitivity model is recorded separately and does not prove which line missed.')
    destination=root/'analysis/residuals.json'
    if destination.exists():
        snapshot=root/'analysis/history'/('residuals_'+b.sha(destination)+'.json')
        snapshot.parent.mkdir(exist_ok=True)
        if not snapshot.exists():snapshot.write_bytes(destination.read_bytes())
    b.save(destination,result)
    for name,row in output.items():print(name,row['per_request'],row['selected_target_events_per_request'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);analyze(parser.parse_args().root)
