#!/usr/bin/env python3
"""Publish completed split75 diagnostics and trials without executable bulk."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import dense_build as b


def publish(root):
    for stage in ['hybrid_screen','lead_screen','residual_diagnostics']:
        assert json.loads((root/stage/'complete.json').read_text())['valid']
    b.space(root)
    out=b.REPO/'llvm_prefetchit/migration/evidence'/root.name
    assert not out.exists();out.mkdir(parents=True)
    artifacts=out/'artifacts';artifacts.mkdir();manifest=[]
    def eligible(path):
        if path.is_symlink() or not path.is_file():return False
        if 'runtime_config' in path.parts:return False
        if any(part.endswith('_work') for part in path.relative_to(root).parts):return False
        if path.name in ['runtime.json','service-config.json','compose.json','nginx_jaeger.json']:return False
        if path.name.endswith('_pending.json') and (path.parent/'result.json').exists():return False
        return path.suffix in {'.json','.csv','.log','.maps','.c','.cc','.cpp','.h','.py','.s','.S','.ld','.asm','.md'} or path.name=='maps.txt'
    groups={'campaign':[p for p in root.iterdir() if p.is_file()]}
    groups.update({p.name:list(p.rglob('*')) for p in root.iterdir() if p.is_dir() and not p.is_symlink()})
    for name,paths in sorted(groups.items()):
        records={};entries=[]
        for path in sorted(paths):
            if not eligible(path):continue
            raw=path.read_bytes();assert len(raw)<16*2**20,(path,'unexpected bulk record')
            relative=str(path.relative_to(root));records[relative]=raw.decode()
            entries.append(dict(path=relative,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        if not records:continue
        destination=artifacts/(name+'.json.gz')
        with gzip.GzipFile(filename=str(destination),mode='wb',mtime=0) as stream:
            stream.write(json.dumps(records,sort_keys=True,separators=(',',':')).encode())
        with gzip.open(destination,'rt') as stream:verified=json.load(stream)
        assert set(verified)==set(records)
        for entry in entries:assert hashlib.sha256(verified[entry['path']].encode()).hexdigest()==entry['sha256']
        manifest.append(dict(bundle=str(destination.relative_to(out)),sha256=b.sha(destination),bytes=destination.stat().st_size,records=entries))
    for source in sorted((root/'residual_diagnostics').rglob('*_observations.json.gz')):
        assert source.is_file() and not source.is_symlink()
        destination=artifacts/source.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(source.read_bytes());assert b.sha(source)==b.sha(destination)
        with gzip.open(destination,'rt') as stream:assert isinstance(json.load(stream),list)
        manifest.append(dict(file=str(destination.relative_to(out)),sha256=b.sha(destination),bytes=destination.stat().st_size,source=str(source)))
    checks=[]
    for platform in sorted(root.rglob('*_platform')):
        if platform.is_symlink() or not platform.is_dir():continue
        for before in sorted(platform.rglob('*_before.json')):
            after=before.with_name(before.name.replace('_before','_restored'))
            same=after.exists() and json.loads(before.read_text())==json.loads(after.read_text())
            checks.append(dict(before=str(before.relative_to(root)),restored=same))
    assert checks and all(row['restored'] for row in checks)
    b.save(out/'platform_restoration.json',dict(valid=True,checks=len(checks),records=checks))
    figures=[]
    for stage in ['hybrid_screen','lead_screen']:
        destination=out/stage;destination.mkdir()
        for name in ['complete.json','report.md','screen_evaluation.json','topdown.json','topdown.md',
            'cpu_attribution.json','cpu_attribution.md','baseline_variation.json','baseline_variation.md','workload_age.json','protocol.json']:
            source=root/stage/name
            if source.exists():(destination/name).write_bytes(source.read_bytes())
        for source in sorted((root/stage/'figures').glob('*')):
            assert source.suffix in ['.png','.svg'] and not source.is_symlink()
            dest=b.REPO/'docs/figures'/f'{root.name}_{stage}_{source.name}'
            dest.write_bytes(source.read_bytes());assert b.sha(dest)==b.sha(source);figures.append(dest)
    b.save(out/'manifest.json',dict(source_root=str(root),publisher_sha256=b.sha(__file__),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),entries=manifest,
        figures={str(p.relative_to(b.REPO)):dict(bytes=p.stat().st_size,sha256=b.sha(p)) for p in figures},
        scope='Completed measurements, negative/excluded attempts, commands, settings, source/patch/hash records, sparse observations and cleanup records. Byte-exact text round-trip verified. No executables, objects, original benchmark inputs, raw/decoded traces, container environments or active experiments. Existing campaigns are not pooled.'))
    print(json.dumps(dict(output=str(out),bundles=len(manifest),bytes=sum(v['bytes'] for v in manifest),restoration_checks=len(checks))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    publish(parser.parse_args().root)
