#!/usr/bin/env python3
"""Train switch-in lists with actual syscall-exit user IP preceding the PT run.

Requires syscall_context.txt recorded with --user-regs=ip alongside Intel PT.
Classifiers use the first PT trace-start return IP and an unambiguous observed
syscall/IP dictionary, with the preceding SYSCALL opcode verified in the ELF.
Cross-recorder timestamps are not assumed interchangeable.
"""
import argparse
import bisect
import collections
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
PARSER = Path(__file__).resolve().parent/'reference/run_paths.py'
spec = importlib.util.spec_from_file_location('run_paths', PARSER)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)
EXIT = re.compile(r'^\s*(\d+)\s+(\d+\.\d+):\s+raw_syscalls:sys_exit:\s+NR\s+(\d+).*?\bIP:0x([0-9a-f]+)')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def resume_event(events,times,tin,tout,first_branch):
    index=bisect.bisect_left(times,tin)
    if index<len(events) and events[index][0]<=first_branch and events[index][0]<tout:
        return events[index]
    return None


def resume_context(records, dictionary, maps, verified):
    if not records:
        return None
    _,source,ip,flags=records[0]
    numbers=dictionary.get(ip,set())
    if source or flags!='tr strt' or len(numbers)!=1:
        return None
    if ip not in verified:
        resolved=maps.resolve(ip)
        verified[ip]=None
        if resolved:
            dso,va=resolved
            for offset,start,size in dso.segs:
                if start<=va-2 and va<=start+size:
                    with open(dso.file,'rb') as f:
                        f.seek(offset+va-start-2)
                        if f.read(2)==b'\x0f\x05':
                            verified[ip]=(dso.path,va)
                    break
    if verified[ip] is None:
        return None
    return (next(iter(numbers)),*verified[ip])


def episodes(trace):
    maps = rp.Maps(str(trace/'maps.txt'), str(trace/'symfs'))
    exits = collections.defaultdict(list)
    for line in (trace/'syscall_context.txt').open():
        m = EXIT.match(line)
        if m:
            exits[int(m[1])].append((float(m[2]),int(m[3]),int(m[4],16)))
    assert exits, 'no syscall events with user IP'
    for v in exits.values():
        v.sort()
    dictionary=collections.defaultdict(set)
    for events in exits.values():
        for _,nr,ip in events:
            dictionary[ip].add(nr)
    verified={}
    br, sw, _, _ = rp.parse(str(trace))
    result = []
    counters = collections.Counter()
    for tid, switches in sw.items():
        events = exits.get(tid,[])
        times = [v[0] for v in events]
        for tin,tout,_,records,_ in rp.runs_of(tid,br.get(tid,[]),switches,[]):
            if not records:
                continue
            counters['complete_runs_with_branches'] += 1
            # Retain the failed direct clock-join diagnostic. Do not relax its
            # time window or use a later syscall to label a wake.
            event=resume_event(events,times,tin,tout,records[0][0])
            if event is not None:
                counters['direct_clock_join_matches'] += 1
            ctx=resume_context(records,dictionary,maps,verified)
            if ctx is not None:
                counters['verified_pt_resume_context'] += 1
            seen = set()
            first = []
            for stamp,dso,va,_seq in first_touches(records,maps):
                key = (dso.path,va)
                if key not in seen:
                    seen.add(key)
                    first.append(key)
            result.append(dict(context=ctx,first=first,tid=tid,start=tin))
    return result, dict(counters)


def first_touches(records,maps):
    for stamp,dso,va in rp.touched_lines(records,maps):
        yield stamp,dso,va,False


def lower_bound(hits,total):
    z=1.96
    p=hits/total
    return (p+z*z/(2*total)-z*math.sqrt(p*(1-p)/total+z*z/(4*total*total)))/(1+z*z/total)


