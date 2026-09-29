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
    'confirmation_setup_rejected','stack_frontend','confirmation','wake_validation','backend',
    'callpath_native_preflight','callpath','call_frequency','callpath_refinement','callpath_coverage75','callpath_frontend','balanced_callpath','hybrid_switch',
    'hybrid_native_preflight','hybrid_native_preflight_initial','hybrid_native_preflight_rejected_dependency','hybrid_native_preflight_shim_warning',
    'callpath_frontend_rejected_msr_conflict','split_fetch_probe','split_fetch_intermission',
    'split_target_refine','coverage75_finish_intermission','resume_hint_probe',
    'hybrid_service_preflight','hybrid_mapping_debug','balanced_callpath_rejected_startup']
BACKEND_PHASES={'backend','callpath_native_preflight','callpath','call_frequency','callpath_refinement','callpath_coverage75','callpath_frontend','balanced_callpath','hybrid_switch',
    'hybrid_native_preflight','hybrid_native_preflight_initial','hybrid_native_preflight_rejected_dependency','hybrid_native_preflight_shim_warning'}

def pack(root,out,native_only=False,phases=None):
    assert (root/'confirmation_followup_complete.json').exists(),'Archive completed native validation only'
    if phases is not None:
        assert phases and set(phases)<=set(PHASES) and not native_only
        for phase in phases:
            assert (root/phase/'complete.json').exists() or (root/phase/'rejection.json').exists(), 'Archive only completed or explicitly rejected phases: '+phase
    if not native_only:
        for phase in ['backend','callpath','call_frequency','callpath_refinement','callpath_coverage75','callpath_frontend','balanced_callpath','hybrid_switch']:
            if phases is not None and phase not in phases:continue
            if (root/phase).exists():
                assert (root/phase/'complete.json').exists(), 'Do not archive an active backend phase: '+phase
    out.mkdir(parents=True,exist_ok=True);manifest=[]
    def eligible(path):
        if path.is_symlink() or not path.is_file():return False
        rel=path.relative_to(root)
        if any(p.endswith('_work') or p.startswith('test_work') or p.startswith('backend_test_work') for p in rel.parts):return False
        if '_live.' in path.name:return False
        if path.name.endswith('_pending.json') and (path.parent/'result.json').exists():return False
        # Runtime snapshots can contain full container environments; specific
        # binary/dataset/platform checks are sufficient for this public archive.
        if path.name in ['runtime.json','service-config.json','compose.json','nginx_jaeger.json']:return False
        return path.suffix in ('.json','.csv','.log','.maps','.c','.cc','.cpp','.py',
                               '.s','.S','.ld','.asm','.md') or path.name=='maps.txt'
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
    if phases is None:
        bundle('campaign',[p for p in root.iterdir() if p.is_file() and not (native_only and p.name.startswith(('backend','callpath')))])
    for name in phases if phases is not None else PHASES:
        if native_only and name in BACKEND_PHASES:continue
        folder=root/name
        if folder.exists():bundle(name,folder.rglob('*'))
    for folder in sorted(root.glob('*_platform')):
        if phases is not None:continue
        if folder.is_dir() and not folder.is_symlink():bundle(folder.name,folder.rglob('*'))
    # Compact training inputs support retarget/thinning reproduction after the
    # much larger decoded traces have been removed.
    for pattern in ['refine_observations/*.gz','builds/**/*.observations.json.gz','backend/observations/*.gz',
                    'callpath/observations/*.gz','callpath/residual_observations/*.gz',
                    'callpath_coverage75/residual_observations/*.gz']:
        if native_only and pattern.startswith(('backend/','callpath/','callpath_coverage75/')):continue
        if phases is not None and pattern.split('/')[0] not in phases:continue
        for source in sorted(root.glob(pattern)):
            assert source.is_file() and not source.is_symlink()
            dest=out/source.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
            assert b.sha(source)==b.sha(dest)
            manifest.append(dict(file=str(dest.relative_to(out)),sha256=b.sha(dest),bytes=dest.stat().st_size,source=str(source)))
    b.save(out/'manifest.json',dict(source_root=str(root),archiver_sha256=b.sha(__file__),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),entries=manifest,
        backend_included=not native_only,
        selected_phases=phases,
        scope='Compact measurements, settings, commands, quality, failure/exclusion, patch/hash and cleanup records. Executables, raw/decoded traces, original input datasets and full container environments remain outside Git.'))
    print(json.dumps(dict(bundles=len(manifest),compressed_bytes=sum(x['bytes'] for x in manifest))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);p.add_argument('--native-only',action='store_true')
    p.add_argument('--phase',action='append',choices=PHASES);a=p.parse_args();pack(a.root,a.out,a.native_only,a.phase)
