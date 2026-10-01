#!/usr/bin/env python3
"""Join PEBS retirement ages, observed calls and bounded static CFG evidence.

Static control-flow dominance is reported only for fully decoded normal paths
without unresolved jumps. Observed cross-function paths do not imply dominance.
GOT anchors come from observed PLT/GOT branches and are validated by ELF identity.
"""
import argparse
import bisect
import collections
import gzip
import heapq
import json
from pathlib import Path
import re
import struct
import sys

import dense_build as b
from dense_cause_analysis import Code, category
import call_stub_prefetch as stubs
from temporal_path_common import EDGES, PRIOR


class Image:
    def __init__(self,path):
        self.path=Path(path);self.sha=b.sha(path);self.raw=self.path.read_bytes()
        self.elf=stubs.Elf(self.raw);self.code=Code(self.path);self.calls={};self.got_sites={};self.functions={};self.cfgs={}
        previous=None;start=None
        for va,(length,asm,function) in self.code.instructions.items():
            if function!=previous:
                start=va;previous=function;self.functions[start]=dict(name=function,ips=[])
            self.functions[start]['ips'].append(va)
            if length==5 and category(asm)=='direct_call':
                off=self.elf.offset(va,5,True)
                if self.raw[off]==0xe8:
                    target=va+5+struct.unpack_from('<i',self.raw,off+1)[0]
                    if target in self.code.instructions:self.calls[va]=dict(site=va,callee=target,expected=self.raw[off:off+5].hex())
            if category(asm) in ('indirect_call','indirect_jump') and '(%rip)' in asm:
                match=re.search(r'#\s*([0-9a-f]+)',asm)
                if match:self.got_sites[va]=int(match[1],16)
        self.starts=sorted(self.functions)
        self.function_for={ip:start for start,entry in self.functions.items() for ip in entry['ips']}
        self.dynamic_got=set()
        for section in self.elf.sh:
            if section[1]==4 and section[2]&2:
                for pos in range(section[4],section[4]+section[5],24):
                    address,info,_=struct.unpack_from('<QQq',self.raw,pos)
                    if info&0xffffffff in (6,7):self.dynamic_got.add(address)
        self.got_sites={site:got for site,got in self.got_sites.items() if got in self.dynamic_got}

    def function(self,ip):
        start=self.function_for.get(ip)
        return self.functions[start]['name'] if start is not None else 'unknown'

    def dominance(self,site,target):
        start=self.function_for.get(site)
        if start is None or start!=self.function_for.get(target):return 'cross_function_trace'
        if start not in self.cfgs:self.cfgs[start]=self._cfg(start)
        cfg=self.cfgs[start]
        if cfg is None:return 'same_function_unresolved_cfg'
        source_block=cfg['block_for'].get(site);target_block=cfg['block_for'].get(target)
        if target_block not in cfg['dom']:return 'same_function_unreachable_cfg'
        if source_block in cfg['dom'][target_block] and (source_block!=target_block or site<target):
            return 'same_function_normal_cfg_dominator'
        return 'same_function_observed_path'

    def _cfg(self,start):
        ips=self.functions[start]['ips']
        if len(ips)>5000:return None
        valid=set(ips);leaders={start};branches={}
        for ip in ips:
            length,asm,_=self.code.get(ip);kind=category(asm);after=ip+length
            if kind=='indirect_jump':return None
            if kind in ('conditional_branch','direct_jump'):
                match=re.search(r'\b(?:j\w+|loop\w*)\s+([0-9a-f]+)',asm)
                if not match:return None
                dest=int(match[1],16)
                if dest in valid:leaders.add(dest)
                branches[ip]=dest
            if kind in ('conditional_branch','direct_jump','return','direct_call','indirect_call') and after in valid:leaders.add(after)
        leaders=sorted(leaders)
        if len(leaders)>512:return None
        block_for={ip:leaders[bisect.bisect_right(leaders,ip)-1] for ip in ips}
        blocks=collections.defaultdict(list)
        for ip in ips:blocks[block_for[ip]].append(ip)
        succ={leader:set() for leader in leaders}
        for leader,values in blocks.items():
            ip=values[-1];length,asm,_=self.code.get(ip);kind=category(asm)
            if ip in branches and branches[ip] in valid:succ[leader].add(block_for[branches[ip]])
            if kind not in ('direct_jump','return') and ip+length in valid:succ[leader].add(block_for[ip+length])
        reachable={start};todo=[start]
        while todo:
            for nxt in succ[todo.pop()]-reachable:reachable.add(nxt);todo.append(nxt)
        pred={v:set() for v in reachable}
        for src in reachable:
            for dst in succ[src]:pred[dst].add(src)
        dom={v:({v} if v==start else set(reachable)) for v in reachable}
        changed=True
        while changed:
            changed=False
            for v in sorted(reachable-{start}):
                value={v}|set.intersection(*(dom[p] for p in pred[v]))
                if value!=dom[v]:dom[v]=value;changed=True
        return dict(block_for=block_for,dom=dom,blocks=len(blocks))


