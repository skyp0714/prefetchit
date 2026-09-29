#!/usr/bin/env python3
"""Freeze a screen choice, then use fresh seeds and separate wake diagnostics."""
import argparse
import gzip
import json
from pathlib import Path
import dense_build as b
import fullset as h
from e2e_lbr import remove_generated
from mechanism_report import crossover,evaluate
from residual_retarget import thin_by_age,thin_patch,lead_rows,plan,patch
from lean_plan import read_image

RULE=('Prefer largest measured throughput speedup among policies with >=20% retired L2 reduction, '
      'nonnegative whole-stack CPU reduction and no more than 1% p99 increase versus same-layout NOP. '
      'If none qualifies, diagnose the largest retired L2 reduction instead; do not label that an E2E winner. '
      'Fresh confirmation is never pooled with the selection screen.')

def extra_policies(root):
    builds={name:{} for name in ['thin_by_age','aggressive64']}
    for key,exe in b.SERVICES.items():
        b.space(root)
        with gzip.open(root/'refine_observations'/f'{key}.json.gz','rt') as f:rows=json.load(f)
        source=root/'builds/retarget_t1'/key/exe
        targets={r['site']:r['target'] for r in read_image(source)['records'] if r['active'] and r['direct']}
        result=thin_by_age(rows,targets);dest=root/'builds/thin_by_age'/key/exe
        b.save(dest.with_suffix('.plan.json'),result);thin_patch(source,dest,result['drop'],b.sha(source))
        builds['thin_by_age'][key]=str(dest)
        source=root/'builds/selected_t1'/key/exe
        targets={r['site']:r['target'] for r in read_image(source)['records'] if r['active'] and r['direct']}
        result=plan(lead_rows(rows,64,8192),targets,max_fraction=1,min_gain=2,protected_rows=rows)
        dest=root/'builds/aggressive64'/key/exe;b.save(dest.with_suffix('.plan.json'),result)
        patch(source,dest,result['changes'],b.sha(source));builds['aggressive64'][key]=str(dest)
        print(json.dumps(dict(built_service=key,aggressive_changed_sites=len(result['changes']))),flush=True)
    b.save(root/'extra_policy_builds.json',dict(builds=builds,rule='Same retained NOP training, no added sites/code bytes. Thin separately by observed age band; aggressive targets lower minimum net gain from 8 to 2 samples.'))
    return builds

