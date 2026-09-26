#!/usr/bin/env python3
"""Retain compact evidence, then unlink only explicit campaign artifacts."""
from pathlib import Path
import shutil
import fullset as h


def cleanup(paths, record, reason):
    assert reason and not record.exists()
    rows=[]
    for raw in paths:
        p=Path(raw).absolute()
        assert p.is_file() and not p.is_symlink() and p.resolve()==p,p
        allowed=p.is_relative_to(h.TRACE)
        allowed |= (p.parent.name=='fullset_coverage' and p.parent.parent.parent in
                    [h.c.S/'media_build',h.c.S/'social_build'] and
                    p.name in [v[1]+suffix for targets in h.TARGETS.values() for v in targets.values() for suffix in ('','.nop')])
        assert allowed,p
        rows.append(dict(path=str(p),bytes=p.stat().st_size,sha256=h.c.sha(p)))
    free=lambda:{str(p):shutil.disk_usage(p).free for p in (Path('/'),Path('/storage'),Path('/trace'))}
    result=dict(reason=reason,files=rows,bytes_removed=0,free_before=free(),status='prepared')
    h.c.save(record,result)
    for row in rows:
        Path(row['path']).unlink();result['bytes_removed']+=row['bytes']
    result.update(status='complete',free_after=free());h.c.save(record,result)


def trace_done(root):
    paths=[]
    for p in root.rglob('*'):
        if p.is_file() and not p.is_symlink() and ('symfs' in p.parts or p.name in
            ('pt.data','branches.txt','syscall_context.txt','misses.txt','misses.data') or p.name.endswith('.syscall.data')):
            paths.append(p)
    cleanup(paths,root/'bulk_cleanup.json','PT plans, temporal validation, mapped binary hashes, run summaries and build records extracted; raw/decoded copies no longer used')
