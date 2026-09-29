#!/usr/bin/env python3
"""Keep the exploratory E2E candidate and remove superseded generated ELFs."""
import argparse
import json
from pathlib import Path
import dense_build as b
from e2e_lbr import remove_generated


def retire(root):
    assert (root/'complete.json').exists(), 'No cleanup while any backend capture still uses its artifacts'
    assert not (root/'retired_artifacts.json').exists(), 'Retirement already recorded'
    evaluation=json.loads((root/'screen_evaluation.json').read_text())
    spec=json.loads((root/'screen_spec.json').read_text());assert evaluation['complete']
    candidates=[]
    for name in ['mongo256','native','combined','native_it0','native_it1']:
        metrics=evaluation['e2e'][name]['mongo_nop']
        row=dict(name=name,speedup=metrics['inverse_rps']['speedup'],speedup_ci95=metrics['inverse_rps']['speedup_ci95'],
            cpu_reduction=metrics['stack_cpu']['cost_reduction_pct'],p99_reduction=metrics['p99_ms']['cost_reduction_pct'])
        row['eligible']=row['speedup']>1 and row['cpu_reduction']>=0 and row['p99_reduction']>=-1
        candidates.append(row)
    eligible=[r for r in candidates if r['eligible']]
    chosen=max(eligible,key=lambda r:(r['speedup'],r['cpu_reduction'])) if eligible else None
    retained=set()
    if chosen:
        setting=spec['arms'][chosen['name']]
        retained.update(Path(p) for p in setting['overrides'].values())
        if setting.get('mongo_binary'):retained.add(Path(setting['mongo_binary']))
    generated={}
    for name in ['native_it0','native_it1']:
        for path in spec['arms'][name]['overrides'].values():
            path=Path(path);metadata=path.with_suffix('.opcode.json')
            assert path.is_relative_to(root/'builds')
            generated[path]=metadata
    path=Path(spec['arms']['mongo256']['mongo_binary']);generated[path]=path.with_suffix('.patches.json')
    discarded=[]
    for path,metadata in generated.items():
        assert path.is_file() and not path.is_symlink() and metadata.is_file()
        assert json.loads(metadata.read_text())['sha256']==b.sha(path)
        if path not in retained:discarded.append(path)
    b.save(root/'artifact_selection.json',dict(candidates=candidates,chosen=chosen,
        retained_generated=[str(p) for p in generated if p in retained],discarded_generated=list(map(str,discarded)),
        rule='Exploratory artifact retention only: highest throughput point estimate versus copied original among policies with nonnegative CPU reduction and <=1% p99 regression. This post-hoc screen choice is not an independently confirmed winner.',
        original_references='Original Mongo and existing native T1/NOP references remain untouched. Next call-path experiment uses original Mongo.',
        source_sha256=b.sha(__file__)))
    remove_generated(discarded,root/'retired_artifacts.json',
        'Completed backend/opcode screen and wake diagnostics. Keep only its exploratory E2E candidate, original and existing controls; retain all results, patches, settings and hashes before deleting unused generated ELFs.')
    return chosen


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();retire(args.root)
