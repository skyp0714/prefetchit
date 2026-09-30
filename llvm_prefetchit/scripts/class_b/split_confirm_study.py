#!/usr/bin/env python3
"""Fresh original-versus-residual confirmation, conditional on completed follow-up."""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b
import fullset as h
from fullset_study import summarize
import split_lead_study as lead
from split_coverage_campaign import report as endpoint_report
from split_topdown_report import report as topdown_report


def sources():
    return [Path(__file__), Path(lead.__file__), Path(lead.study.__file__),
        Path(lead.study.hybrid.__file__), Path(lead.study.balanced_backend.__file__),
        Path(lead.study.backend_study.__file__), Path(__file__).with_name('balanced_load.py'),
        Path(__file__).with_name('dense_causes.py')]


def plan(root):
    destination=root/'confirmation_plan.json'; assert not destination.exists()
    rows=json.loads((root/'lead_screen/screen/rows.json').read_text())
    b.save(destination,dict(source_hashes={str(path):b.sha(path) for path in sources()},
        followup_rows_observed_at_plan=len(rows), blocks=4, seedbase=89401,
        orders=[['original','residual_t1'],['residual_t1','original']]*2,
        trigger='After all 16 follow-up trials complete: residual_t1 versus split75 has a positive lower individual 95% bound for throughput speedup minus one OR whole-CPU/request reduction. Never stop or extend the follow-up based on interim performance.',
        scope='Fresh full Media compose-review C4 including MovieId, eight workload CPUs, 50s warmup and 60s clean ROI. Same 25 post-ROI PMU windows. Four AB/BA paired blocks, no performance-based exclusions or retries. Results remain separate from preceding campaigns.',
        rationale='If the fixed-layout residual candidate improves performance, directly measure its original-baseline speedup instead of multiplying ratios from separate campaigns. Confirmation plan was set after inspecting the recorded number of exploratory follow-up trials, before any confirmation endpoint data.'))


def report(stage):
    endpoint_report(stage)
    path=stage/'report.md'
    path.write_text(path.read_text().replace('Continuation-aware placement: fresh full Media C4',
        'Original versus residual targets: independent full Media C4 confirmation').replace(
        'PMU windows follow the clean ROI and cover three MongoDBs only;',
        'Cache/prefetch PMU windows follow the clean ROI and cover three MongoDBs; separate top-down/memory windows also cover pool user and kernel execution;'))
    topdown_report(stage,plot=True)


def campaign(root):
    fixed=json.loads((root/'confirmation_plan.json').read_text())
    assert all(b.sha(path)==sha for path,sha in fixed['source_hashes'].items())
    assert json.loads((root/'lead_screen/complete.json').read_text())['valid']
    results=json.loads((root/'lead_screen/screen_evaluation.json').read_text())
    assert results['complete'] and results['trials']==16
    effect=results['e2e']['residual_t1']['split75']
    qualified=(effect['inverse_rps']['speedup_ci95'][0]>1 or effect['stack_cpu']['ci95_pct'][0]>0)
    b.save(root/'confirmation_qualification.json',dict(qualified=qualified,effect=effect,
        input_sha256=b.sha(root/'lead_screen/screen_evaluation.json'),plan_sha256=b.sha(root/'confirmation_plan.json')))
    if not qualified:
        print('Residual candidate did not qualify for an additional original-baseline performance comparison.',flush=True)
        return
    initial=json.loads((root/'prepared_complete.json').read_text())
    followup=json.loads((root/'lead_screen/protocol.json').read_text())
    original=dict(initial['arms']['original']); original.pop('controls',None)
    candidate=dict(followup['arms']['residual_t1'],controls=['original'])
    arms=dict(original=original,residual_t1=candidate)
    for value in arms.values(): assert not value.get('hybrid')
    stage=root/'confirmation_screen'; stage.mkdir(exist_ok=False); (stage/'screen').mkdir(); b.space(stage)
    protocol=dict(fixed,arms=arms,control='original',monitored=lead.study.MONITORED,
        binary_hashes={v['mongo_binary']:b.sha(v['mongo_binary']) for v in arms.values()})
    for name in ['protocol.json','screen/protocol.json']:b.save(stage/name,protocol)
    rows=[]
    for block,order in enumerate(protocol['orders']):
        for arm in order:
            b.space(stage)
            assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
            out=stage/'screen'/f'{block:02d}_{arm}'; manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=protocol['seedbase']+block,reverse_pmu=bool(block%2)))
            h.platform(out,['python3',Path(lead.__file__),'trial',manifest])
            value=json.loads((out/'result.json').read_text()); assert value['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=value['pool']['achieved_rps'],
                pool_util_pct=value['pool_util_pct'],metrics=dict(mean_ms=value['pool']['mean_ms'],p99_ms=value['pool']['p99_ms'],
                stack_cpu=value['whole_stack_cpu_us_per_request'],inverse_rps=1/value['pool']['achieved_rps']))
            rows.append(row); b.save(stage/'screen/rows.json',rows)
            b.save(stage/'screen/summary.json',summarize(rows,arms)); print(json.dumps(row),flush=True)
    b.save(stage/'screen/complete.json',dict(rows=len(rows)))
    b.save(stage/'complete.json',dict(valid=True,clean_trials=len(rows)))
    report(stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['plan','campaign','report']); parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame): raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[args.action](args.root)
