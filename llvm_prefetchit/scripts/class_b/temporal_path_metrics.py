#!/usr/bin/env python3
"""Aggregate separate diagnostic windows, preserving event denominators."""
import argparse
import collections
import json
from pathlib import Path
import statistics

import dense_build as b
from media_system_study import NATIVE, MONGO, MONITORED


def summarize(root,pattern='*',output_name='pmu_summary.json'):
    observations=collections.defaultdict(list);runs=collections.defaultdict(set);quality=[];traces=[]
    for path in sorted((root/'diagnostics').glob(pattern+'/result.json')):
        protocol=json.loads((path.parent/'protocol.json').read_text())
        result=json.loads(path.read_text())
        if not result['valid']:
            quality.append(dict(path=str(path),valid=False));continue
        arm=protocol['arm'];suite=protocol['suite']
        for key,groups in [('service',result['pmu_extra']),('pool',result['pool_pmu'])]:
            for label,scopes in groups.items():
                for scope,row in scopes.items():
                    assert row['fully_scheduled'] and row['window']['completed']>0
                    quality.append(dict(path=str(path),scope=scope,label=label,valid=True,
                        closure_error_pct=row.get('topdown_closure_error_pct')))
                    for event,value in row['per_request'].items():
                        observations[(arm,key,scope,label,event)].append(value)
                        runs[(arm,key,scope,label,event)].add(str(path))
        trace=path.parent/'request_path_summary.json'
        if trace.exists():traces.append(dict(arm=arm,suite=suite,path=str(trace),**json.loads(trace.read_text())))
    means={key:statistics.mean(values) for key,values in observations.items()}
    arms=sorted({key[0] for key in means});output={}
    scopes={**{key:[key] for key in MONITORED},'native':list(NATIVE),'mongo':list(MONGO),'monitored':list(MONITORED)}
    for arm in arms:
        output[arm]={}
        for scope,services in scopes.items():
            counts={}
            labels=sorted({(key[3],key[4]) for key in means if key[0]==arm and key[1]=='service'})
            for label,event in labels:
                keys=[(arm,'service',service,label,event) for service in services]
                if all(key in means for key in keys):counts[label+':'+event]=sum(means[key] for key in keys)
            ratios={};skipped={}
            def ratio(name,numerator,denominator,factor=100):
                if numerator in counts and counts.get(denominator,0)>0:
                    nl,ne=numerator.split(':',1);dl,de=denominator.split(':',1)
                    assert nl==dl,'Ratios must use counters from the same event window'
                    if any(runs[arm,'service',s,nl,ne]!=runs[arm,'service',s,dl,de] for s in services):
                        skipped[name]='Different source windows; select a matched diagnostic pattern.';return
                    ratios[name]=factor*counts[numerator]/counts[denominator]
            for name in ('fe-bound','be-bound','retiring','bad-spec','fetch-lat','mem-bound'):
                ratio(name+'_pct','topdown:topdown-'+name+':u','topdown:slots:u')
            for name,label,event in [('icache_stall','cache','ICACHE_DATA_STALL'),
                ('unknown_branch','front','UNKNOWN_BRANCH_CYCLES'),('itlb_walk','front','ITLB_WALK_ACTIVE'),
                ('recovery','recovery','RECOVERY_CYCLES'),('clear_resteer','recovery','CLEAR_RESTEER_CYCLES')]:
                ratio(name+'_cycles_pct',label+':'+event,label+':cycles:u')
            ratio('branch_mispredict_pct','recovery:branch-misses:u','recovery:branches:u')
            ratio('code_read_mpki','cache:L2I','cache:instructions:u',1000)
            ratio('retired_l2_mpki','cache:FE_L2','cache:instructions:u',1000)
            ratio('retired_l1_mpki','l1:FE_L1','l1:instructions:u',1000)
            ratio('code_read_miss_pct','cache:L2I','cache:L2_CODE_ALL')
            ratio('cycles_per_icache_stall_period','cache:ICACHE_DATA_STALL','cache:ICACHE_STALL_PERIODS',1)
            output[arm][scope]=dict(per_request=counts,ratios=ratios,skipped_ratios=skipped)
        for privilege in ('u','k'):
            counts={key[3]+':'+key[4]:value for key,value in means.items()
                if key[:3]==(arm,'pool',privilege)}
            output[arm]['pool_'+privilege]=dict(per_request=counts)
    result=dict(arms=output,input_pattern=pattern,observations=[dict(arm=k[0],kind=k[1],scope=k[2],label=k[3],event=k[4],
        n=len(v),mean=statistics.mean(v),min=min(v),max=max(v)) for k,v in sorted(observations.items())],
        quality=quality,request_traces=traces,source_sha256=b.sha(__file__),
        limitation='Descriptive independent diagnostic windows, not clean endpoint timing. Sum request-normalized service counts before ratios. Different labels have separate denominators; stalled cycles overlap and must not be added. Top-down fractions describe slots, not request latency or an exclusive critical path. Branch associations and unknown-branch events do not measure BTB occupancy. SWPF counts include original data hints; L1D fill-buffer pressure is not instruction-fetch queue occupancy.')
    b.save(root/'analysis'/output_name,result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    parser.add_argument('--pattern',default='*');parser.add_argument('--output',default='pmu_summary.json')
    args=parser.parse_args();assert '/' not in args.output and '..' not in args.output
    summarize(args.root,args.pattern,args.output)
