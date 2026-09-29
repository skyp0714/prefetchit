#!/usr/bin/env python3
"""Compare greater miss coverage against frequency-aware, cheaper emission."""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b
import fullset as h
from callpath_campaign import smoke
from mechanism_report import evaluate


def run(parent,blocks=4):
    assert blocks>=3
    source=parent/'callpath';frequency=parent/'call_frequency/capture/frequency_summary.json'
    assert (source/'complete.json').exists() and (parent/'call_frequency/complete.json').exists()
    assert json.loads(frequency.read_text())['valid']
    root=parent/'callpath_coverage75';root.mkdir(exist_ok=False);b.space(root)
    base=json.loads((parent/'confirmation_spec.json').read_text())['arms']['base']['overrides']
    first=json.loads((source/'prepared.json').read_text())
    services=json.loads((source/'protocol.json').read_text())['training_services']
    b.save(root/'protocol.json',dict(source_sha256=b.sha(__file__),screen_seedbase=81001,blocks=blocks,
        training_source=str(source),frequency_source=str(frequency),frequency_sha256=b.sha(frequency),
        hypothesis='The first policy covers about half of heldout miss paths, eliminates about a third of measured Mongo retired L2 events, and emits many hints. Target 75% train coverage and price sites by independent retired-call frequency.',
        policies='Both new policies use 64..8192 retired-age proxy, <=1024 sites/4096 hints, <=4/site, gain>=8, 75% coverage goal. Plain marginal cover versus marginal misses per regularized call-rate cost. Heldout is not used to choose placements.',
        controls='Original, prior call256 T1, and a separate same-layout NOP twin for each new policy. Fresh Media C4, fixed initial data, 50s warmup then 60s clean ROI. PMU follows clean E2E.',
        residual_policy='Frequency-aware candidate, frozen before performance outcomes; original heldout comparison is diagnostic only.'))
    candidates={}
    for name in ['wide75','cost75']:
        out=root/'builds'/name
        cmd=['python3',Path(__file__).with_name('callpath_refine.py'),source,out,'--goal','.75','--build']
        if name=='cost75':cmd+=['--frequency',frequency]
        b.run(cmd,root/(name+'_build.log'))
        candidates[name]=json.loads((out/'prepared.json').read_text())
    prepared=dict(reference=first['reference'],candidates=candidates,residual_candidate='cost75',
        baseline_root=str(source),density_rule='Same 75% training-cover goal and fixed budgets; compare coverage-first and dynamic-emission-cost priorities.')
    b.save(root/'prepared.json',prepared);smoke(root,prepared)
    from privilege_frontend import DECODE_EVENTS
    from dense_causes import counters
    events={'decode':DECODE_EVENTS}
    # Same frontend groups as the first screen; preflight before any workload.
    for name,event in events.items():
        stem=root/('preflight_'+name)
        b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',event,'-a','-C','84','--','sleep','.2'],Path(str(stem)+'.log'))
        assert counters(Path(str(stem)+'.csv'))['fully_scheduled']
    primary=first['candidates']['call256']
    assert b.sha(primary['binary'])==json.loads(Path(primary['binary']+'.json').read_text())['sha256']
    arms=dict(original=dict(overrides=base,mongo_binary=first['reference']),
        call256=dict(overrides=base,mongo_binary=primary['binary'],controls=['original']))
    for name,variant in candidates.items():
        arms[name+'_nop']=dict(overrides=base,mongo_binary=variant['nop'],controls=['original'])
        arms[name]=dict(overrides=base,mongo_binary=variant['binary'],controls=['original',name+'_nop','call256'])
        if name=='cost75':arms[name]['controls'].append('wide75')
    for settings in arms.values():settings['extra_events']=events
    manifest=root/'screen_spec.json'
    b.save(manifest,dict(out=str(root/'screen'),arms=arms,blocks=blocks,seedbase=81001,exploratory=False))
    # The original call256 NOP is no longer used by this concrete campaign.
    from e2e_lbr import remove_generated
    nop=Path(primary['nop']);patch=json.loads(Path(primary['binary']+'.json').read_text())
    if nop.exists():
        assert b.sha(nop)==patch['nop_sha256']
        remove_generated([nop],source/'retired_nop.json',
            'First call-path screen/residual complete; retain original and call256 T1 as the next screen references. New policies have their own NOP twins; old NOP results, bytes/hash/patch records remain.')
    b.run(['python3',Path(__file__).with_name('backend_study.py'),'campaign',manifest],root/'screen_driver.log')
    evaluate(root/'screen',root/'screen_evaluation.json')
    candidate=candidates['cost75'];manifest=root/'residual_capture_spec.json'
    b.save(manifest,dict(out=str(root/'residual'),reference=candidate['binary'],mongo_binary=candidate['binary'],
        overrides=base,seed=82001,services=services))
    h.platform(root/'residual',['python3',Path(__file__).with_name('backend_prefetch.py'),'profile',manifest])
    manifest=root/'residual_analysis_spec.json'
    b.save(manifest,dict(root=str(root),binary=candidate['binary'],services=services,baseline_root=str(source)))
    b.run(['python3',Path(__file__).with_name('callpath_prefetch.py'),manifest,'--residual'],root/'residual_analysis.log')
    b.save(root/'complete.json',dict(clean_trials=blocks*len(arms),prepared=prepared,
        next='Report E2E and its uncertainty, compare actual hint issue and same-layout NOP overhead, then retire unused binaries and choose a cause-based next step.'))
    b.run(['python3',Path(__file__).with_name('backend_summary.py'),root,'--plot'],root/'summary.log')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);p.add_argument('--blocks',type=int,default=4);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);run(a.parent,a.blocks)
