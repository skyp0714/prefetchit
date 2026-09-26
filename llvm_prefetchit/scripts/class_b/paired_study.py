#!/usr/bin/env python3
"""Run a frozen, fresh-process paired study from an explicit arm manifest."""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess

import social_headroom as h
from scipy.stats import t


def summarize(rows,arms):
    output={}
    metrics=('target_cpu','pool_cpu','stack_cpu','user_cycles','code_misses')
    for arm,config in arms.items():
        if 'controls' not in config:
            continue
        comparisons={}
        for control in config['controls']:
            pairs={}
            for row in rows:
                if row['arm'] in (arm,control) and row['valid']:
                    pairs.setdefault(row['block'],{})[row['arm']]=row
            result={}
            for metric in metrics:
                logs=[math.log(pair[control][metric]/pair[arm][metric]) for pair in pairs.values()
                      if set(pair)=={arm,control} and pair[control][metric] and pair[arm][metric]]
                if not logs:
                    continue
                mean=statistics.mean(logs)
                half=float(t.ppf(.975,len(logs)-1))*statistics.stdev(logs)/math.sqrt(len(logs)) if len(logs)>1 else None
                result[metric]=dict(pairs=len(logs),cost_reduction_pct=100*(1-math.exp(-mean)),
                    ci95_pct=[100*(1-math.exp(-(mean-half))),100*(1-math.exp(-(mean+half)))] if half is not None else None)
            comparisons[control]=result
        output[arm]=comparisons
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path)
    a=p.parse_args()
    spec=json.loads(a.manifest.read_text())
    out=Path(spec['out'])
    out.mkdir(parents=True,exist_ok=False)
    h.c.save(out/'protocol.json',dict(**spec,manifest_sha256=h.c.sha(a.manifest),
        analysis='paired log cost ratios, individual 95% t intervals, exploratory and confirmation kept separate',
        multiplicity='No family-wise correction; do not treat exploratory best-of-many as confirmed'))
    arms=spec['arms']
    names=list(arms)
    rows=[]
    for block in range(spec['blocks']):
        order=names[block%len(names):]+names[:block%len(names)]
        if (block//len(names))%2:
            order=list(reversed(order))
        for name in order:
            arm=arms[name]
            trial=out/f'{block:02d}_{name}'
            command=['python3',str(h.REPO/'llvm_prefetchit/results/class_b_extension_20260926/run_platform.py'),
                     '--out',str(trial.with_name(trial.name+'_platform')),'--cpus','16-19,32-43',
                     'python3',str(h.REPO/'llvm_prefetchit/scripts/class_b/social_headroom.py'),
                     '--out',str(trial),'--pool',str(spec['pool']),'--rate',str(spec['rate']),
                     '--seed',str(spec['seedbase']+block),'--binary',arm['binary'],
                     '--kernel-mode',arm.get('kernel_mode','off')]
            if arm.get('kernel_plan'):
                command+=['--kernel-plan',arm['kernel_plan']]
            if not spec.get('pmu',True):
                command+=['--no-pmu']
            h.c.run(command,out/(trial.name+'.log'),timeout=1200)
            result=json.loads((trial/'result.json').read_text())
            pmu=result.get('pmu')
            row=dict(block=block,arm=name,valid=result['valid'],target_cpu=result['target']['cpu_us_per_request'],
                pool_cpu=result['pool']['cpu_us_per_request'],stack_cpu=result['whole_stack_cpu_us_per_request'],
                user_cycles=pmu['user_cycles_per_request'] if pmu else None,
                code_misses=pmu['code_misses_per_request'] if pmu else None,
                mpki=pmu['mpki'] if pmu else None,p99_ms=result['target']['p99_ms'],
                kernel_switches=(result['kernel_after']['matched_switches']-result['kernel_before']['matched_switches'])
                if result['kernel_after'] else None,output=str(trial))
            rows.append(row)
            h.c.save(out/'rows.json',rows)
            h.c.save(out/'paired_summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True)
    h.c.save(out/'complete.json',dict(rows=len(rows),valid=sum(r['valid'] for r in rows)))


if __name__=='__main__':main()
