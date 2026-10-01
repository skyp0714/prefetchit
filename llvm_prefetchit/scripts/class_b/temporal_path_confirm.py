#!/usr/bin/env python3
"""Freeze independent confirmation after the completed exploratory screen."""
import argparse
import copy
import datetime
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import time

import dense_build as b


def select(rows, base, variants, expected_pairs=2):
    means = {}
    for name in [base, *variants]:
        observations = [row for row in rows if row['arm'] == name]
        assert len(observations) == expected_pairs and all(row['valid'] for row in observations)
        means[name] = dict(
            geometric_rps=math.exp(statistics.mean(math.log(row['achieved_rps']) for row in observations)),
            cpu=statistics.mean(row['metrics']['stack_cpu'] for row in observations),
            p99=statistics.mean(row['metrics']['p99_ms'] for row in observations))
    eligible = [name for name in variants
                if means[name]['cpu'] <= means[base]['cpu'] * 1.005
                and means[name]['p99'] <= means[base]['p99'] * 1.02]
    # The frozen screen rule compares the highest qualifying refinement with base.
    best = max([base, *eligible], key=lambda name: means[name]['geometric_rps'])
    return dict(selected=best, eligible=eligible, means=means,
                rule='Highest geometric RPS after all frozen blocks, subject to CPU <= base+0.5% and p99 <= base+2%; retain base if no refinement improves RPS.')


def arm_paths(arm):
    result = set(arm['overrides'].values()) | {arm['mongo_binary']}
    for libraries in arm.get('libraries', {}).values():
        result.update(libraries.values())
    return {Path(path).resolve() for path in result}


def cleanup(root, rejected, keep_arms, record_name='screen2_rejected_cleanup.json'):
    protected = set().union(*(arm_paths(arm) for arm in keep_arms))
    files = []
    for name in rejected:
        folder = root / 'builds' / name
        assert not folder.is_symlink()
        for path in sorted(folder.rglob('*')):
            if path.is_symlink() or not path.is_file() or path.resolve() in protected:
                continue
            with path.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    continue
            files.append(dict(path=str(path), bytes=path.stat().st_size, sha256=b.sha(path)))
    record = dict(reason='Completed exploratory screen; retain all measurements, source/patch/assembly/hash records and selected/reference/NOP artifacts. Remove only rejected generated ELFs.',
                  rejected=rejected, files=files, bytes_removed=sum(row['bytes'] for row in files),
                  free_before=shutil.disk_usage(root).free, complete=False)
    destination = root / record_name
    assert not destination.exists()
    b.save(destination, record)
    for row in files:
        Path(row['path']).unlink()
    record.update(complete=True, free_after=shutil.disk_usage(root).free)
    b.save(destination, record)


def run(root, name, command):
    b.space(root)
    print(json.dumps(dict(stage=name, epoch=time.time(), command=list(map(str, command)))), flush=True)
    b.run(command, root / (name + '.log'))


