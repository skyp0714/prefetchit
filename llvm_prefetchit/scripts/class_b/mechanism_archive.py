#!/usr/bin/env python3
"""Publish compact, auditable campaign records without executable/trace bulk."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import dense_build as b

PHASES=['probe','probe_serialized','probe_fixed','screen','retarget_screen','retarget_training',
    'refine_training','builds','crossover','crossover_preflight','crossover_startup_blocked',
    'confirmation_setup_rejected','stack_frontend','confirmation','wake_validation','backend']

def pack(root,out):
    assert (root/'confirmation_followup_complete.json').exists(),'Archive completed native validation only'
    out.mkdir(parents=True,exist_ok=True);manifest=[]
    def eligible(path):
        if path.is_symlink() or not path.is_file():return False
        rel=path.relative_to(root)
        if any(p.endswith('_work') or p.startswith('test_work') or p.startswith('backend_test_work') for p in rel.parts):return False
        if '_live.' in path.name or path.name.endswith('_pending.json'):return False
        # Runtime snapshots can contain full container environments; specific
        # binary/dataset/platform checks are sufficient for this public archive.
        if path.name in ['runtime.json','service-config.json','compose.json','nginx_jaeger.json']:return False
        return path.suffix in ('.json','.csv','.log','.maps','.c','.py') or path.name=='maps.txt'
    def bundle(name,paths):
        records={};entries=[]
        for path in sorted(set(paths)):
            if not eligible(path):continue
            raw=path.read_bytes();relative=str(path.relative_to(root))
            if len(raw)>16*2**20:raise ValueError('Unexpectedly large compact record: '+relative)
            content=json.loads(raw) if path.suffix=='.json' else raw.decode()
            records[relative]=content
            entries.append(dict(path=relative,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        dest=out/(name+'.json.gz')
        with gzip.GzipFile(filename=str(dest),mode='wb',mtime=0) as f:
            f.write(json.dumps(records,separators=(',',':'),sort_keys=True).encode())
        manifest.append(dict(bundle=dest.name,sha256=b.sha(dest),bytes=dest.stat().st_size,records=entries))
    bundle('campaign',[p for p in root.iterdir() if p.is_file()])
    for name in PHASES:
        folder=root/name
        if folder.exists():bundle(name,folder.rglob('*'))
    # Compact training inputs support retarget/thinning reproduction after the
    # much larger decoded traces have been removed.
    for name in ['refine_observations','retarget_observations','backend/observations']:
        folder=root/name
        if not folder.exists():continue
        for source in sorted(folder.glob('*.gz')):
            dest=out/name/source.name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
            assert b.sha(source)==b.sha(dest)
            manifest.append(dict(file=str(dest.relative_to(out)),sha256=b.sha(dest),bytes=dest.stat().st_size,source=str(source)))
    b.save(out/'manifest.json',dict(source_root=str(root),archiver_sha256=b.sha(__file__),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),entries=manifest,
        scope='Compact measurements, settings, commands, quality, failure/exclusion, patch/hash and cleanup records. Executables, raw/decoded traces, original input datasets and full container environments remain outside Git.'))
    print(json.dumps(dict(bundles=len(manifest),compressed_bytes=sum(x['bytes'] for x in manifest))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);a=p.parse_args();pack(a.root,a.out)
