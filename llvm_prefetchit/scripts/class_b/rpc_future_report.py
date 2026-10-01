#!/usr/bin/env python3
"""Compact independent E2E and sequential-PMU summaries, without pooling them."""
import argparse
import collections
import json
from pathlib import Path
import statistics

import dense_build as b
from mechanism_report import evaluate


def build(root):
    report={}
    for phase in ('screen','confirmation'):
        folder=root/phase
        if not (folder/'complete.json').exists():continue
        existing=folder/'evaluation.json'
        result=json.loads(existing.read_text()) if existing.exists() else evaluate(folder,root/'analysis'/(phase+'_evaluation.json'))
        report[phase]=dict(trials=result['trials'],absolute={k:dict(rps=v['rps'],util_pct=v['util_pct'],**v['e2e'])
            for k,v in result['absolute'].items()},comparisons=result['e2e'])
    diagnostic_rows=[]
    for path in sorted((root/'diagnostics').glob('*/result.json')):
        result=json.loads(path.read_text());assert result['valid'];block,name=path.parent.name.split('_',1)
        groups={'app_servers':collections.defaultdict(float),'mongodb':collections.defaultdict(float)}
        for label,services in result['pmu_extra'].items():
            for key,window in services.items():
                assert window['fully_scheduled']
                group=groups['mongodb' if key.startswith('mongo_') else 'app_servers']
                for event,value in window['per_request'].items():group[label+':'+event]+=value
        for group,values in groups.items():
            values['topdown:frontend_pct']=100*values['topdown:topdown-fe-bound:u']/values['topdown:slots:u']
            values['topdown:backend_pct']=100*values['topdown:topdown-be-bound:u']/values['topdown:slots:u']
            values['translation:frontend_pct']=100*values['translation:FE_BUBBLES']/values['translation:SLOTS']
            diagnostic_rows.append(dict(block=int(block),arm=name,group=group,values=dict(values)))
    if diagnostic_rows:
        means={}
        for name in sorted({r['arm'] for r in diagnostic_rows}):
            means[name]={}
            for group in ('app_servers','mongodb'):
                rows=[r['values'] for r in diagnostic_rows if r['arm']==name and r['group']==group]
                means[name][group]={k:statistics.mean(r[k] for r in rows) for k in rows[0]}
        report['diagnostics']=dict(rows=diagnostic_rows,means=means,
            limitation='Separate sequential three-second request-normalized cgroup windows. Nine app processes and three busy MongoDBs; not simultaneous full-stack counts or causal request-time fractions. E2E from diagnostic runs is excluded.')
    b.save(root/'analysis/report.json',report)
    for phase in ('screen','confirmation'):
        if phase in report:
            print(phase)
            for name,values in report[phase]['absolute'].items():
                print(name, {k:round(v,4) for k,v in values.items()})
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();build(a.root)
