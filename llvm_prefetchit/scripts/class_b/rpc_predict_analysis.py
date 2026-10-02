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
    selected={s:{t//64 for c in row['choices'] for t in c['targets']} for s,row in load(root/'model.json').items()}
    output={};sources={}
    for phase in sorted((root/'profiles').iterdir()):
        if not phase.is_dir() or not (phase/'complete.json').exists():continue
        name=phase.name;aggregate=collections.Counter();locations=collections.Counter();targeted=collections.Counter()
        ages=[collections.Counter() for _ in range(len(EDGES))];exposures=[0.0]*len(EDGES);events=[0.0]*len(EDGES)
        services={};branch=collections.Counter();origins=collections.Counter()
        for path in sorted(phase.glob('*/l2/observations.json.gz')):
            data=read(path);service=data['service'];weight=data['period']/data['requests']
            main=data['names'].index(next(n for n in data['names'] if Path(n).name==Path(arms[name]['overrides'][service]).name))
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
                if in_stub:cls=in_stub
                elif line in lines[i]:cls='targeted_with_lbr_witness' if witnessed else 'targeted_no_bounded_witness'
                else:cls='not_targeted'
                if i<0:cls='unmapped'
                counts[cls]+=weight;counts['all']+=weight;counts['image_'+segment]+=weight
                local_ages[age][cls]+=weight;sample_locations[segment,i,line,cls]+=weight
                if i==main and line in selected[service]:targets['selected_lines']+=weight
                if i==main:targets['main_all']+=weight
                if history and history[0][2]==i and 0<=ip-history[0][3]<64:
                    branch['within_64B_after_taken']+=weight
                    branch['prediction_'+history[0][4]]+=weight
                origins[row['origin']]+=weight
            timeline=load(path.with_name('timeline.json'))
            for index,v in enumerate(timeline['bins']):
                exposures[index]+=v['exposure_us'];events[index]+=v['estimated_events']
            aggregate.update(counts);targeted.update(targets)
            for i,c in enumerate(local_ages):ages[i].update(c)
            services[service]=dict(samples=len(data['rows']),per_request=dict(counts),selected_target_events_per_request=dict(targets),
                quality=timeline['quality'],requests=data['requests'],profile_sha256=b.sha(path))
            sources[str(path)]=b.sha(path)
            for (segment,i,line,cls),value in sample_locations.items():
                locations[service,segment,data['names'][i] if i>=0 else 'unknown',line,cls]+=value
        output[name]=dict(services=services,per_request=dict(aggregate),selected_target_events_per_request=dict(targeted),
            branch_association_per_request=dict(branch),origin_events_per_request=dict(origins),
            age_bins=[dict(lo_us=lo,hi_us=EDGES[i+1] if i+1<len(EDGES) else None,events_per_request=dict(ages[i]),
                sampled_events=events[i],scheduled_exposure_us=exposures[i],events_per_scheduled_us=events[i]/exposures[i] if exposures[i] else None) for i,lo in enumerate(EDGES)],
            top_locations=[dict(service=s,segment=seg,image=im,line=line,classification=cls,events_per_request=n)
                for (s,seg,im,line,cls),n in locations.most_common(100)])
    result=dict(arms=output,sources=sources,source_sha256=b.sha(__file__),
        scope='Nine application process cgroups, their mapped DSOs included. MongoDB and kernel are excluded from these PEBS captures; use separate PMU for their totals.',
        limitations='Retired L2-miss samples, not all speculative L2 code reads. Each service has a separate eight-second window. One capture per arm, descriptive only. Bounded retired LBR can witness execution of a hint stub, not acceptance or completion. No witness is not proof of no issue. Taken-target proximity is not BTB attribution. Switch-in age starts at scheduler selection, not first user instruction. Straddling instructions are not adjusted here; this classifier uses the sampled IP cache line consistently in every arm.')
    b.save(root/'analysis/residuals.json',result)
    for name,row in output.items():print(name,row['per_request'],row['selected_target_events_per_request'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);analyze(parser.parse_args().root)
