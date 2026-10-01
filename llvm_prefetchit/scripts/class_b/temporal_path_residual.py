#!/usr/bin/env python3
"""Locate residual misses relative to static targets and observed hint stubs."""
import argparse
import bisect
import collections
import json
from pathlib import Path

import dense_build as b
from dense_cause_analysis import Code, category
from temporal_path_analysis import read, files
from temporal_path_common import EDGES, PRIOR


def policies(root):
    result={}
    candidates=list((root/'controls').rglob('*.json'))
    settings=json.loads((PRIOR/'settings.json').read_text())
    candidates.append(Path(settings['mongo_split75']+'.json'))
    candidates.extend((root/'builds').rglob('*.json'))
    for path in candidates:
        data=json.loads(path.read_text())
        if 'hints' not in data or 'patches' not in data:continue
        result[data['sha256']]=data
    return result


def policy_index(digests, known):
    """Resolve static targets across loaded ELF identities, never virtual bases."""
    originals={known[d]['source_sha256'] if d in known else d:i for i,d in enumerate(digests)}
    jumps={};targets=collections.defaultdict(set);ranges=collections.defaultdict(list)
    for index,digest in enumerate(digests):
        policy=known.get(digest)
        if not policy:continue
        assert 'hybrid' not in policy, 'Conditional hybrid stubs require a separate witness model'
        for patch in policy['patches']:
            reached={(index,target//64) for target in patch['targets']}
            for target in patch.get('got_targets',[]):
                destination=originals.get(target['target_sha'])
                if destination is not None:reached.add((destination,target['target']//64))
            terminal=patch.get('terminal_jumps')
            if terminal is None:
                assert not patch.get('got_targets'), 'GOT witness requires recorded terminal jump'
                terminal=[patch['stub']+7*len(patch['targets'])]
            assert len(terminal)==1
            jumps[index,terminal[0]]=reached
            ranges[index].append((patch['stub'],terminal[0]+5))
            for destination,line in reached:targets[destination].add(line)
    return jumps,targets,ranges


def analyze(root,phase='residual'):
    known=policies(root);cache={};records=[]
    sources={}
    for name in ('temporal_path_residual.py','temporal_path_analysis.py','dense_cause_analysis.py','temporal_path_common.py'):
        source=Path(__file__).with_name(name);digest=b.sha(source)
        saved=root/'source_versions'/(digest+'.py')
        if not saved.exists():saved.write_bytes(source.read_bytes())
        sources[name]=digest
    b.save(root/'analysis'/('residual_'+phase+'_protocol.json'),dict(phase=phase,source_hashes=sources))
    for kind in ('l2','lat128','l1','unknown'):
        for path in files(root,phase,kind):
            data=read(path);digests=data['digests'];images={}
            stub_jumps,target_lines,stub_ranges=policy_index(digests,known)
            for index,name in enumerate(data['names']):
                digest=digests[index];policy=known.get(digest);entry=data['catalog'][name]
                source=policy['source'] if policy else entry['binary'];key=b.sha(source)
                if key not in cache:
                    print(json.dumps(dict(stage='residual_decode',binary=source)),flush=True)
                    cache[key]=Code(Path(source))
                images[index]=cache[key]
            sorted_targets={index:sorted(lines) for index,lines in target_lines.items()}
            counts=collections.Counter();weighted=collections.Counter();age_classes=collections.Counter();locations=collections.Counter()
            target_distance=collections.Counter();branch_distance=collections.Counter()
            branches=collections.Counter();lead=collections.Counter();functions=collections.Counter();examples=[]
            instruction_classes=collections.Counter();straddling=0
            for row in data['rows']:
                dso=row['dso'];ip=row['ip'];index=bisect.bisect_right(EDGES,row['age_us'])-1
                if dso not in images:
                    cls='unmapped';target=ip;function='unknown';nearest=None
                else:
                    code=images[dso];length,asm,function=code.get(ip);target=ip
                    if length and ip//64!=(ip+length-1)//64:
                        straddling+=1
                        if ip+length in code.instructions:target=ip+length
                    in_stub=any(lo<=ip<hi for lo,hi in stub_ranges.get(dso,[]))
                    instruction_classes[('added_hint_stub_jump' if (dso,ip) in stub_jumps else 'added_hint_stub_other')
                                        if in_stub else category(asm)]+=1
                    history=row['edges']
                    if history and tuple(history[0][:2])==(dso,ip):history=history[1:]
                    nearest=history[0] if history else None
                    matches=[];age=0
                    for sd,fr,td,to,pred,cycles,typ in history:
                        if (dso,target//64) in stub_jumps.get((sd,fr),set()):matches.append(age)
                        if cycles is None or cycles>=65535:break
                        age+=cycles
                    if in_stub:cls='added_hint_stub_fetch';function='added_hint_stub'
                    elif dso not in target_lines and digests[dso] not in known:cls='unmodified_image'
                    elif target//64 not in target_lines[dso]:cls='line_not_statically_targeted'
                    elif not matches:cls='targeted_line_without_matching_stub_in_bounded_lbr'
                    else:
                        value=max(matches)
                        band='0_63' if value<64 else '64_511' if value<512 else '512_2047' if value<2048 else '2048_plus'
                        cls='matching_stub_observed_'+band;lead[band]+=1
                    lines=sorted_targets.get(dso,[])
                    if lines and not in_stub:
                        line=target//64;position=bisect.bisect_left(lines,line)
                        nearby=lines[max(0,position-1):position+1]
                        delta=line-min(nearby,key=lambda x:abs(line-x))
                        target_distance[str(delta) if abs(delta)<=4 else 'farther_than_4_lines']+=1
                    if nearest and nearest[2]==dso and 0<=ip-nearest[3]<64:
                        branches[cls,'within_64B_after_taken_target']+=1
                        branches[cls,'preceding_mispredicted_taken_branch']+=nearest[4]=='M'
                        branches[cls,'preceding_correctly_predicted_taken_branch']+=nearest[4]=='P'
                        branches[cls,'preceding_prediction_unknown']+=nearest[4] not in ('M','P')
                        if nearest[0] in images:
                            source_kind='added_hint_stub_jump' if tuple(nearest[:2]) in stub_jumps else category(images[nearest[0]].get(nearest[1])[1])
                            branches[cls,source_kind]+=1
                    if nearest and nearest[2]==dso:
                        distance=ip-nearest[3]
                        branch_distance[str(distance) if 0<=distance<64 else 'outside_first_64_bytes']+=1
                counts[cls]+=1;weighted[cls]+=data['period']/data['requests'];age_classes[index,cls]+=1
                locations[dso,target//64,cls]+=1;functions[dso,function,cls]+=1
                if len(examples)<40 and cls.startswith('matching_stub'):
                    examples.append(dict(ip=ip,dso=dso,age_us=row['age_us'],classification=cls,function=function,nearest=nearest))
            record=dict(service=data['service'],kind=kind,phase=phase,samples=len(data['rows']),counts=dict(counts),
                events_per_request=dict(weighted),age_classes=[dict(bin=i,classification=c,samples=n) for (i,c),n in age_classes.items()],
                nearest_static_target_line_delta=dict(target_distance),nearest_taken_target_byte_delta=dict(branch_distance),
                instruction_classes=dict(instruction_classes),straddling_instruction_samples=straddling,
                branches=[dict(classification=c,kind=k,samples=n) for (c,k),n in branches.items()],
                top_locations=[dict(dso=d,line=line,classification=c,samples=n) for (d,line,c),n in locations.most_common(100)],
                top_functions=[dict(dso=d,function=f,classification=c,samples=n) for (d,f,c),n in functions.most_common(80)],examples=examples,
                names=data['names'],digests=digests,
                limitation='Residual event attribution, not accepted-prefetch or precise fetch latency. A retired straight-line-stub jump witnesses preceding hints, not their acceptance/completion. GOT hints assume the separately audited relocation has resolved; the trace cannot distinguish an unresolved lazy slot. Missing bounded-LBR evidence does not prove absence. Straddling-instruction continuation is a target model. Conditional hybrid stubs are rejected.')
            records.append(record)
            b.save(root/'analysis'/('residual_'+phase+'_'+data['service']+'_'+kind+'.json'),record)
            print(json.dumps(dict(stage='residual_summary',service=data['service'],kind=kind,counts=dict(counts))),flush=True)
    b.save(root/'analysis'/('residual_'+phase+'_summary.json'),dict(records=records))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--phase',default='residual');a=p.parse_args();analyze(a.root,a.phase)
