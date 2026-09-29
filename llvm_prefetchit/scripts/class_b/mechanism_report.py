#!/usr/bin/env python3
"""Separate clean E2E ratios from sequential PMU event populations."""
import argparse
import json
import math
from pathlib import Path
import statistics
import dense_build as b
from fullset_study import summarize

def service_costs(accounts):
    targets={'movie-id-service','compose-review-service','rating-service'}
    values={}
    for name,cost in accounts.items():
        for field in ['cpu_us','user_us','system_us']:
            if field not in cost:continue
            value=cost[field]/cost['completed']
            values[f'{name}:{field}/request']=value
            group='targets' if name in targets else 'other_services'
            key=f'{group}:{field}/request';values[key]=values.get(key,0)+value
    return values

def evaluate(root, out):
    protocol=json.loads((root/'protocol.json').read_text())
    rows=json.loads((root/'rows.json').read_text())
    pmu=[];absolute={};cpu=[]
    for row in rows:
        r=json.loads((Path(row['output'])/'result.json').read_text())
        assert row['valid'] and r['valid']
        cpu.append(dict(block=row['block'],arm=row['arm'],valid=True,metrics=service_costs(r['all_services'])))
        values={}
        sets=dict(r['pmu_extra'])
        if r['pmu']:sets['primary']=r['pmu']
        for label,services in sets.items():
            assert set(services)==set(protocol.get('monitored',b.SERVICES))
            for service,counts in services.items():
                assert counts['fully_scheduled'] and counts['window']['completed']>0
                for event,value in counts['per_request'].items():
                    values[f'{label}:{service}:{event}']=value
                    key=f'{label}:sum:{event}';values[key]=values.get(key,0)+value
                for event,value in counts['counters'].items():
                    values[f'{label}:{service}:{event}/ki']=1000*value/counts['counters']['instructions:u']
                if 'FE_BUBBLES' in counts['counters']:
                    values[f'{label}:{service}:frontend_bound_pct']=100*counts['counters']['FE_BUBBLES']/counts['counters']['SLOTS']
        pmu.append(dict(block=row['block'],arm=row['arm'],valid=True,metrics=values))
    for arm in protocol['arms']:
        a=[x for x in rows if x['arm']==arm]
        p=[x for x in pmu if x['arm']==arm]
        if not a:continue
        absolute[arm]=dict(trials=len(a),e2e={k:statistics.mean(x['metrics'][k] for x in a) for k in a[0]['metrics']},
            rps=statistics.mean(x['achieved_rps'] for x in a),util_pct=statistics.mean(x['pool_util_pct'] for x in a),
            service_cpu={k:statistics.mean(x['metrics'][k] for x in cpu if x['arm']==arm) for k in cpu[0]['metrics']},
            pmu={k:statistics.mean(x['metrics'][k] for x in p) for k in p[0]['metrics']})
    e2e=summarize(rows,protocol['arms'])
    for controls in e2e.values():
        for metrics in controls.values():
            for value in metrics.values():
                value['speedup']=1/(1-value['cost_reduction_pct']/100)
                value['speedup_ci95']=[1/(1-x/100) for x in value['ci95_pct']] if value['ci95_pct'] else None
    result=dict(trials=len(rows),complete=(root/'complete.json').exists(),absolute=absolute,e2e=e2e,
        pmu=summarize(pmu,protocol['arms']),pmu_rows=pmu,service_cpu=summarize(cpu,protocol['arms']),
        interpretation='Individual paired-log t95 intervals, no multiplicity correction. Two-block screens are exploratory. E2E precedes PMU; no E2E inference from code misses. LATE_SWPF zero-control values are retained as absolute counts, not undefined percentage ratios. Service-summed PMU counts combine separate request-normalized windows.')
    b.save(out,result);return result