def main(root):
    import media_system_study as system
    assert json.loads((root / 'screen2/complete.json').read_text())['valid']
    ready = json.loads((root / 'iteration2_extended_prepared.json').read_text())
    rows = json.loads((root / 'screen2/rows.json').read_text())
    choice = select(rows, ready['base'], ready['variants'])
    best = choice['selected']
    prepared = json.loads((root / 'prepared_candidates.json').read_text())
    references = json.loads((root / 'arms.json').read_text())
    choice.update(epoch=time.time(), rejected=[name for name in ready['variants'] if name != best], screen_only=True)
    b.save(root / 'screen2_decision.json', choice)
    scripts = Path(__file__).parent
    if (root / 'it0_diagnostic_amendment.json').exists():
        it0 = ready['base'] + '_native_it0'
        tag = 'pmu_it0_extra'
        spec = root / (tag + '_spec.json')
        b.save(spec, dict(prepared[it0]['arm'], root=str(root), out=str(root / 'diagnostics' / tag),
                         arm=it0, suite='extra', seed=1002401,
                         purpose='Predeclared IT0 mechanism diagnosis before retiring any rejected IT0 ELF; L1/translation/late hint counts, not clean endpoint timing.'))
        run(root, tag, ['python3', scripts / 'temporal_path_final_pmu.py', 'platform_trial', spec])
        assert json.loads((root / 'diagnostics' / tag / 'result.json').read_text())['valid']
        run(root, 'it0_pmu_summary_driver', ['python3', scripts / 'temporal_path_metrics.py', root,
                                           '--pattern', 'pmu_it0_*', '--output', 'it0_pmu_summary.json'])
    cleanup(root, choice['rejected'], [*references.values(), prepared[ready['base']]['arm'],
                                     prepared[ready['base']]['nop'], prepared[best]['arm'], prepared[best]['nop']])
    # The earlier long-lived driver may have loaded before the L1 amendment.
    # Complete that declared control here, outside every clean timing trial.
    for group, services in [('native', list(system.NATIVE)), ('mongo', list(system.MONGO))]:
        tag = 'baseline2_l1_' + group
        if (root / 'profiles' / tag / 'complete.json').exists():
            assert json.loads((root / 'profiles' / tag / 'complete.json').read_text())['valid']
            continue
        spec = root / (tag + '_spec.json')
        b.save(spec, dict(references['original'], root=str(root), out=str(root / 'profiles' / tag),
                         services=services, kinds=['l1'], capture_s=8, seed=1001401,
                         phase='baseline2', arm='original', purpose='Declared L1I temporal control after screen2; no overlap with clean ROI.'))
        run(root, tag, ['python3', scripts / 'temporal_path_study.py', 'platform_capture', spec])
        assert json.loads((root / 'profiles' / tag / 'complete.json').read_text())['valid']
    if (root / 'iteration3_predeclared.json').exists():
        run(root, 'prepare_residual_repair', ['python3', scripts / 'temporal_path_repair.py', root])
        candidate = ready['base'] + '_repair'
        if json.loads((root / 'candidates' / candidate / 'model_decision.json').read_text())['eligible']:
            prepared = json.loads((root / 'prepared_candidates.json').read_text())
            smoke_spec = root / ('smoke_' + candidate + '_spec.json')
            b.save(smoke_spec, dict(prepared[candidate]['arm'], root=str(root), out=str(root / 'smokes' / candidate),
                                   candidate=candidate, seed=1001801))
            run(root, 'smoke_' + candidate, ['python3', scripts / 'temporal_path_campaign.py', 'platform_smoke', smoke_spec])
            assert json.loads((root / 'smokes' / candidate / 'result.json').read_text())['valid']
            screen_arms = {name: copy.deepcopy(prepared[name]['arm']) for name in (best, candidate)}
            for name, arm in screen_arms.items():
                arm['controls'] = [other for other in screen_arms if other != name]
            screen_spec = root / 'screen3_spec.json'
            b.save(screen_spec, dict(root=str(root), out=str(root / 'screen3'), arms=screen_arms, blocks=3,
                seedbase=1001901, order_seed=1001900, trial_script=str(scripts / 'temporal_path_trial.py'),
                predeclared=str(root / 'iteration3_predeclared.json'),
                scope='Residual repair versus the screen2 incumbent, three fresh exploratory blocks. No performance exclusions or retries. Independent confirmation follows.'))
            run(root, 'screen3_driver', ['python3', scripts / 'temporal_path_campaign.py', 'campaign', screen_spec])
            third = select(json.loads((root / 'screen3/rows.json').read_text()), best, [candidate], expected_pairs=3)
            third.update(epoch=time.time(), incumbent=best, screen_only=True)
            b.save(root / 'screen3_decision.json', third)
            rejected = [name for name in (best, candidate) if name != third['selected'] and name != ready['base']]
            best = third['selected']
            cleanup(root, rejected, [*references.values(), prepared[ready['base']]['arm'], prepared[ready['base']]['nop'],
                                     prepared[best]['arm'], prepared[best]['nop']], 'screen3_rejected_cleanup.json')
    arms = {name: copy.deepcopy(references[name]) for name in ('original', 'mongo')}
    arms[ready['base']] = copy.deepcopy(prepared[ready['base']]['arm'])
    arms[best] = copy.deepcopy(prepared[best]['arm'])
    arms[best + '_nop'] = copy.deepcopy(prepared[best]['nop'])
    for name, arm in arms.items():
        arm['controls'] = [control for control in arms if control != name]
    now = datetime.datetime.now(datetime.timezone.utc)
    # Predeclared time-only budget, independent of any endpoint effect size.
    blocks = 7 if now.hour < 6 or (now.hour == 6 and now.minute < 14) else 6
    if now.hour > 6 or (now.hour == 6 and now.minute >= 28):
        blocks = 5
    if best == ready['base']:
        blocks += 1
    final_choice = dict(epoch=time.time(), selected=best, arms=list(arms), blocks=blocks,
        screen_only=True, timing_budget='7 blocks before 06:14 UTC, 6 before 06:28, otherwise 5; one additional block when only four arms remain. Set before confirmation, without effect-size-dependent stopping.')
    b.save(root / 'confirmation_selection.json', final_choice)
    spec = root / 'confirmation_spec.json'
    b.save(spec, dict(root=str(root), out=str(root / 'confirmation'), arms=arms, blocks=blocks,
                     seedbase=1002101, order_seed=1002100,
                     trial_script=str(scripts / 'temporal_path_trial.py'),
                     selection_source=str(root / 'confirmation_selection.json'),
                     scope='Independent endpoint confirmation at accepted C4 / 80–90% utilization operating point; no PMU or trace collection in clean ROIs.',
                     promotion_rule='Report all contrasts with individual paired-log t95 intervals. Selected policy remains selected regardless of confirmation noise; do not select a different winner from these trials. No performance exclusions, retries or early stopping.',
                     background_audit=str(root / 'environment_amendment.json')))
    run(root, 'confirmation_driver', ['python3', scripts / 'temporal_path_campaign.py', 'campaign', spec])
    for name, suite in [('original', 'core'), (best, 'core'), (best, 'extra'), ('original', 'extra')]:
        tag = 'pmu_final_' + name + '_' + suite
        spec = root / (tag + '_spec.json')
        b.save(spec, dict(arms[name], root=str(root), out=str(root / 'diagnostics' / tag),
                         arm=name, suite=suite, seed=1002401))
        run(root, tag, ['python3', scripts / 'temporal_path_final_pmu.py', 'platform_trial', spec])
        assert json.loads((root / 'diagnostics' / tag / 'result.json').read_text())['valid']
    for kinds, suffix in [(['l2', 'lat128'], ''), (['l1'], '_l1')]:
        for group, services in [('native', list(system.NATIVE)), ('mongo', list(system.MONGO))]:
            tag = 'final' + suffix + '_' + group
            spec = root / (tag + '_spec.json')
            b.save(spec, dict(arms[best], root=str(root), out=str(root / 'profiles' / tag), services=services,
                             kinds=kinds, capture_s=8, seed=1001401, phase='final', arm=best,
                             purpose='Final selected policy versus repeated original baseline2, including residual L1I misses.'))
            run(root, tag, ['python3', scripts / 'temporal_path_study.py', 'platform_capture', spec])
            assert json.loads((root / 'profiles' / tag / 'complete.json').read_text())['valid']
    run(root, 'final_pmu_summary_driver', ['python3', scripts / 'temporal_path_metrics.py', root,
                                         '--pattern', 'pmu_final_*', '--output', 'final_pmu_summary.json'])
    run(root, 'final_temporal_report_driver', ['python3', scripts / 'temporal_path_report.py', root,
                                             '--plot', '--phases', 'baseline2', 'best1', 'final', '--prefix', 'matched_'])
    run(root, 'final_residual_driver', ['python3', scripts / 'temporal_path_residual.py', root, '--phase', 'final'])
    b.save(root / 'confirmation_and_diagnostics_complete.json', dict(valid=True, selected=best, epoch=time.time()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    main(parser.parse_args().root)
