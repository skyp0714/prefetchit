#!/usr/bin/env python3
"""Read-only restoration and retained-artifact audit after all measurements."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

import dense_build as b
from temporal_path_confirm import arm_paths


def read(path):
    return json.loads(path.read_text())


def audit(root):
    assert read(root / 'confirmation_and_diagnostics_complete.json')['valid']
    comparisons = []
    settings = {}
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
    assert all(row['matches_recorded_state'] for row in current)
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
    prepared = read(root / 'prepared_candidates.json')
    best = read(root / 'confirmation_selection.json')['selected']
    keep = set()
    binary_checks = []
    for name in set(('pathwide', best)):
        keep.update(arm_paths(prepared[name]['arm']))
        keep.update(arm_paths(prepared[name]['nop']))
        for row in prepared[name]['builds'].values():
            for key, digest in [('binary', 'sha256'), ('nop', 'nop_sha256')]:
                path = Path(row[key])
                value = b.sha(path)
                assert value == row[digest], path
                binary_checks.append(dict(path=str(path), bytes=path.stat().st_size, sha256=value))
    unexpected = []
    for path in (root / 'builds').rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            elf = stream.read(4) == b'\x7fELF'
        if elf and path.resolve() not in keep:
            unexpected.append(str(path))
    assert not unexpected, unexpected
    generated = [str(path) for path in root.rglob('*') if path.is_file() and not path.is_symlink()
                 and path.name in ('perf.data', 'events.txt', 'samples.txt')]
    assert not generated, generated
    endpoint_quality = []
    for campaign in ('screen1', 'screen2', 'screen3', 'confirmation'):
        path = root / campaign / 'rows.json'
        if not path.exists():
            continue
        for row in read(path):
            load = read(Path(row['output']) / 'load/load.json')
            item = dict(campaign=campaign, block=row['block'], arm=row['arm'],
                steady_errors=load['steady_errors'], mapping_preserved=load['mapping_preserved'],
                startup_and_warmup_errors=load['errors'], warmup_reconnects=len(load.get('warmup_reconnects', [])))
            assert item['steady_errors'] == 0 and item['mapping_preserved']
            endpoint_quality.append(item)
    result = dict(valid=True, epoch=time.time(), platform_comparisons=comparisons, current_sysfs=current,
        current_hwp_note='Each privileged wrapper checked exact HWP MSR restoration; this final unprivileged audit does not reread MSRs.',
        project=project, owned_resources=owned, modules=modules,
        retained_generated_elves=binary_checks,
        retention_reason='Keep the final policy, its same-layout NOP control, and the pathwide reference/NOP for the next iteration. Original inputs, packages and shared dependencies are untouched.',
        rejected_elf_residue=unexpected, raw_or_decoded_trace_residue=generated,
        endpoint_quality=endpoint_quality,
        free_bytes={str(path):shutil.disk_usage(path).free for path in (Path('/'),root)},
        source_sha256=b.sha(__file__))
    b.save(root / 'final_restoration_audit.json', result)
    print(json.dumps(dict(valid=True, platform_comparisons=len(comparisons), retained_generated_elves=len(binary_checks))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    audit(parser.parse_args().root)
