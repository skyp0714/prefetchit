#!/usr/bin/env python3
"""Follow whole-stack miss attribution with padding-only backend prefetch tests.

No performance claim is selected from the rejected long-lived write crossover.
Training, held-out coverage, clean screen and wake profiles use separate seeds.
"""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b
import fullset as h
from mechanism_report import evaluate

def run(parent):
    assert (parent/'confirmation_followup_complete.json').exists(),'Finish native measurements before backend work'
    root=parent/'backend';root.mkdir(exist_ok=False);b.space(root)
    spec=json.loads((parent/'confirmation_spec.json').read_text())
    native=json.loads((parent/'confirmation_evaluation.json').read_text())
    candidates=[]
    for name in ['candidate','thin_by_age','aggressive64']:
        e=native['e2e'][name]['selected_nop'];p=native['pmu'][name]['selected_nop']
        row=dict(name=name,speedup=e['inverse_rps']['speedup'],
            cpu_reduction=e['stack_cpu']['cost_reduction_pct'],p99_reduction=e['p99_ms']['cost_reduction_pct'],
            retired_l2_reduction=p['cache:sum:FE_L2']['cost_reduction_pct'])
        row['eligible']=row['cpu_reduction']>=0 and row['p99_reduction']>=-1 and row['retired_l2_reduction']>=20
        candidates.append(row)
    eligible=[r for r in candidates if r['eligible']]
    chosen=max(eligible,key=lambda r:(r['speedup'],r['cpu_reduction'])) if eligible else next(r for r in candidates if r['name']=='candidate')
    base=spec['arms']['base']['overrides'];selected=spec['arms'][chosen['name']]['overrides']
    reference=root/'reference/mongod'
    b.save(root/'protocol.json',dict(source_sha256=b.sha(__file__),native_candidates=candidates,native_choice=chosen,
        native_choice_rule='Largest throughput point estimate with nonnegative CPU reduction, p99 regression <=1%, retired L2 reduction >=20% versus NOP; otherwise retained retarget mechanism reference. This is selection, not independent confirmation.',
        training_seeds=[75001,75002],screen_seedbase=76001,timeline_seed=77001,
        hypothesis='Two review MongoDBs have more retired L2 misses and user CPU than the three modified native services. Use observed earlier executed NOP padding, without code growth or changed benchmark semantics.',
        controls='Fresh stack and equal workload age for every arm; all MongoDBs share one identical selected ELF; include original image and byte-identical copied ELF control.'))
    for phase,seed in [('train',75001),('heldout',75002)]:
        dest=root/'profiles'/phase;manifest=root/(phase+'_spec.json')
        b.save(manifest,dict(out=str(dest),reference=str(reference),overrides=base,seed=seed))
        h.platform(dest,['python3',Path(__file__).with_name('backend_prefetch.py'),'profile',manifest])
    manifest=root/'prepare_spec.json';b.save(manifest,dict(root=str(root),reference=str(reference)))
    b.run(['python3',Path(__file__).with_name('backend_prefetch.py'),'prepare',manifest],root/'prepare.log')
    prepared=json.loads((root/'prepared.json').read_text());patched=prepared['binary']
    arms=dict(
        base=dict(overrides=base),
        mongo_nop=dict(overrides=base,mongo_binary=str(reference),controls=['base']),
        mongo256=dict(overrides=base,mongo_binary=patched,controls=['base','mongo_nop']),
        native=dict(overrides=selected,mongo_binary=str(reference),controls=['base','mongo_nop']),
        combined=dict(overrides=selected,mongo_binary=patched,controls=['base','mongo_nop','native','mongo256']))
    screen=dict(out=str(root/'screen'),arms=arms,blocks=2,seedbase=76001,exploratory=True)
    manifest=root/'screen_spec.json';b.save(manifest,screen)
    b.run(['python3',Path(__file__).with_name('backend_study.py'),'campaign',manifest],root/'screen_driver.log')
    evaluate(root/'screen',root/'screen_evaluation.json')
    # A separate original-Mongo diagnostic tests its wake-age distribution.
    timeline=dict(out=str(root/'timeline'),overrides=base,reference=str(reference),seed=77001,periods=[1021,4093])
    manifest=root/'timeline_spec.json';b.save(manifest,timeline)
    h.platform(root/'timeline',['python3',Path(__file__).with_name('backend_prefetch.py'),'timeline',manifest])
    b.save(root/'complete.json',dict(clean_trials=10,profile_runs=2,wake_captures=4,prepared=prepared,
        evaluation=str(root/'screen_evaluation.json'),next='Inspect independent held-out coverage and clean whole-stack results before selecting a follow-up.'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);run(a.parent)