def run(root):
    nonstationary=(root/'crossover_nonstationarity.json').exists()
    assert (root/'crossover/complete.json').exists() or nonstationary
    crossover(root/'crossover',root/'crossover_evaluation.json')
    result=json.loads((root/'crossover_evaluation.json').read_text())
    spec=json.loads((root/'crossover_spec.json').read_text());candidates=[]
    for name in spec['variants']:
        e=result['e2e'][name]['nop'];p=result['pmu'][name]['nop']
        candidate=dict(name=name,speedup=e['inverse_rps']['speedup'],
            cpu_reduction=e['stack_cpu']['cost_reduction_pct'],p99_reduction=e['p99_ms']['cost_reduction_pct'],
            retired_l2_reduction=p['cache:sum:FE_L2']['cost_reduction_pct'])
        candidate['eligible']=candidate['retired_l2_reduction']>=20 and candidate['cpu_reduction']>=0 and candidate['p99_reduction']>=-1
        candidates.append(candidate)
    eligible=[r for r in candidates if r['eligible']]
    chosen=max(eligible,key=lambda x:(x['speedup'],x['retired_l2_reduction'])) if eligible else max(candidates,key=lambda x:x['retired_l2_reduction'])
    rule=RULE
    if nonstationary:
        chosen=next(x for x in candidates if x['name']=='retarget')
        rule='Long crossover E2E rejected for write-state growth. Retarget is the existing mechanism reference from the completed fresh-stack retarget screen (29% retired L2 reduction), not an E2E-selected winner. Compare it and two frozen refinements at equal fresh-stack workload age.'
    b.save(root/'confirmation_selection.json',dict(rule=rule,candidates=candidates,chosen=chosen,
        source_sha256=b.sha(__file__),no_e2e_eligible_policy=not bool(eligible),
        crossover_e2e_rejected=nonstationary,
        limitation='Screen choice only. No original-baseline or independently confirmed E2E claim.'))
    selected=spec['variants'][chosen['name']]
    # The old-target and original retarget bundles remain active mechanism
    # references. Reject unused new exploratory binaries immediately.
    unused=[]
    for name in ['protected128','protected512','retarget_thin']:
        if name!=chosen['name']:unused.extend(Path(p) for p in spec['variants'][name].values())
    if unused:remove_generated(unused,root/'screen_rejected_cleanup.json',
        'Screen selection frozen; compact outcomes, hashes, source/patch records and plans retained. These new candidate executables will not be used in confirmation.')
    previous=json.loads((root/'retarget_screen_spec.json').read_text())
    baseline=dict(out=str(root/'stack_frontend'),overrides=previous['arms']['base']['overrides'],seed=74001)
    b.save(root/'stack_frontend_spec.json',baseline)
    h.platform(root/'stack_frontend',['python3',Path(__file__).with_name('stack_frontend.py'),root/'stack_frontend_spec.json'])
    extras=extra_policies(root)
    confirm=dict(out=str(root/'confirmation'),blocks=4,seedbase=72001,exploratory=True,
        arms=dict(base=previous['arms']['base'],selected_nop=previous['arms']['selected_nop'],
            candidate=dict(overrides=selected,controls=['base','selected_nop'])),
        pmu_event_sets=previous['pmu_event_sets'],
        phase='Fresh-seed confirmation after the frozen within-process screen; C4 full Media stack',
        selected_name=chosen['name'])
    for name,overrides in extras.items():
        confirm['arms'][name]=dict(overrides=overrides,controls=['base','selected_nop','candidate'])
    confirm['phase']='Fresh-stack equal-age four-block validation of the retained retarget reference, plus exploratory tests of age-preserving thinning and more aggressive target coverage. Individual intervals, no multiplicity correction. Long crossover E2E is not pooled or used to choose the reference.' if nonstationary else 'Independent four-block confirmation of the frozen screen candidate, plus exploratory tests of age-preserving thinning and more aggressive target coverage. Individual intervals, no multiplicity correction.'
    b.save(root/'confirmation_spec.json',confirm)
    validate(root)

def validate(root):
    confirm=json.loads((root/'confirmation_spec.json').read_text())
    selected=confirm['arms']['candidate']['overrides']
    if not (root/'confirmation/complete.json').exists():
        b.run(['python3',Path(__file__).with_name('mechanism_study.py'),root/'confirmation_spec.json'],root/'confirmation_driver.log')
    evaluate(root/'confirmation',root/'confirmation_evaluation.json')
    timeline=dict(out=str(root/'wake_validation'),trials=[dict(name=name,concurrency=4,clock=False,
        overrides=overrides,services=list(b.SERVICES),periods=periods,seed=73001)
        for name,overrides,periods in [('base',confirm['arms']['base']['overrides'],[1021,4093]),
            ('candidate',selected,[4093,1021])]])
    b.save(root/'wake_validation_spec.json',timeline)
    b.run(['python3',Path(__file__).with_name('lean_timeline.py'),'campaign',root/'wake_validation_spec.json'],root/'wake_validation_driver.log')
    from lean_timeline_summary import summarize
    summarize(root/'wake_validation')
    b.save(root/'confirmation_followup_complete.json',dict(selected=confirm['selected_name'],fresh_trials=20,
        diagnostic_captures=12,confirmation=str(root/'confirmation_evaluation.json')))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--prepared',action='store_true');a=p.parse_args()
    (validate if a.prepared else run)(a.root)
