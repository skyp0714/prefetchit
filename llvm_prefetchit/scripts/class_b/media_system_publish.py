#!/usr/bin/env python3
"""Publish compact joint-deployment measurements and exact reproduction records."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile

import dense_build as b


def publish(root):
    destination=b.REPO/'llvm_prefetchit/migration/evidence/class_b_media_system_20260930'
    destination.mkdir(parents=True,exist_ok=False)
    copies=['settings.json','prepared.json','screen_evaluation.json','system_report.json','report.md',
        'tests.json','scope_amendment.json','audit_amendment.json','smoke_restoration_audit.json',
        'source_manifest.json','source_snapshot.tar.gz','source_manifest_dso.json','source_snapshot_dso.tar.gz',
        'complete.json','decision.json','candidate_cleanup.json','boundary_summary.json','final_work_status.json']
    for name in copies:
        if (root/name).exists():shutil.copyfile(root/name,destination/name)
    for suffix in ['_driver.log','_libraries.log','_diagnostics.log','_diagnostics_continue.log','_boundaries.log']:
        path=root.with_name(root.name+suffix)
        if path.exists():shutil.copyfile(path,destination/path.name)
    files=[];records={}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():continue
        relative=path.relative_to(root)
        if path.name=='requests.json.gz' or path.name in copies:continue
        if path.suffix not in ['.json','.csv','.log','.txt','.py','.s','.ld','.asm','.md','.gz']:continue
        assert path.name not in ['perf.data','samples.txt']
        files.append(path);records[str(relative)]=dict(bytes=path.stat().st_size,sha256=b.sha(path))
    for path in [root.parent/'media_system_tests_20260930_sources.json',root.parent/'media_system_tests_20260930_cleanup.json',
                 root.parent/'media_system_dso_tests_20260930_sources.json',root.parent/'media_system_dso_tests_20260930_cleanup.json']:
        if path.exists():shutil.copyfile(path,destination/path.name)
    with tarfile.open(destination/'records.tar.gz','w:gz') as archive:
        for path in files:archive.add(path,arcname=str(path.relative_to(root)),recursive=False)
    b.save(destination/'records_manifest.json',records)
    with tarfile.open(destination/'records.tar.gz') as archive:
        names=archive.getnames();assert set(names)==set(records)
        import hashlib
        for name in names:
            data=archive.extractfile(name).read();assert len(data)==records[name]['bytes']
            assert hashlib.sha256(data).hexdigest()==records[name]['sha256']
    figures=b.REPO/'docs/figures';figures.mkdir(exist_ok=True)
    for suffix in ['png','svg']:
        shutil.copyfile(root/('system_e2e.'+suffix),figures/('class_b_media_system_20260930.'+suffix))
    text=(root/'report.md').read_text()
    text += '\n![전체 요청 성능](figures/class_b_media_system_20260930.png)\n\n'
    text += '자료: [전체 성능 원자료](../llvm_prefetchit/migration/evidence/class_b_media_system_20260930/screen_evaluation.json), '
    text += '[서비스·커널 PMU](../llvm_prefetchit/migration/evidence/class_b_media_system_20260930/system_report.json), '
    text += '[재현 기록 manifest](../llvm_prefetchit/migration/evidence/class_b_media_system_20260930/records_manifest.json).\n'
    (b.REPO/'docs/class_b_media_system_20260930.md').write_text(text)
    manifest={str(path.relative_to(destination)):dict(bytes=path.stat().st_size,sha256=b.sha(path))
        for path in sorted(destination.rglob('*')) if path.is_file()}
    b.save(destination/'manifest.json',dict(files=manifest,records=len(records),source=str(root),
        verified_archive=True,exclusions='No ELF/object/build tree, raw perf recording, decoded trace copies, full HTTP request list or original input datasets.'))
    print(json.dumps(dict(evidence=str(destination),compact_files=len(manifest),archived_records=len(records))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();publish(a.root)
