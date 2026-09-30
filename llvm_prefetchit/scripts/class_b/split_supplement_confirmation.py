#!/usr/bin/env python3
"""Confirm a qualifying L1I supplement against the original in fresh trials."""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b
import fullset as h
from fullset_study import summarize
import split_confirm_study as confirmation
import split_lead_study as lead


def sources():
    return list(dict.fromkeys([Path(__file__), *confirmation.sources()]))


def plan(root):
    dest=root/'l1_confirmation_plan.json'; assert not dest.exists()
    rows=json.loads((root/'l1_screen/screen/rows.json').read_text())
    b.save(dest,dict(source_hashes={str(path):b.sha(path) for path in sources()},
        rows_observed=[dict(block=row['block'],arm=row['arm']) for row in rows],
        candidates=['extra_t1','extra_it0'],blocks=4,seedbase=89701,
        orders=[['original','candidate'],['candidate','original']]*2,
        trigger='After all 16 L1I trials complete: a candidate qualifies if its split75 comparison has a positive lower individual 95% bound for throughput speedup minus one OR whole-CPU/request reduction. If both qualify, select by larger throughput lower bound, then CPU reduction lower bound, then candidate name. No performance-based exclusions, retries, early stopping or extra L1I blocks.',
        selection_bias='This is exploratory selection among two candidates, without multiplicity correction. The following original-baseline trials are fresh and are never pooled or multiplied with previous comparisons.',
        scope='Fresh full Media compose-review C4 including MovieId, eight workload CPUs, 50s warmup and 60s clean ROI. Same 25 post-ROI PMU windows. Four AB/BA paired blocks. Report throughput, average/p99 latency and whole CPU/request regardless of outcome.'))


def campaign(root):
    fixed=json.loads((root/'l1_confirmation_plan.json').read_text())
    assert all(b.sha(path)==sha for path,sha in fixed['source_hashes'].items())
    assert json.loads((root/'l1_screen/complete.json').read_text())['valid']
    data=json.loads((root/'l1_screen/screen_evaluation.json').read_text())
    assert data['complete'] and data['trials']==16
    effects={name:data['e2e'][name]['split75'] for name in fixed['candidates']}
    eligible=[name for name,value in effects.items()
        if value['inverse_rps']['speedup_ci95'][0]>1 or value['stack_cpu']['ci95_pct'][0]>0]
    selected=max(eligible,key=lambda name:(effects[name]['inverse_rps']['speedup_ci95'][0],
        effects[name]['stack_cpu']['ci95_pct'][0],name)) if eligible else None
    dest=root/'l1_confirmation_qualification.json'; assert not dest.exists()
    b.save(dest,dict(qualified=bool(selected),selected=selected,eligible=eligible,effects=effects,
        plan_sha256=b.sha(root/'l1_confirmation_plan.json'),
        input_sha256=b.sha(root/'l1_screen/screen_evaluation.json')))
    if not selected:
        print('Neither L1I supplement qualified for a fresh original-baseline comparison.',flush=True)
        return
    initial=json.loads((root/'prepared_complete.json').read_text())
    previous=json.loads((root/'l1_screen/protocol.json').read_text())
    original=dict(initial['arms']['original']); original.pop('controls',None)
    candidate=dict(previous['arms'][selected],controls=['original'])
    arms={'original':original,selected:candidate}
    assert all(not value.get('hybrid') for value in arms.values())
    assert all(b.sha(value['mongo_binary'])==previous['binary_hashes'][value['mongo_binary']]
        for name,value in arms.items() if name!='original')
    original_hash=initial['binary_hashes'][original['mongo_binary']]
    assert b.sha(original['mongo_binary'])==original_hash
    stage=root/'l1_confirmation_screen'; stage.mkdir(exist_ok=False); (stage/'screen').mkdir();b.space(stage)
    orders=[[selected if name=='candidate' else name for name in order] for order in fixed['orders']]
    protocol=dict(fixed,arms=arms,control='original',orders=orders,monitored=lead.study.MONITORED,
        selected=selected,binary_hashes={value['mongo_binary']:b.sha(value['mongo_binary']) for value in arms.values()})
    for name in ['protocol.json','screen/protocol.json']:b.save(stage/name,protocol)
    rows=[]
    for block,order in enumerate(orders):
        for arm in order:
            b.space(stage); assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
            out=stage/'screen'/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=protocol['seedbase']+block,reverse_pmu=bool(block%2)))
            h.platform(out,['python3',Path(lead.__file__),'trial',manifest])
            value=json.loads((out/'result.json').read_text());assert value['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=value['pool']['achieved_rps'],
                pool_util_pct=value['pool_util_pct'],metrics=dict(mean_ms=value['pool']['mean_ms'],
                p99_ms=value['pool']['p99_ms'],stack_cpu=value['whole_stack_cpu_us_per_request'],
                inverse_rps=1/value['pool']['achieved_rps']))
            rows.append(row);b.save(stage/'screen/rows.json',rows)
            b.save(stage/'screen/summary.json',summarize(rows,arms));print(json.dumps(row),flush=True)
    b.save(stage/'screen/complete.json',dict(rows=len(rows)))
    b.save(stage/'complete.json',dict(valid=True,clean_trials=len(rows)))
    confirmation.report(stage)
    report=stage/'report.md'
    report.write_text(report.read_text().replace('Original versus residual targets: independent full Media C4 confirmation',
        'Original versus L1I supplement: independent full Media C4 confirmation'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['plan','campaign']);parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[args.action](args.root)
