#!/usr/bin/env python3
"""Archive compact completed results; never archive benchmark binaries/raw PT."""
import json
from pathlib import Path
import tarfile

import social_headroom as h


def main():
    assert (h.OUT/'confirmation_complete.json').exists()
    h.c.space()
    evidence=h.REPO/'llvm_prefetchit/migration/evidence/class_b_headroom_20260926'
    archive=evidence/'campaign_results.tar.gz'
    assert not archive.exists()
    files={}
    for root,prefix in [(h.OUT,'campaign'),(h.TRACE,'trace_summary')]:
        for p in root.rglob('*'):
            if not p.is_file() or p.is_symlink():continue
            if p.suffix not in {'.json','.csv','.log','.txt','.tsv','.err','.yaml','.yml','.conf','.sh','.c','.h','.py'}:continue
            if p.name in {'branches.txt','syscall_context.txt','misses.txt'} or 'symfs' in p.parts:continue
            assert p.stat().st_size<5*2**20,(p,'unexpected bulk text; extract compact results first')
            files[p]=prefix+'/'+str(p.relative_to(root))
    builds=h.c.S/'social_build'
    for p in builds.glob('usertimeline/headroom_*'):
        paths=p.rglob('*') if p.is_dir() else [p]
        for f in paths:
            if f.is_file() and not f.is_symlink() and f.suffix in {'.json','.log','.txt'}:
                files[f]='builds/'+str(f.relative_to(builds))
    for name in ('source.json','cmake_flags.json','build_service.sh'):
        p=builds/name
        if p.is_file():files[p]='builds/'+name
    checks=[]
    for before in h.OUT.rglob('*_before.json'):
        if before.name not in {'platform_before.json','hwp_before.json'}:continue
        after=before.with_name(before.name.replace('_before','_restored'))
        checks.append(dict(before=str(before),restored=after.exists() and
                           json.loads(before.read_text())==json.loads(after.read_text())))
    assert checks and all(x['restored'] for x in checks),'unrestored platform state'
    manifest=[]
    with tarfile.open(archive,'w:gz') as tf:
        for p,name in sorted(files.items(),key=lambda x:x[1]):
            manifest.append(dict(path=str(p),archive_path=name,bytes=p.stat().st_size,sha256=h.c.sha(p)))
            tf.add(p,arcname=name,recursive=False)
    h.c.save(evidence/'campaign_archive_manifest.json',dict(files=manifest,
        archive_sha256=h.c.sha(archive),archive_bytes=archive.stat().st_size,
        excludes='Executables, objects, build directories, original inputs, raw/decoded traces, mapped ELF copies'))
    h.c.save(evidence/'final_platform_restore.json',dict(all_restored=True,checks=len(checks),details=checks))
    for name in ('confirmation_selection.json','confirmation_summary.json','confirmation_rows.json',
                 'confirmation_complete.json','screen_candidate_cleanup.json','confirmation_rejection_cleanup.json',
                 'cache_probe_build_cleanup.json'):
        p=h.OUT/name
        if p.exists():(evidence/name).write_bytes(p.read_bytes())
    probe=h.OUT/'kernel_cache_probe/result.json'
    if probe.exists():(evidence/'kernel_cache_probe.json').write_bytes(probe.read_bytes())
    print(json.dumps(dict(files=len(files),archive_bytes=archive.stat().st_size,restoration_checks=len(checks))),flush=True)


if __name__=='__main__':main()
