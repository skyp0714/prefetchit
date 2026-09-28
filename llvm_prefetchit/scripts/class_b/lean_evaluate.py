#!/usr/bin/env python3
"""Retain compact complete-campaign evidence and apply frozen decision rules."""
import argparse
import json
from pathlib import Path
import statistics

import dense_build as b


def evaluate(root, candidate=None, matched_nop=None, out=None):
    protocol=json.loads((root/'protocol.json').read_text())
    complete=json.loads((root/'complete.json').read_text())
    rows=json.loads((root/'rows.json').read_text())
    assert complete['rows']==len(rows)==protocol['blocks']*len(protocol['arms'])
    assert all(row['valid'] for row in rows)
    summary=complete['summary']
    means={}; variation={}; services={}; pmu=[]; restoration=[]; workers=[]; service_rows=[]
    for arm in protocol['arms']:
        group=[row for row in rows if row['arm']==arm]
        assert sorted(row['block'] for row in group)==list(range(protocol['blocks']))
        metrics={key:[row['metrics'][key] for row in group] for key in group[0]['metrics']}
        means[arm]={key:statistics.mean(values) for key,values in metrics.items()}
        means[arm].update(rps=statistics.mean(row['achieved_rps'] for row in group),
                         util_pct=statistics.mean(row['pool_util_pct'] for row in group))
        variation[arm]={key:dict(min=min(values),max=max(values),
            sample_cv_pct=100*statistics.stdev(values)/statistics.mean(values) if len(values)>1 else None)
            for key,values in metrics.items()}
        measurements=[]
        for row in group:
            path=Path(row['output']);result=json.loads((path/'result.json').read_text())
            clock=json.loads((path/'clock_restoration.json').read_text())
            scheduler=json.loads((path/'scheduler_restoration.json').read_text())
            platform=json.loads((path.with_name(path.name+'_platform')/'verified.json').read_text())
            assert clock['unloaded'] and scheduler['restored'] and platform['restored']
            restoration.append(dict(arm=arm,block=row['block'],clock=clock,scheduler=scheduler,platform=platform))
            measurements.append(result['all_services'])
            service_metrics={name+':'+metric:values[metric]
                for name,values in result['all_services'].items()
                if name in ('movie-id-service','compose-review-service','rating-service')
                for metric in ('cpu_us_per_request','user_us_per_request')}
            service_rows.append(dict(arm=arm,block=row['block'],valid=True,metrics=service_metrics,
                result_sha256=b.sha(path/'result.json')))
            worker_path=path/'nginx_processes_postroi.json'
            if worker_path.exists():
                snapshot=json.loads(worker_path.read_text())
                ticks=[p['user_ticks']+p['system_ticks'] for p in snapshot['processes']
                       if p['command'].startswith('nginx: worker process')]
                total=sum(ticks)
                workers.append(dict(arm=arm,block=row['block'],worker_cpu_ticks=ticks,
                    effective_workers=total*total/sum(x*x for x in ticks) if total else None,
                    max_worker_share_pct=100*max(ticks)/total if total else None,
                    nginx_cpu_us_per_request=result['all_services']['nginx-web-server']['cpu_us_per_request'],
                    stack_cpu_us_per_request=row['metrics']['stack_cpu'],
                    snapshot_sha256=b.sha(worker_path),unavailable=snapshot['unavailable'],
                    interpretation=snapshot['interpretation']))
            if result.get('pmu'):
                pmu.append(dict(arm=arm,block=row['block'],services=result['pmu'],extra=result.get('pmu_extra',{})))
        services[arm]={name:{key:statistics.mean(m[name][key] for m in measurements)
            for key in ('cpu_us_per_request','user_us_per_request')}
            for name in measurements[0]}
    decisions={}
    throughput={}
    for name,contrasts in summary.items():
        throughput[name]={}
        for control,metrics in contrasts.items():
            inverse=metrics['inverse_rps']
            def convert(value):return 100*(1/(1-value/100)-1)
            throughput[name][control]=dict(pairs=inverse['pairs'],
                gain_pct=convert(inverse['cost_reduction_pct']),
                ci95_pct=[convert(value) for value in inverse['ci95_pct']] if inverse['ci95_pct'] else None)
    comparisons=([(candidate,matched_nop)] if candidate else
                 [(name,next((control for control in setting.get('controls',[]) if control.endswith('_nop')),None))
                  for name,setting in protocol['arms'].items() if name.endswith('_it0')])
    for name,nop in comparisons:
        assert nop and name in summary
        controls=('base',nop)
        point_checks={control:{metric:summary[name][control][metric]['cost_reduction_pct']>
                      (-2 if metric=='p99_ms' else 0)
                      for metric in ('stack_cpu','mean_ms','p99_ms')} for control in controls}
        interval_checks={control:{metric:(summary[name][control][metric]['ci95_pct'] is not None and
            summary[name][control][metric]['ci95_pct'][0]>(-2 if metric=='p99_ms' else 0))
            for metric in ('stack_cpu','mean_ms','p99_ms')} for control in controls}
        enough=protocol['blocks']>=6
        decisions[name]=dict(matched_nop=nop,point_eligible=all(all(x.values()) for x in point_checks.values()),
            point_checks=point_checks,confirmation_checks=interval_checks,
            confirmed=bool(candidate and enough and all(all(x.values()) for x in interval_checks.values())),
            minimum_effect_pct=min(summary[name][control][metric]['cost_reduction_pct']
                for control in controls for metric in ('stack_cpu','mean_ms')))
    result=dict(campaign=str(root),protocol_sha256=b.sha(root/'protocol.json'),driver_sha256=b.sha(__file__),rows=len(rows),
        independent_confirmation=bool(candidate),means=means,variation=variation,decisions=decisions,
        comparisons=summary,throughput=throughput,services=services,workers=workers,
        limitations=['Individual paired log t95 intervals, all frozen promotion criteria must pass.',
          'Screen observations are never pooled into independent confirmation.',
          'Closed-loop throughput and mean latency are related, not independent confirmations.',
          'PMU windows follow clean timing; bracketing request normalization includes perf startup/teardown.',
          'ITLB_WALK (0x11/0x0e) is completed page walks, not walk-active cycles.',
          'L2I is a speculative instruction-fetch miss event; FE_L2 is a retired front-end event. Neither count is a cycle fraction.'])
    out=out or root
    from fullset_study import summarize
    b.save(out/'service_rows.json',service_rows)
    b.save(out/'service_comparisons.json',dict(comparisons=summarize(service_rows,protocol['arms']),
        interpretation='Secondary decomposition of the three modified services; individual unadjusted paired-log t95 intervals. These do not replace whole-stack E2E promotion criteria.'))
    b.save(out/'evaluation.json',result)
    b.save(out/'compact_pmu.json',pmu)
    b.save(out/'restoration_audit.json',restoration)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('--candidate');parser.add_argument('--matched-nop')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();assert bool(args.candidate)==bool(args.matched_nop)
    result=evaluate(args.root,args.candidate,args.matched_nop,args.out)
    print(json.dumps(dict(means=result['means'],decisions=result['decisions']),indent=2))