def files(root,phase,kind):
    return sorted((root/'profiles').glob(phase+'_*/'+ '*/'+kind+'/observations.json.gz'))


def read(path):
    with gzip.open(path,'rt') as stream:data=json.load(stream)
    data['digests']=[data['catalog'][name]['sha256'] for name in data['names']]
    data['requests']=json.loads((path.parent/'request_window.json').read_text())['completed_requests']
    data['service']=path.parents[1].name
    return data


def inventory(root):
    found={}
    for phase in ('train','heldout','residual'):
        for path in files(root,phase,'l2'):
            data=read(path)
            for entry in data['catalog'].values():found.setdefault(entry['sha256'],entry['binary'])
    return found


def load_original_images(root):
    found={}
    for path in files(root,'train','l2'):
        data=read(path)
        for entry in data['catalog'].values():found.setdefault(entry['sha256'],entry['binary'])
    images={}
    for digest,path in found.items():
        if 'ld-linux' in Path(path).name:continue
        print(json.dumps(dict(stage='decode_image',binary=path)),flush=True)
        try:images[digest]=Image(path)
        except AssertionError as error:
            b.save(root/'analysis'/('unsupported_'+digest+'.json'),dict(binary=path,error=repr(error)))
    return images


def anchors(root,images):
    observations=collections.defaultdict(set);support=collections.Counter();graph=collections.Counter()
    for path in files(root,'train','l2')+files(root,'train','calls'):
        data=read(path);digests=data['digests']
        for row in data['rows']:
            for sd,source,td,target,pred,cycles,kind in row['edges']:
                if min(sd,td)<0:continue
                source_sha,target_sha=digests[sd],digests[td]
                if source_sha not in images or target_sha not in images:continue
                source_image=images[source_sha];target_image=images[target_sha]
                if source in source_image.got_sites:
                    key=(source_sha,source_image.got_sites[source]);observations[key].add((target_sha,target));support[key]+=1
                if kind in ('CALL','IND_CALL'):
                    graph[source_sha,source_image.function(source),target_sha,target_image.function(target),kind]+=1
    table=collections.defaultdict(list);rejected=[]
    for (source_sha,got),values in observations.items():
        if len(values)!=1:
            rejected.append(dict(source=source_sha,got=got,values=list(values),reason='GOT target varied across training traces'));continue
        target_sha,target=next(iter(values))
        if target_sha==source_sha or target not in images[target_sha].code.instructions:continue
        table[source_sha,target_sha].append(dict(got=got,anchor=target,observations=support[source_sha,got]))
    b.save(root/'analysis/got_anchors.json',dict(anchors=[dict(source=s,target=t,entries=v) for (s,t),v in table.items()],rejected=rejected,
        source='Observed retired PLT/GOT branch destinations plus existing ELF dynamic relocations. Runtime ASLR handled by loading that GOT cell; training target ELF hash and offset must match deployment.'))
    b.save(root/'analysis/observed_callgraph.json',dict(edges=[dict(source_sha=s,caller=fn,target_sha=t,callee=to,kind=k,observations=n) for (s,fn,t,to,k),n in graph.items()],
        limitation='Dynamic edge presence supplements static direct calls. Counts are repeated LBR appearances, not unbiased execution frequencies; missing edges are not impossible paths.'))
    return table


def frequencies(root,images):
    frequency=collections.Counter();floors=collections.Counter();counts=collections.Counter()
    for path in files(root,'train','calls'):
        data=read(path);digests=data['digests'];weight=data['period']/data['requests'];seen=set()
        for row in data['rows']:
            if row['dso']<0:continue
            digest=digests[row['dso']]
            if digest not in images:continue
            seen.add(digest);image=images[digest];counts[category(image.code.get(row['ip'])[1])]+=1
            if row['ip'] in image.calls:frequency[digest,row['ip']]+=weight
        for digest in seen:floors[digest]+=3*weight
    calls=counts['direct_call']+counts['indirect_call'];assert calls>.99*sum(counts.values()),counts
    b.save(root/'analysis/call_frequency.json',dict(counts=dict(counts),floor=dict(floors),
        rates=[dict(sha=d,site=s,per_request=n) for (d,s),n in frequency.items()]))
    return frequency,floors


