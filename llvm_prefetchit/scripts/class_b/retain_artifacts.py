#!/usr/bin/env python3
"""Record hashes, sizes and reasons before deleting explicit generated files.

Never traverses a symlink. Only this campaign's generated trees are accepted.
The caller must first extract measurements and decide the artifacts are unused.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOTS = [Path('/storage/prefetchit/class_b_headroom_20260926'),
         Path('/trace/prefetchit/class_b_headroom_20260926')]
BUILD = Path('/storage/prefetchit/class_b_extension_20260926/social_build/usertimeline')


def free():
    return {str(p):shutil.disk_usage(p).free for p in (Path('/'),Path('/storage'),Path('/trace'))}


def cleanup(paths, record, reason):
    assert reason and not record.exists()
    entries=[]
    for raw in paths:
        p=Path(raw).absolute()
        assert not p.is_symlink() and p.is_file(),p
        assert p.resolve()==p,'symlink parent is forbidden'
        allowed=any(p.is_relative_to(root) for root in ROOTS)
        # Service candidate binaries only; original benchmark sources/inputs
        # and base/wake16 reference executables are never cleanup candidates.
        allowed |= p.parent.parent==BUILD and p.parent.name.startswith('headroom_') and p.name in {
            'UserTimelineService','UserTimelineService.nop'}
        assert allowed,p
        with p.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        entries.append(dict(path=str(p),bytes=p.stat().st_size,sha256=digest))
    result=dict(reason=reason,files=entries,bytes_removed=0,free_before=free(),status='prepared')
    record.parent.mkdir(parents=True,exist_ok=True)
    record.write_text(json.dumps(result,indent=2)+'\n')
    for item in entries:
        p=Path(item['path'])
        assert not p.is_symlink() and p.stat().st_size==item['bytes']
        p.unlink()
        result['bytes_removed']+=item['bytes']
    result.update(status='complete',free_after=free())
    record.write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path,help='JSON with files, record, reason')
    a=p.parse_args()
    spec=json.loads(a.manifest.read_text())
    result=cleanup(spec['files'],Path(spec['record']),spec['reason'])
    print(json.dumps({k:v for k,v in result.items() if k!='files'}))


if __name__=='__main__':main()