def fit(rows,budget,threshold,horizon,misses=None):
    contexts=collections.defaultdict(list)
    for row in rows:
        if row['context'] is not None:
            contexts[row['context']].append(row)
    output=[]
    for context,group in sorted(contexts.items(), key=lambda x:(-len(x[1]),x[0])):
        if len(group)<12:
            continue
        hits=collections.Counter()
        ranks=collections.defaultdict(list)
        for row in group:
            for i,key in enumerate(row['first'][:horizon]):
                hits[key]+=1
                ranks[key].append(i)
        candidates=[]
        for key,n in hits.items():
            low=lower_bound(n,len(group))
            if low<threshold:
                continue
            rank=sum(ranks[key])/n
            score=(n/len(group))/(1+rank/horizon)
            if misses is not None:
                score*=misses.get(key,0)+1 # smoothing: unsampled is not proven warm
            candidates.append(dict(key=key,hits=n,total=len(group),p=n/len(group),
                                   ci_lower=low,mean_rank=rank,score=score,
                                   retired_l2_samples=misses.get(key,0) if misses is not None else None))
        candidates.sort(key=lambda x:(-x['score'],x['key']))
        if candidates:
            output.append(dict(context=context,runs=len(group),targets=candidates[:budget]))
        if len(output)==8:
            break
    return output


def evaluate(profiles,rows):
    by_context={p['context']:p for p in profiles}
    issued=useful=matched=covered=0
    total=sum(len(row['first']) for row in rows)
    for row in rows:
        p=by_context.get(row['context'])
        if p is None:
            continue
        matched+=1
        keys={t['key'] for t in p['targets']}
        issued+=len(keys)
        touched=len(keys.intersection(row['first']))
        useful+=touched
        covered+=touched
    return dict(runs=len(rows),matched_runs=matched,issued=issued,touched=useful,
                touch_precision=useful/issued if issued else None,
                all_first_touch_coverage_pct=100*covered/total if total else None,
                semantics='Execution-path touch accuracy; not misses, fills, timeliness, or speedup')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('training',type=Path)
    p.add_argument('validation',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--threshold',type=float,default=.8)
    p.add_argument('--horizon',type=int,default=128)
    p.add_argument('--miss-samples',type=Path)
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    train,tc=episodes(a.training)
    valid,vc=episodes(a.validation)
    misses=None
    if a.miss_samples:
        maps=rp.Maps(str(a.training/'maps.txt'),str(a.training/'symfs'))
        misses=collections.Counter()
        for line in a.miss_samples.open():
            m=re.match(r'^\s*\d+\s+\d+\.\d+:\s+([0-9a-f]+)\s*$',line)
            if m:
                resolved=maps.resolve(int(m[1],16))
                if resolved:
                    dso,va=resolved
                    misses[(dso.path,va&~63)]+=1
        assert sum(misses.values())>100, 'insufficient decoded retired-L2 samples'
    summaries={}
    hashes={}
    def target(key):
        path,va=key
        if path not in hashes:
            binary=a.training/'symfs'/path.lstrip('/')
            other=a.validation/'symfs'/path.lstrip('/')
            hashes[path]=sha(binary)
            assert hashes[path]==sha(other), 'training/validation binaries differ'
        return dict(path=path,sha256=hashes[path],elf_va=hex(va))
    for budget in (8,16,32,64):
        fitted=fit(train,budget,a.threshold,a.horizon,misses)
        assert fitted, 'no sufficiently supported context/line profiles'
        plan=dict(profiles=[dict(syscall_nr=row['context'][0],
            resume_ip=target(row['context'][1:]),targets=[target(t['key']) for t in row['targets']]) for row in fitted])
        (a.out/f'kernel{budget}.json').write_text(json.dumps(plan,indent=2)+'\n')
        summaries[budget]=dict(training=evaluate(fitted,train),validation=evaluate(fitted,valid),
            details=fitted,plan_sha256=sha(a.out/f'kernel{budget}.json'))
    report=dict(training_capture=tc,validation_capture=vc,threshold=a.threshold,horizon=a.horizon,
        miss_samples=str(a.miss_samples),retired_l2_samples=sum(misses.values()) if misses is not None else None,
        policies=summaries,source_sha256=sha(Path(__file__)),parser_sha256=sha(PARSER),
        training=str(a.training),validation=str(a.validation),
        limits=['Context uses first PT trace-start destination, unique observed syscall/IP mapping, and verified preceding SYSCALL opcode.',
                'Cross-recorder timestamp join was rejected for insufficient matches; no widened time window or future method labels.',
                'Saved return IP/syscall is matched by the kernel. Runtime match counts must independently establish applicability.',
                'Two separate temporal captures; not independent applications or a miss oracle.'])
    (a.out/'training_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v['validation'] for k,v in summaries.items()},indent=2))


if __name__=='__main__':main()