def target_for(image,row):
    ip=row['ip'];length=image.code.get(ip)[0]
    if not length:return None
    if ip//64!=(ip+length-1)//64 and ip+length in image.code.instructions:return ip+length
    return ip


def observed_calls(row,digests,images,minimum,maximum):
    history=row['edges'];sample=(row['dso'],row['ip'])
    if history and tuple(history[0][:2])==sample:history=history[1:]
    age=0;seen={}
    for sd,source,td,target,pred,cycles,kind in history:
        if age>maximum:break
        if sd>=0:
            digest=digests[sd]
            if digest in images and source in images[digest].calls and minimum<=age<=maximum:
                seen.setdefault((digest,source),age)
        if cycles is None or cycles>=65535:break
        age+=cycles
    return seen


def collect(root,phase,images,anchor_table,minimum,maximum):
    rows=[];quality=collections.Counter();classes=collections.Counter();timebins=collections.Counter()
    settings=json.loads((PRIOR/'settings.json').read_text())
    legacy=json.loads(Path(settings['mongo_split75']+'.json').read_text())
    legacy_sha=legacy['source_sha256']
    legacy_targets={p['site']:{target//64 for target in p['targets']} for p in legacy['plan']['calls']}
    for path in files(root,phase,'l2'):
        data=read(path);digests=data['digests'];weight=data['period']/data['requests']
        for row in data['rows']:
            quality['all_samples']+=1
            if row['dso']<0:quality['unmapped_samples']+=1;continue
            target_sha=digests[row['dso']]
            if target_sha not in images:quality['unsupported_image_samples']+=1;continue
            image=images[target_sha];target=target_for(image,row)
            if target is None:quality['not_instruction_boundary']+=1;continue
            sites={};calls=observed_calls(row,digests,images,minimum,maximum)
            baseline_calls=observed_calls(row,digests,images,64,8192) if target_sha==legacy_sha else {}
            precovered=any(source==legacy_sha and target//64 in legacy_targets.get(site,set()) for source,site in baseline_calls)
            for (source_sha,site),age in calls.items():
                if source_sha==target_sha:
                    if site//64==target//64:continue
                    sites[source_sha,site]=dict(target=target,age=age,kind='local')
                elif (source_sha,target_sha) in anchor_table:
                    anchor=min(anchor_table[source_sha,target_sha],key=lambda a:abs(target-a['anchor']))
                    if not -(1<<31)<=target-anchor['anchor']<1<<31:continue
                    sites[source_sha,site]=dict(got=anchor['got'],addend=target-anchor['anchor'],age=age,kind='cross',
                        target=target,anchor=anchor['anchor'])
            quality['with_any_earlier_call']+=bool(calls)
            quality['eligible_samples']+=bool(sites)
            quality['cross_dso_eligible_samples']+=any(v['kind']=='cross' for v in sites.values())
            quality['cross_dso_only_samples']+=bool(sites) and all(v['kind']=='cross' for v in sites.values())
            quality['retained_mongo_model_covered_samples']+=precovered
            classes[category(image.code.get(row['ip'])[1])]+=1
            timebins[bisect.bisect_right(EDGES,row['age_us'])-1]+=1
            rows.append(dict(target_sha=target_sha,target=target,line=target//64,sites=sites,weight=weight,
                service=data['service'],age_us=row['age_us'],origin=row['origin'],precovered=precovered))
    return rows,dict(quality,classes=dict(classes),age_bins=dict(timebins),rows=len(rows))


def choose(rows,frequency,floors,max_sites=2048,max_hints=6144,per_site=4,min_gain=6,goal=.75,cross_cost=2.5):
    candidates=collections.defaultdict(set);representatives={};weights=[r['weight'] for r in rows]
    for i,row in enumerate(rows):
        for site,description in row['sites'].items():
            key=(*site,row['target_sha'],row['line']);candidates[key].add(i);representatives.setdefault(key,description)
    candidates={k:v for k,v in candidates.items() if len(v)>=min_gain}
    costs={k:max(frequency.get(k[:2],0),floors.get(k[0],1.0))*(cross_cost if representatives[k]['kind']=='cross' else 1) for k in candidates}
    heap=[(-sum(weights[i] for i in ids)/costs[k],k) for k,ids in candidates.items()];heapq.heapify(heap)
    covered={i for i,row in enumerate(rows) if row.get('precovered')};baseline_covered=len(covered)
    used=collections.Counter();selected=[]
    while heap and len(selected)<max_hints and len(covered)<goal*len(rows):
        _,key=heapq.heappop(heap);site=key[:2]
        if used[site]>=per_site or (site not in used and len(used)>=max_sites):continue
        new=candidates[key]-covered
        if len(new)<min_gain:continue
        gain=sum(weights[i] for i in new);priority=(-gain/costs[key],key)
        if heap and priority>heap[0]:heapq.heappush(heap,priority);continue
        selected.append(dict(source_sha=key[0],site=key[1],target_sha=key[2],line=key[3],**representatives[key],
            gain=len(new),estimated_misses_per_request=gain,estimated_issue_per_request=max(frequency.get(site,0),floors.get(key[0],1.0))))
        covered.update(new);used[site]+=1
    return dict(choices=selected,samples=len(rows),covered=len(covered),baseline_covered=baseline_covered,sites=len(used),hints=len(selected),
        settings=dict(max_sites=max_sites,max_hints=max_hints,per_site=per_site,min_gain=min_gain,goal=goal,cross_cost=cross_cost),
        estimated_hint_executions_per_request=sum(s['estimated_issue_per_request'] for s in selected))


def assess(rows,selected):
    chosen=collections.defaultdict(set)
    for c in selected:chosen[c['source_sha'],c['site']].add((c['target_sha'],c['line']))
    quality=collections.Counter();age=collections.Counter();service=collections.Counter()
    for row in rows:
        covered=row.get('precovered',False) or any((row['target_sha'],row['line']) in chosen[site] for site in row['sites'])
        quality['samples']+=1;quality['covered']+=covered
        quality['baseline_covered']+=row.get('precovered',False)
        age[bisect.bisect_right(EDGES,row['age_us'])-1,'all']+=1
        age[bisect.bisect_right(EDGES,row['age_us'])-1,'covered']+=covered
        service[row['service'],'all']+=1;service[row['service'],'covered']+=covered
    return dict(quality=dict(quality),age=[dict(bin=i,kind=k,samples=n) for (i,k),n in age.items()],
        service=[dict(service=s,kind=k,samples=n) for (s,k),n in service.items()])


def prepare(root):
    out=root/'analysis';out.mkdir(exist_ok=True);images=load_original_images(root)
    table=anchors(root,images);frequency,floors=frequencies(root,images);summary={}
    variants=[('path64',64,8192,4,6,.75),('path512',512,16384,4,6,.75),('pathwide',64,16384,8,3,.9)]
    for name,minimum,maximum,per_site,min_gain,goal in variants:
        train,quality=collect(root,'train',images,table,minimum,maximum)
        heldout,hq=collect(root,'heldout',images,table,minimum,maximum)
        selected=choose(train,frequency,floors,per_site=per_site,min_gain=min_gain,goal=goal)
        selected.update(train_quality=quality,heldout_quality=hq,heldout=assess(heldout,selected['choices']),minimum=minimum,maximum=maximum)
        for choice in selected['choices']:
            source=images[choice['source_sha']];target=images[choice['target_sha']]
            choice.update(caller=source.function(choice['site']),target_function=target.function(choice['target']),
                relation=source.dominance(choice['site'],choice['target']) if source.sha==target.sha else 'cross_dso_trace',
                call=source.calls[choice['site']])
        b.save(out/(name+'_selection.json'),selected)
        summary[name]=dict(sites=selected['sites'],hints=selected['hints'],train=selected['covered']/selected['samples'],
            heldout=selected['heldout']['quality']['covered']/selected['heldout']['quality']['samples'],
            kinds=dict(collections.Counter(c['kind'] for c in selected['choices'])),relations=dict(collections.Counter(c['relation'] for c in selected['choices'])))
        print(json.dumps(dict(stage='selected',variant=name,**summary[name])),flush=True)
        del train,heldout
    b.save(out/'images.json',{digest:dict(binary=str(image.path),name=image.path.name,calls=len(image.calls),instructions=len(image.code.instructions)) for digest,image in images.items()})
    b.save(out/'summary.json',summary)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();prepare(a.root)
