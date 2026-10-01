#!/usr/bin/env python3
"""Publish compact records, verified archives and final temporal figures."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import dense_build as b


TAG = 'class_b_temporal_20261001'
EXCLUDED_NAMES = {'perf.data', 'events.txt', 'samples.txt', 'requests.json.gz',
                  'observations.json.gz', 'request_traces.json.gz', 'request_path_traces.json',
                  'background_environment.json'}
LOCAL_DERIVED_NAMES = {'locations.json', 'observed_callgraph.json'}


def publish(root):
    assert json.loads((root / 'confirmation_and_diagnostics_complete.json').read_text())['valid']
    assert (root / 'report.md').is_file()
    destination = b.REPO / 'llvm_prefetchit/migration/evidence' / TAG
    destination.mkdir(parents=True, exist_ok=False)
    direct = ['protocol.json', 'confirmation_selection.json', 'screen1_decision.json', 'screen2_decision.json',
              'screen3_decision.json', 'iteration3_predeclared.json', 'environment_amendment.json',
              'final_restoration_audit.json', 'final_work_status.json', 'report.md']
    for name in direct:
        if (root / name).is_file():
            shutil.copyfile(root / name, destination / name)
    for source, target in [('analysis/final_summary.json', 'final_summary.json'),
                           ('analysis/final_pmu_summary.json', 'final_pmu_summary.json'),
                           ('confirmation/evaluation.json', 'confirmation.json')]:
        shutil.copyfile(root / source, destination / target)
    files, omitted, records = [], [], {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if path.name.startswith(('external_cpu_', 'background_cpu_watch')) or path.name == 'background_environment.json':
            continue  # The aggregate environment amendment is published instead.
        if relative.startswith('plans/') or path.name in LOCAL_DERIVED_NAMES or (
                path.name.endswith('_selection.json') and path.stat().st_size > 2**20):
            omitted.append(dict(path=relative, bytes=path.stat().st_size, sha256=b.sha(path),
                                reason='Derived planning/location detail remains local; decisions, patch records, aggregate results and source hashes are published.'))
            continue
        if path.name in EXCLUDED_NAMES:
            # Keep compact training observations locally for future work.
            if path.name == 'observations.json.gz':
                omitted.append(dict(path=relative, bytes=path.stat().st_size, sha256=b.sha(path),
                                    reason='Reusable compact branch observations retained locally; aggregate evidence published.'))
            continue
        if path.suffix not in ('.json', '.csv', '.log', '.txt', '.py', '.s', '.ld', '.asm', '.md'):
            continue
        with path.open('rb') as stream:
            assert stream.read(4) != b'\x7fELF', path
        files.append(path)
        records[relative] = dict(bytes=path.stat().st_size, sha256=b.sha(path))
    batches, current, size = [], [], 0
    for path in files:
        length = path.stat().st_size
        if current and size + length > 64 * 2**20:
            batches.append(current)
            current, size = [], 0
        current.append(path)
        size += length
    if current:
        batches.append(current)
    archives = []
    for index, batch in enumerate(batches):
        name = f'records_{index:02d}.tar.gz'
        archive_path = destination / name
        with tarfile.open(archive_path, 'w:gz') as archive:
            for path in batch:
                relative = str(path.relative_to(root))
                archive.add(path, arcname=relative, recursive=False)
                records[relative]['archive'] = name
        with tarfile.open(archive_path) as archive:
            assert set(archive.getnames()) == {str(path.relative_to(root)) for path in batch}
            for member in archive:
                value = archive.extractfile(member).read()
                assert len(value) == records[member.name]['bytes']
                assert hashlib.sha256(value).hexdigest() == records[member.name]['sha256']
        assert archive_path.stat().st_size < 90 * 2**20, 'Split before publishing a large Git object'
        archives.append(name)
    b.save(destination / 'records_manifest.json', records)
    b.save(destination / 'local_derived_records.json', dict(root=str(root), files=omitted))
    figures = b.REPO / 'docs/figures'
    figures.mkdir(exist_ok=True)
    figure_manifest = {}
    for path in sorted((root / 'analysis').glob('*')):
        if path.suffix not in ('.png', '.svg') or not path.name.startswith(('final_', 'matched_')):
            continue
        target = figures / (TAG + '_' + path.name)
        shutil.copyfile(path, target)
        assert b.sha(path) == b.sha(target)
        figure_manifest[str(target.relative_to(b.REPO))] = dict(bytes=target.stat().st_size, sha256=b.sha(target))
    shutil.copyfile(root / 'report.md', b.REPO / 'docs' / (TAG + '.md'))
    manifest = {str(path.relative_to(destination)): dict(bytes=path.stat().st_size, sha256=b.sha(path))
                for path in sorted(destination.rglob('*')) if path.is_file()}
    b.save(destination / 'manifest.json', dict(files=manifest, source=str(root), archives=archives,
        figures=figure_manifest, publisher_source_sha256=b.sha(__file__),
        archived_records=len(records), verified_archive=True,
        exclusions='No ELF/object/build tree, generated plan/callgraph/location index, raw perf recording, decoded trace copies, full HTTP request list, original datasets, or identifying details of unrelated host processes. Reusable compact observations and derived planning records remain local with hashes.'))
    print(json.dumps(dict(evidence=str(destination), archives=archives, compact_files=len(manifest),
                          archived_records=len(records), bytes=sum(row['bytes'] for row in manifest.values()))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    publish(parser.parse_args().root)
