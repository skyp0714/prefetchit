#!/usr/bin/env python3
"""Describe complete CPU-pool diagnostics without treating events as causes."""
import argparse
import collections
import json
from pathlib import Path
import statistics
import dense_build as b


def report(root):
    source=root/'result.json';data=json.loads(source.read_text())
    assert data['valid']
    samples=collections.defaultdict(list)
    for row in data['windows']:
        assert row['fully_scheduled']
        p=row['privilege'];counts=row['counters'];per=row['per_request']
        cycles=counts['cycles:'+p];instructions=counts['instructions:'+p]
        for event,value in per.items():
            name=event.removesuffix(':'+p)
            samples[p+':'+row['label']+':'+name+'/request'].append(value)
            if instructions:
                samples[p+':'+row['label']+':'+name+'/ki'].append(counts[event]/instructions*1000)
        for event in ['ICACHE_DATA_STALL','ITLB_WALK_ACTIVE','UNKNOWN_BRANCH_CYCLES']:
            if event in counts and cycles:
                samples[p+':'+row['label']+':'+event+'/cycles_pct'].append(100*counts[event]/cycles)
        if 'FE_BUBBLES' in counts and counts.get('SLOTS'):
            samples[p+':frontend:frontend_bound_pct'].append(100*counts['FE_BUBBLES']/counts['SLOTS'])
        if counts.get('branches:'+p):
            samples[p+':branch:misprediction_pct'].append(100*counts['branch-misses:'+p]/counts['branches:'+p])
        if counts.get('DSB_UOPS',0)+counts.get('MITE_UOPS',0):
            samples[p+':decode:dsb_share_of_dsb_mite_pct'].append(100*counts['DSB_UOPS']/(counts['DSB_UOPS']+counts['MITE_UOPS']))
    metrics={key:dict(mean=statistics.mean(values),minimum=min(values),maximum=max(values),repeats=len(values),values=values)
             for key,values in sorted(samples.items())}
    limitation=('Separate user/kernel windows on workload CPUs 32-39. Values are two-repeat diagnostic means/ranges, '
        'not confidence intervals. Per-window requests/instructions/cycles are the denominators. Overlapping frontend '
        'events do not partition stall causes. Unknown-branch bubbles are not a direct count of absent BTB entries '
        'or missed FDIP opportunities. DSB share excludes other uop sources. No E2E inference.')
    b.save(root/'summary.json',dict(metrics=metrics,limitation=limitation,result_sha256=b.sha(source),source_sha256=b.sha(__file__)))
    display=[('cache:cycles/request','Cycles/request'),('cache:FE_L2/request','Retired L2 events/request'),
        ('cache:L2I/request','Speculative code-read misses/request'),
        ('cache:ICACHE_DATA_STALL/cycles_pct','I-cache data-stall cycles (%)'),
        ('frontend:ITLB_WALK_ACTIVE/cycles_pct','Instruction page-walk active cycles (%)'),
        ('frontend:frontend_bound_pct','Frontend bound (%)'),
        ('branch:FE_ITLB/request','Retired ITLB events/request'),
        ('branch:misprediction_pct','Retired branch misprediction (%)'),
        ('decode:UNKNOWN_BRANCH_CYCLES/cycles_pct','Unknown-branch bubble cycles (%)'),
        ('decode:dsb_share_of_dsb_mite_pct','DSB share of DSB + MITE uops (%)')]
    lines=['# Original full Media C4: user/kernel frontend diagnostics','',
           '| Metric | User mean [range] | Kernel mean [range] |','|---|---:|---:|']
    for key,label in display:
        values=[]
        for p in ['u','k']:
            value=metrics[p+':'+key]
            values.append(f"{value['mean']:.3f} [{value['minimum']:.3f}, {value['maximum']:.3f}]")
        lines.append('| '+label+' | '+' | '.join(values)+' |')
    lines += ['',limitation,'',
        'Event definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).']
    (root/'summary.md').write_text('\n'.join(lines)+'\n')
    return metrics


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();report(args.root)
