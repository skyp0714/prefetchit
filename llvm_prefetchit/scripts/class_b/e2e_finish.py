#!/usr/bin/env python3
"""Finish the frozen E2E placement screen, timed-wave screen, and confirmation."""
import argparse
import json
from pathlib import Path

import fullset as h
from e2e_lbr import campaign, remove_generated
from kernel_emission_study import run_sequence


def finish(root):
    assert (root/'screen_media/complete.json').exists()
    source_paths = [Path(__file__), Path(__file__).with_name('e2e_lbr.py'),
        Path(__file__).with_name('wave_plan.py'), Path(__file__).with_name('wake_miss_timeline.py'),
        Path(__file__).with_name('capture_miss_timeline.py'), Path(h.__file__),
        Path(__file__).with_name('kernel_emission_study.py'),
        h.REPO/'llvm_prefetchit/tools/lbr_padding_prefetch.py',
        h.REPO/'llvm_prefetchit/tools/make_nop_control_binary.py']
    source_paths += list((h.REPO/'llvm_prefetchit/kernel/wake_prefetch').glob('*.h'))
    source_paths += [h.REPO/'llvm_prefetchit/kernel/wake_prefetch'/name for name in
                     ('wake_prefetch.c','control.py','smoke.py','Makefile')]
    for path in source_paths:
        dest = root/'sources'/path.relative_to(h.REPO); dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(path.read_bytes())
    h.c.save(root/'source_hashes.json',{str(p):h.c.sha(p) for p in source_paths})
    summary = json.loads((root/'screen_media/summary.json').read_text())
    arms = json.loads((root/'placements_media/arms.json').read_text())
    eligible = [name for name in arms if name != 'base' and
                summary.get(name, {}).get('base', {}).get('mean_ms', {}).get('pairs') == 2]
    assert eligible
    winner = max(eligible, key=lambda name:summary[name]['base']['mean_ms']['cost_reduction_pct'])
    h.c.save(root/'selection.json', dict(winner=winner, screen=summary,
        rule='Largest paired mean-latency reduction among the three frozen placement variants, regardless of sign; seven new seed pairs required',
        promotion='At least one of mean/p99 has a positive individual 95% lower bound; neither point estimate may regress more than 2%. Report both intervals and no multiplicity correction.'))
    for name, arm in arms.items():
        if name in ('base', winner): continue
        cleanup_record = root/'placements_media'/name/'rejected_cleanup.json'
        if cleanup_record.exists():
            assert json.loads(cleanup_record.read_text())['status'] == 'complete'
            assert all(not Path(p).exists() for p in arm['overrides'].values())
            continue
        paths = [Path(p) for p in arm['overrides'].values()]
        assert all(p.is_relative_to(root/'placements_media'/name) for p in paths)
        remove_generated(paths, cleanup_record,
            'Superseded by frozen mean-latency screen winner '+winner+'; complete timings, hashes, patches and heldout evidence retained')
    # Small parser/ABI tests run between timing stages, never concurrently.
    unit_log = root/'wave_unit.log'
    if unit_log.exists(): unit_log=root/'wave_unit_retry1.log'
    h.c.run(['taskset','-c','84-85',h.REPO/'profiling/.venv/bin/python','-m','pytest','-q',
             h.REPO/'llvm_prefetchit/tests/test_wave_plan.py',
             h.REPO/'llvm_prefetchit/tests/test_wake_miss_timeline.py'],unit_log)
    capture_spec = root/'specs/wave_training.json'
    capture = json.loads(capture_spec.read_text())
    h.platform(Path(capture['out']), ['python3',Path(__file__).with_name('wave_plan.py'),capture_spec])
    variants = json.loads((root/'wave_training/variants.json').read_text())
    kernel_arms = {}; order = []
    for i, (name, variant) in enumerate(variants.items()):
        off, after = f'off{i}', f'off{i+1}'
        kernel_arms[off] = dict(mode='off')
        kernel_arms[name+'_nop'] = dict(mode='nop', plan=variant['plan'], options=variant['options'])
        kernel_arms[name] = dict(mode='t1', plan=variant['plan'], options=variant['options'], controls=[off,name+'_nop'])
        kernel_arms[name+'_burst'] = dict(mode='t1', plan=variant['plan'], options={}, controls=[off])
        order.append(off)
        local = [name+'_nop', name, name+'_burst']
        if i % 2: local.reverse()
        order.extend(local)
    kernel_arms['off3'] = dict(mode='off'); order.append('off3')
    spec = dict(out=str(root/'kernel_screen'),family='media',service='movie',pool=8,rate=1000,
        seed=32501,arms=kernel_arms,order=order,roi_s=30,settle_s=10,pmu_s=0,
        purpose='Exploratory local-off-bracketed request-latency comparison; no confidence or promotion claim')
    h.c.save(root/'specs/kernel_screen.json',spec)
    rows = run_sequence(spec)
    assert all(row['valid'] for row in rows), 'retain invalid screen for diagnosis'
    h.c.save(root/'kernel_screen_summary.json', dict(rows=rows,
        rule='Kernel screen is exploratory. No automatic promotion from one temporal sequence; each periodic candidate also has identical-address burst and exact-layout timer NOP controls.'))
    confirmation = dict(out=str(root/'confirmation_media'),family='media',pool=8,rate=1000,
        seedbase=33001,blocks=7,arms={'base':{}, winner:arms[winner]})
    h.c.save(root/'specs/confirmation_media.json', confirmation)
    campaign(confirmation)
    final = json.loads((root/'confirmation_media/summary.json').read_text())[winner]['base']
    metrics = [final[key] for key in ('mean_ms','p99_ms')]
    promoted = any(m['ci95_pct'][0] > 0 for m in metrics) and all(m['cost_reduction_pct'] >= -2 for m in metrics)
    h.c.save(root/'placement_decision.json', dict(winner=winner, promoted=promoted, metrics=final,
        deployment='Experimental retained artifact only; default service baselines are unchanged',
        interpretation='Individual confidence intervals, two endpoints without multiplicity correction; fixed-load RPS is not maximum throughput'))
    if not promoted:
        remove_generated([Path(p) for p in arms[winner]['overrides'].values()],
            root/'placements_media'/winner/'rejected_cleanup.json',
            'Independent seven-pair confirmation did not pass frozen E2E promotion rule; measurements and patch records retained')
    h.c.save(root/'e2e_complete.json',dict(winner=winner,promoted=promoted))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('root',type=Path)
    finish(parser.parse_args().root)
