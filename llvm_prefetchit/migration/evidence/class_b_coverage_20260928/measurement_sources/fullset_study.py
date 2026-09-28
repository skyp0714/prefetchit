#!/usr/bin/env python3
"""Frozen five-service comparisons and paired log-cost summaries."""
import argparse
import json
import math
from pathlib import Path
import statistics

from scipy.stats import t
import fullset as h


def summarize(rows, arms):
    output={}
    for arm,settings in arms.items():
        for control in settings.get('controls',[]):
            pairs={}
            for row in rows:
                if row['arm'] in (arm,control) and row['valid']:
                    pairs.setdefault(row['block'],{})[row['arm']]=row['metrics']
            metrics={}
            for metric in sorted({k for p in pairs.values() for r in p.values() for k in r}):
                logs=[math.log(p[control][metric]/p[arm][metric]) for p in pairs.values()
                      if set(p)=={arm,control} and p[control].get(metric,0)>0 and p[arm].get(metric,0)>0]
                if not logs:continue
                mean=statistics.mean(logs)
                half=float(t.ppf(.975,len(logs)-1))*statistics.stdev(logs)/math.sqrt(len(logs)) if len(logs)>1 else None
                metrics[metric]=dict(pairs=len(logs),cost_reduction_pct=100*(1-math.exp(-mean)),
                    ci95_pct=[100*(1-math.exp(-(mean-half))),100*(1-math.exp(-(mean+half)))] if half is not None else None)
            output.setdefault(arm,{})[control]=metrics
    return output


def metrics(result):
    result_metrics={'stack_cpu':result['whole_stack_cpu_us_per_request'],
                    'pool_cpu':result['pool']['cpu_us_per_request']}
    for key,row in result['services'].items():
        result_metrics[key+'_cpu']=row['cpu']['cpu_us_per_request']
        if row['pmu']:
            for metric in ('user_cycles_per_request','code_misses_per_request','mpki'):
                result_metrics[key+'_'+metric]=row['pmu'][metric]
    return result_metrics


def study(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    h.c.save(out/'protocol.json',dict(**spec,
        analysis='Paired log cost ratios, individual two-sided 95% t intervals; screen and confirmation separate. No multiplicity correction.',
        invalid='Preserve every attempt; retry an invalid arm at most twice at the same seed. No retry based on performance.'))
    rows=[];names=list(spec['arms'])
    for block in range(spec['blocks']):
        order=names[block%len(names):]+names[:block%len(names)]
        if block//len(names)%2:order.reverse()
        for arm in order:
            for attempt in range(3):
                dest=out/f'{block:02d}_{arm}_{attempt}'
                setting=spec['arms'][arm]
                trial=dict(out=str(dest),family=spec['family'],pool=spec['pool'],seed=spec['seedbase']+block,
                    overrides=setting.get('overrides',{}),pmu=spec.get('pmu',[]))
                if 'kernel' in setting:trial['kernel']=setting['kernel']
                manifest=dest.with_suffix('.json');h.c.save(manifest,trial)
                h.platform(dest,['python3',Path(h.__file__),'trial',manifest])
                result=json.loads((dest/'result.json').read_text())
                row=dict(block=block,arm=arm,attempt=attempt,valid=result['valid'],metrics=metrics(result),output=str(dest))
                rows.append(row);h.c.save(out/'rows.json',rows)
                h.c.save(out/'summary.json',summarize(rows,spec['arms']))
                print(json.dumps(row),flush=True)
                if result['valid']:break
            else:raise RuntimeError(f'{arm} failed three operating gates')
    summary=summarize(rows,spec['arms'])
    h.c.save(out/'complete.json',dict(rows=len(rows),valid_rows=sum(r['valid'] for r in rows),summary=summary))
    return summary


def streams():
    candidates=json.loads((h.OUT/'candidates.json').read_text())
    for family,targets in h.TARGETS.items():
        selected=json.loads((h.OUT/(family+'_selection.json')).read_text())
        # One-arm-at-a-time screen attributes effects to a single changed service.
        # It is exploratory only; simultaneous deployments get independent blocks.
        singles={'base':{}}
        for key in targets:
            singles[key]=dict(overrides={key:candidates[key]['binary']},controls=['base'])
        study(dict(out=str(h.OUT/'individual_screen'/family),family=family,pool=selected['pool'],
            blocks=1,seedbase=14001,arms=singles,pmu=list(targets)))
        arms={
            'base':{},
            'reference':dict(overrides={k:str(h.reference(family,k)) for k in targets},controls=['base']),
            'new_nop':dict(overrides={k:candidates[k]['nop'] for k in targets},controls=['base']),
            'new':dict(overrides={k:candidates[k]['binary'] for k in targets},controls=['base','reference','new_nop'])}
        summary=study(dict(out=str(h.OUT/'confirmation'/family),family=family,pool=selected['pool'],
            blocks=7,seedbase=15001,arms=arms,pmu=[],
            deployment='All three Media or both Social target services changed simultaneously; attribution is to the deployed bundle.'))
        # Independent PMU diagnostic after clean CPU confirmation.
        study(dict(out=str(h.OUT/'pmu_validation'/family),family=family,pool=selected['pool'],
            blocks=1,seedbase=16001,arms=arms,pmu=list(targets)))
        promoted={}
        from fullset_cleanup import cleanup
        for key in targets:
            contrasts=[summary['new'][control][key+'_cpu'] for control in ('base','reference','new_nop')]
            promoted[key]=all(v['pairs']==7 and v['ci95_pct'][0]>0 for v in contrasts)
            if not promoted[key]:
                cleanup([Path(candidates[key]['binary']),Path(candidates[key]['nop'])],
                    h.OUT/'cleanup'/(key+'_rejected.json'),
                    'Seven-block confirmation did not establish incremental target CPU saving against baseline, retained reference and exact-layout NOP; complete compact outcomes retained')
        h.c.save(h.OUT/(family+'_stream_complete.json'),dict(summary=summary,promoted=promoted))
    h.c.save(h.OUT/'streams_complete.json',dict(complete=True,services=list(candidates)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['streams','study'])
    parser.add_argument('manifest',nargs='?',type=Path)
    args=parser.parse_args()
    if args.action=='study':study(json.loads(args.manifest.read_text()))
    else:streams()


if __name__=='__main__':main()
