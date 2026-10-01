#!/usr/bin/env python3
"""Retire measured RPC ELFs, then audit retained controls and restored resources."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

import dense_build as b
from e2e_lbr import remove_generated


def read(path):
    return json.loads(path.read_text())


def finish(root):
    assert read(root / 'diagnostics/complete.json')['trials'] == 8
    assert read(root / 'confirmation/complete.json')['trials'] == 25
    assert (root / 'analysis/pmu_contrasts.json').is_file()
    prepared = read(root / 'prepared_candidates.json')
    report = read(root / 'analysis/report.json')
    b.save(root / 'final_decision.json', dict(selected='full_dso',
        selected_reference=read(root / 'confirmation_spec.json')['arms']['full_dso'],
        retained_new_reference='no_dso',
        rejected='rpc_stable',
        reason='Independent five-block confirmation establishes no incremental RPC gain; '
               'RPC/full throughput is lower, and RPC/exact-NOP CPU cost is higher. '
               'Keep the existing full policy and strict no-DSO ablation reference.',
        comparisons=report['confirmation']['comparisons'],
        diagnosis_records=['analysis/pmu_contrasts.json', 'analysis/rpc_target_footprint.json'],
        limitations='No claim that DSO removal significantly harms throughput: that interval crosses zero. '
                    'Initial live/type/trace comparisons include displaced decoder hints/layout effects.'))
    cleanup = root / 'rpc_stable_cleanup.json'
    if not cleanup.exists():
        paths = []
        for row in prepared['rpc_stable']['builds'].values():
            for key, digest in [('binary', 'sha256'), ('nop', 'nop_sha256')]:
                path = Path(row[key])
                assert path.parent.parent == root / 'builds/rpc_stable'
                assert not path.is_symlink() and b.sha(path) == row[digest]
                assert path.with_suffix(path.suffix + '.json').is_file() or key == 'nop'
                paths.append(path)
        assert len(paths) == 18
        remove_generated(paths, cleanup,
            'Completed confirmation and reverse-order PMU; RPC policy is not selected. '
            'Preserve all measurements, plans, assembly, patch maps, source versions and hashes.')
    assert read(cleanup)['status'] == 'complete'
    comparisons, settings = [], {}
    for name in ('platform_before.json', 'hwp_before.json'):
        for before in sorted(root.rglob(name)):
            after = before.with_name(name.replace('_before', '_restored'))
            valid = after.exists() and read(before) == read(after)
            comparisons.append(dict(before=str(before.relative_to(root)), restored=valid))
            assert valid, before
            if name == 'platform_before.json':
                for path, value in read(before).items():
                    settings.setdefault(path, set()).add(value)
    current = []
    for path, values in sorted(settings.items()):
        value = Path(path).read_text().strip()
        current.append(dict(path=path, expected_observed_before=sorted(values), actual=value,
                            matches_recorded_state=value in values))
    assert current and all(row['matches_recorded_state'] for row in current)
    project = 'codex-b-fullset-media'
    owned = {}
    for kind, command in [('containers', ['docker', 'ps', '-aq']),
                          ('networks', ['docker', 'network', 'ls', '-q']),
                          ('volumes', ['docker', 'volume', 'ls', '-q'])]:
        result = subprocess.run(command + ['--filter', 'label=com.docker.compose.project=' + project],
                                capture_output=True, text=True, check=True)
        owned[kind] = result.stdout.splitlines()
    assert not any(owned.values()), owned
    modules = {name: Path('/sys/module', name).exists() for name in ('wake_prefetch', 'prefetchit')}
    assert not any(modules.values())
    keep, binaries = set(), []
    for row in prepared['no_dso']['builds'].values():
        path = Path(row['binary'])
        assert not path.is_symlink() and b.sha(path) == row['sha256']
        keep.add(path)
        binaries.append(dict(path=str(path), bytes=path.stat().st_size, sha256=row['sha256']))
    unexpected = []
    for path in (root / 'builds').rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            elf = stream.read(4) == b'\x7fELF'
        if elf and path not in keep:
            unexpected.append(str(path))
    assert not unexpected, unexpected
    smoke = []
    for name in ('no_dso', 'rpc_live', 'rpc_type', 'rpc_trace', 'rpc_stable', 'rpc_stable_nop'):
        row = read(root / 'smoke' / name / 'result.json')
        assert row['valid'] and row['original_dsos_verified'] and row['load']['steady_errors'] == 0
        smoke.append(dict(arm=name, valid=True, original_dsos_verified=True,
            completed=row['load']['completed'], steady_errors=row['load']['steady_errors'],
            startup_and_warmup_errors=row['load']['errors']))
    b.save(root / 'smoke_summary.json', smoke)
    quality = []
    for phase in ('screen', 'confirmation'):
        for row in read(root / phase / 'rows.json'):
            load = read(Path(row['output']) / 'load/load.json')
            assert row['valid'] and load['steady_errors'] == 0 and load['mapping_preserved']
            quality.append(dict(phase=phase, block=row['block'], arm=row['arm'],
                steady_errors=load['steady_errors'], mapping_preserved=load['mapping_preserved'],
                startup_and_warmup_errors=load['errors'], warmup_reconnects=len(load.get('warmup_reconnects', []))))
    diagnostic_quality = []
    for path in sorted((root / 'diagnostics').glob('*/result.json')):
        row = read(path)
        assert row['valid']
        windows = [w for services in row['pmu_extra'].values() for w in services.values()]
        windows += [w for modes in row['pool_pmu'].values() for w in modes.values()]
        assert all(w['fully_scheduled'] for w in windows)
        diagnostic_quality.append(dict(trial=path.parent.name, valid=True, fully_scheduled_windows=len(windows)))
    result = dict(valid=True, epoch=time.time(), platform_comparisons=comparisons, current_sysfs=current,
        current_hwp_note='Each privileged wrapper checked exact MSR restoration; final audit uses those records.',
        project=project, owned_resources=owned, modules=modules, endpoint_quality=quality,
        diagnostic_quality=diagnostic_quality, smoke_quality=smoke, retained_generated_elves=binaries,
        retention_reason='Strict no-DSO ablation remains useful. Existing winner and original controls remain in their previous locations.',
        rejected_elf_residue=unexpected, rpc_cleanup=read(cleanup),
        free_bytes={str(path): shutil.disk_usage(path).free for path in (Path('/'), root)},
        source_sha256=b.sha(__file__))
    b.save(root / 'final_restoration_audit.json', result)
    b.save(root / 'final_work_status.json', dict(complete=True, clean_trials=43, diagnostics=8,
        invalid_diagnostic_attempts=1, diagnostic_retry_record='diagnostic_validity_retry.json',
        smoke_trials=6, native_tests=28, selected='full_dso', retained_new_control='no_dso',
        no_nas_io=True, no_kernel_changes=True, final_restoration_valid=True))
    print(json.dumps(dict(valid=True, restored_records=len(comparisons), clean_trials=len(quality),
        diagnostic_trials=len(diagnostic_quality), retained_elves=len(binaries),
        rpc_bytes_removed=read(cleanup)['bytes_removed'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    finish(parser.parse_args().root)
