#!/usr/bin/env python3
"""Publish compact RPC measurements and source/patch records, never generated ELFs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

import dense_build as b
from rpc_future_finalize import TAG


def publish(root):
    assert json.loads((root / 'final_work_status.json').read_text())['complete']
    assert json.loads((root / 'final_restoration_audit.json').read_text())['valid']
    destination = b.REPO / 'llvm_prefetchit/migration/evidence' / TAG
    destination.mkdir(parents=True, exist_ok=False)
    direct = ['protocol.json', 'final_decision.json', 'final_restoration_audit.json', 'final_work_status.json',
              'rpc_stable_cleanup.json', 'initial_rpc_cleanup.json', 'initial_rpc_decisions.json',
              'stable_policy_spec.json', 'stable_preservation_summary.json', 'rpc_inventory.json',
              'policy_size_summary.json', 'tests.json', 'tests_nested.json', 'smoke_summary.json',
              'cpu_numa_topology.json', 'dtlb_event_definitions.txt', 'diagnostic_validity_retry.json']
    for name in direct:
        shutil.copyfile(root / name, destination / name)
    for name in ('report.json', 'pmu_contrasts.json', 'rpc_target_footprint.json', 'baseline_variation.json'):
        shutil.copyfile(root / 'analysis' / name, destination / name)
    shutil.copyfile(root / 'confirmation/evaluation.json', destination / 'confirmation.json')
    files, records, omitted = [], {}, []
    excluded = {'perf.data', 'events.txt', 'samples.txt', 'requests.json.gz', 'observations.json.gz',
                'background_environment.json', 'request_traces.json.gz', 'work_state.json', 'progress.py'}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if path.name in excluded or path.name.startswith(('external_cpu_', 'background_cpu_watch')):
            continue
        if relative.startswith('plans/'):
            omitted.append(dict(path=relative, bytes=path.stat().st_size, sha256=b.sha(path),
                reason='Generated plan stays local; emitted assembly, patch records, hashes and policy source are published.'))
            continue
        if path.suffix not in ('.json', '.csv', '.log', '.txt', '.py', '.s', '.ld', '.asm'):
            continue
        with path.open('rb') as stream:
            assert stream.read(4) != b'\x7fELF', path
        files.append(path)
        records[relative] = dict(bytes=path.stat().st_size, sha256=b.sha(path))
    batches, current, size = [], [], 0
    for path in files:
        length = path.stat().st_size
        if current and size + length > 48 * 2**20:
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
        assert archive_path.stat().st_size < 90 * 2**20
        archives.append(name)
    b.save(destination / 'records_manifest.json', records)
    b.save(destination / 'local_derived_records.json', dict(root=str(root), files=omitted))
    figures = {}
    for extension in ('png', 'svg'):
        source = root / 'analysis' / ('endpoint_effects.' + extension)
        target = b.REPO / 'docs/figures' / (TAG + '_endpoint_effects.' + extension)
        shutil.copyfile(source, target)
        assert b.sha(source) == b.sha(target)
        figures[str(target.relative_to(b.REPO))] = dict(bytes=target.stat().st_size, sha256=b.sha(target))
    report = b.REPO / 'docs' / (TAG + '.md')
    shutil.copyfile(root / 'report.md', report)
    manifest = {str(path.relative_to(destination)): dict(bytes=path.stat().st_size, sha256=b.sha(path))
                for path in sorted(destination.rglob('*')) if path.is_file()}
    b.save(destination / 'manifest.json', dict(files=manifest, source=str(root), archives=archives,
        figures=figures, report=dict(path=str(report.relative_to(b.REPO)), sha256=b.sha(report)),
        publisher_source_sha256=b.sha(__file__), archived_records=len(records), verified_archive=True,
        exclusions='No executable/object/build bulk, raw or decoded trace copies, datasets, full request list, '
                   'or identifying details of unrelated host processes. Generated plans stay local with hashes.'))
    print(json.dumps(dict(evidence=str(destination), archives=archives, archived_records=len(records),
                          published_bytes=sum(row['bytes'] for row in manifest.values()))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    publish(parser.parse_args().root)