def probes(root, out):
    grouped=[]
    for name in ['probe','probe_serialized','probe_fixed']:
        path=root/name/'rows.json'
        if not path.exists():continue
        rows=json.loads(path.read_text())
        settings=sorted({(x['kind'],x['demand'],x['flush'],x['lead_iterations']) for x in rows})
        for kind,demand,flush,lead in settings:
            rr=[x for x in rows if (x['kind'],x['demand'],x['flush'],x['lead_iterations'])==(kind,demand,flush,lead)]
            grouped.append(dict(experiment=name,kind=kind,demand=demand,flush=flush,lead_iterations=lead,n=len(rr),
                mean_call_tsc=statistics.mean(x['mean_call_tsc'] for x in rr),
                call_tsc_range=[min(x['mean_call_tsc'] for x in rr),max(x['mean_call_tsc'] for x in rr)],
                events_per_iteration={k:statistics.mean(x['counters'][k]/x['iterations'] for x in rr) for k in rr[0]['counters']}))
    b.save(out,dict(rows=grouped,limitation='Synthetic CLFLUSH/calibration, not service speedup. Hint-line invalidation changes multiple frontend structures; DSB-specific causality requires additional controls.'))

def crossover(root,out):
    protocol=json.loads((root/'protocol.json').read_text());rows=json.loads((root/'stack_rows.json').read_text())
    names=['nop',*protocol['variants']]
    arms={name:dict(controls=[c for c in protocol.get('controls',['nop','t1','retarget']) if c in names and c!=name]) for name in names if name!='nop'}
    pmu=[];absolute={};cpu=[]
    for block in sorted({r['block'] for r in rows}):
        result=json.loads((root/f'{block:02d}'/'result.json').read_text());assert result['valid']
        for arm in names:
            values={}
            cc=[service_costs(r['services']) for r in result['rows'] if r['arm']==arm]
            cpu.append(dict(block=block,arm=arm,valid=True,metrics={k:math.exp(statistics.mean(math.log(x[k]) for x in cc)) if all(x[k]>0 for x in cc) else statistics.mean(x[k] for x in cc) for k in cc[0]}))
            groups={}
            for entry in result['pmu']:
                if entry['arm']==arm:groups.setdefault((entry['label'],entry['service']),[]).append(entry)
            for (label,service),entries in groups.items():
                assert all(e['fully_scheduled'] for e in entries)
                co={event:sum(e['counters'][event] for e in entries) for event in entries[0]['counters']}
                completed=sum(e['window']['completed'] for e in entries)
                for event,total in co.items():
                    value=total/completed
                    values[f'{label}:{service}:{event}']=value
                    key=f'{label}:sum:{event}';values[key]=values.get(key,0)+value
                if 'FE_BUBBLES' in co:values[f'{label}:{service}:frontend_bound_pct']=100*co['FE_BUBBLES']/co['SLOTS']
            pmu.append(dict(block=block,arm=arm,valid=True,metrics=values))
    for arm in names:
        a=[r for r in rows if r['arm']==arm];p=[r for r in pmu if r['arm']==arm]
        absolute[arm]=dict(stacks=len(a),e2e={k:statistics.mean(r['metrics'][k] for r in a) for k in a[0]['metrics']},
            service_cpu={k:statistics.mean(x['metrics'][k] for x in cpu if x['arm']==arm) for k in cpu[0]['metrics']},
            pmu={k:statistics.mean(r['metrics'][k] for r in p) for k in p[0]['metrics']})
    e2e=summarize(rows,arms)
    for controls in e2e.values():
        for metrics in controls.values():
            for v in metrics.values():
                v['speedup']=1/(1-v['cost_reduction_pct']/100)
                v['speedup_ci95']=[1/(1-x/100) for x in v['ci95_pct']] if v['ci95_pct'] else None
    b.save(out,dict(complete=(root/'complete.json').exists(),e2e_causal_usable=not (root.parent/'crossover_nonstationarity.json').exists(),
        rejection_record=str(root.parent/'crossover_nonstationarity.json') if (root.parent/'crossover_nonstationarity.json').exists() else None,
        e2e=e2e,pmu=summarize(pmu,arms),pmu_rows=pmu,absolute=absolute,service_cpu=summarize(cpu,arms),
        interpretation='Independent units are fresh stacks; two clean intervals per arm collapsed to log mean within each stack. Exploratory multiple-policy screen with individual paired-log t95 intervals and no multiplicity adjustment. Exact-layout NOP, not original uninstrumented baseline. PMU windows separate from clean ROIs.'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['service','probes','crossover']);p.add_argument('root',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    {'service':evaluate,'probes':probes,'crossover':crossover}[a.mode](a.root,a.out)
