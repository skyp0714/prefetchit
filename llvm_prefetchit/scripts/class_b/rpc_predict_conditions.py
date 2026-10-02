#!/usr/bin/env python3
"""Annotate measurement windows with observed host load; never exclude trials."""
import argparse
import collections
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load


def annotate(root):
    observations=load(root/'aggregate_environment.json')
    def window(begin,end):
        weighted=collections.Counter();covered=0.0;outside=[]
        for row in observations:
            overlap=max(0,min(end,row['end_epoch'])-max(begin,row['start_epoch']))
            if not overlap:continue
            covered+=overlap
            for key,value in row['cpu_busy_pct'].items():weighted[key]+=overlap*value
            outside.append(row['cpu_busy_pct']['other_host'])
        means={k:v/covered for k,v in weighted.items()} if covered else {}
        coverage=100*covered/(end-begin)
        if coverage<95:condition='incomplete_observation'
        elif means['other_host']<5 and means['client']<20:condition='observed_quiet'
        elif means['other_host']>50 or means['client']>50:condition='co_loaded'
        else:condition='intermediate_load'
        return dict(begin_epoch=begin,end_epoch=end,seconds=end-begin,observed_pct=coverage,
            mean_cpu_busy_pct=means,outside_busy_range=[min(outside),max(outside)] if outside else None,
            descriptive_condition=condition)
    endpoints={};profiles={}
    for phase in ('screen','confirmation','coverage_screen','quiet_coverage_screen','production_confirmation'):
        path=root/phase/'rows.json'
        if not path.exists():continue
        endpoints[phase]=[]
        for row in load(path):
            pool=load(Path(row['output'])/'result.json')['pool']
            endpoints[phase].append(dict(block=row['block'],arm=row['arm'],valid=row['valid'],
                achieved_rps=row['achieved_rps'],**window(pool['start'],pool['end'])))
    for directory in ('profiles','mongo_profiles'):
        for path in sorted((root/directory).glob('*/*/l2/request_window.json')):
            bounds=load(path);name='/'.join(path.relative_to(root).parts[:2])
            profiles.setdefault(name,[]).append(dict(service=path.parents[1].name,
                **window(bounds['begin_epoch'],bounds['end_epoch'])))
    result=dict(epoch=time.time(),source_sha256=b.sha(__file__),endpoints=endpoints,profiles=profiles,
        protocol='Post-hoc descriptive annotation after observing a host-wide external load rise. No rows are excluded, retried, or reweighted by this tool. The original observer is contextual. Labels summarize continuous CPU observations, not an originally predeclared performance validity rule.',
        definitions='Observed quiet: >=95% interval coverage, outside-server/client/controller CPUs <5% busy and client CPUs <20%. Co-loaded: >=95% coverage and outside or client busy >50%. Intermediate and missing observation are explicit. Server busy includes both campaign and external work. Profile windows include perf setup/teardown and are only approximate request-normalization intervals.',
        identities='No unrelated process identity, command, owner, or input is recorded.')
    b.save(root/'analysis/conditions.json',result)
    for phase,rows in endpoints.items():print(phase,dict(collections.Counter(v['descriptive_condition'] for v in rows)))
    for name,rows in profiles.items():print(name,dict(collections.Counter(v['descriptive_condition'] for v in rows)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);annotate(parser.parse_args().root)
