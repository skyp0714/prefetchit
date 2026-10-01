#!/usr/bin/env python3
"""Locate retained training samples in the incumbent's emitted stub ranges."""
import argparse
import bisect
import collections
from pathlib import Path

import dense_build as b
from rpc_route_study import load
from temporal_path_analysis import read


def audit(root):
    assert load(root/'same_line_complete.json')['valid'],'Do not decode training data during timing'
    model=load(root/'model.json');reference=load(root/'references.json')['previous']['arm']
    services={};total=collections.Counter()
    for service,info in model.items():
        trace=Path(info['training']);metadata=Path(reference['overrides'][service]+'.json')
        assert not str(trace.resolve()).startswith('/fast-lab-share/')
        assert not str(metadata.resolve()).startswith('/fast-lab-share/')
        assert b.sha(trace)==info['training_sha256']
        record=load(metadata);ranges=sorted({(p['stub'],max(p['terminal_jumps'])+5) for p in record['patches']})
        merged=[]
        for lo,hi in ranges:
            if merged and lo<=merged[-1][1]:merged[-1][1]=max(hi,merged[-1][1])
            else:merged.append([lo,hi])
        starts=[lo for lo,hi in merged];hints={p['va'] for p in record['hints']}
        data=read(trace);main=data['digests'].index(record['sha256']);counts=collections.Counter(all=len(data['rows']))
        for row in data['rows']:
            if row['dso']!=main:continue
            i=bisect.bisect_right(starts,row['ip'])-1
            if i>=0 and row['ip']<merged[i][1]:
                counts['emitted_stub']+=1
                counts['hint_instruction' if row['ip'] in hints else 'other_stub_instruction']+=1
        weighted={k:v*data['period']/data['requests'] for k,v in counts.items()};total.update(weighted)
        services[service]=dict(samples=dict(counts),estimated_per_request=weighted,
            trace=str(trace),trace_sha256=info['training_sha256'],metadata=str(metadata),metadata_sha256=b.sha(metadata),
            executable_sha256=record['sha256'],ranges=merged)
    result=dict(scope='Retained incumbent training, not new-policy PMU or a held-out temporal trace.',services=services,
        estimated_per_request=dict(total),stub_pct=100*total['emitted_stub']/total['all'],
        hint_instruction_pct=100*total['hint_instruction']/total['all'],source_sha256=b.sha(__file__),
        interpretation='PEBS sample IP is inside an emitted prefetch-stub range. This is not the number of misses caused by prefetch targets, a slowdown estimate, or a BTB attribution. Ranges come from the incumbent patch records; no decoded copies are retained.')
    b.save(root/'training_stub_audit.json',result)
    print({k:result[k] for k in ['estimated_per_request','stub_pct','hint_instruction_pct']})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    audit(parser.parse_args().root)
