#!/usr/bin/env python3
"""Publish a completed serial stage, keeping active measurement data separate."""
import argparse
import gzip
import json
from pathlib import Path
import dense_build as b
from mechanism_archive import pack

NAMES={'balanced_callpath':'balanced_completed','hybrid_switch':'hybrid_completed','split_coverage':'split_coverage_completed'}


def publish(parent,phase):
    root=parent/phase;assert (root/'complete.json').exists();b.space(parent)
    out=b.REPO/'llvm_prefetchit/migration/evidence'/parent.name/NAMES[phase]
    assert not out.exists(), 'Never silently replace a published result bundle'
    from baseline_variation import report as baseline_variation
    baseline_variation(root)
    if phase=='hybrid_switch':
        from hybrid_report import report as hybrid_report
        hybrid_report(root)
    pack(parent,out/'artifacts',phases=[phase])
    # Read and verify every compressed record before publishing its manifest.
    archive=json.loads((out/'artifacts/manifest.json').read_text())
    for entry in archive['entries']:
        path=out/'artifacts'/entry['bundle'];assert b.sha(path)==entry['sha256']
        with gzip.open(path,'rt') as stream:json.load(stream)
    names=['complete.json','screen_report.md','report.md','grouped_pmu.json','screen_evaluation.json',
        'workload_age.json','cpu_attribution.json','cpu_attribution.md','protocol.json',
        'hybrid_diagnostics.json','hybrid_diagnostic_report.md',
        'baseline_variation.json','baseline_variation.md']
    for name in names:
        source=root/name
        if source.exists():(out/name).write_bytes(source.read_bytes())
    figures=[]
    for source in sorted((root/'figures').glob('*')):
        assert source.is_file() and not source.is_symlink() and source.suffix in ['.png','.svg']
        dest=b.REPO/'docs/figures'/f'class_b_hybrid_20260929_{phase}_{source.name}'
        dest.write_bytes(source.read_bytes());assert b.sha(source)==b.sha(dest);figures.append(dest)
    b.save(out/'manifest.json',dict(source_root=str(root),phase=phase,
        publisher_sha256=b.sha(__file__),files={p.name:dict(bytes=p.stat().st_size,sha256=b.sha(p)) for p in out.iterdir() if p.is_file()},
        figures={str(p.relative_to(b.REPO)):dict(bytes=p.stat().st_size,sha256=b.sha(p)) for p in figures},
        scope='Completed fresh-stack E2E and separate post-ROI PMU stage. Individual paired-log intervals, no multiplicity correction; no pooling with prior protocols. No executable, original dataset or active phase is copied.'))
    print(json.dumps(dict(valid=True,output=str(out))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('parent',type=Path);parser.add_argument('phase',choices=list(NAMES))
    args=parser.parse_args();publish(args.parent,args.phase)
