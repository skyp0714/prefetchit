#!/usr/bin/env python3
"""Independent E2E check of the best-latency dense screen candidate.

The original CPU-gated selection is retained. This separate experiment removes
that extra CPU eligibility requirement to answer the user's E2E-first question.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import time

import dense_build as b


def read(path): return json.loads(path.read_text())


def preregister(root):
    evidence=b.REPO/'llvm_prefetchit/migration/evidence/class_b_dense_20260927'
    path=evidence/'latency_followup_protocol.json';assert not path.exists()
    screen=read(root/'screen/summary.json')
    winner=max(('callee8','seq4k','seq256'),key=lambda arm:screen[arm]['base']['mean_ms']['cost_reduction_pct'])
    assert winner=='callee8'
    b.save(path,dict(registered_epoch=time.time(),selected=winner,
        reason='Original selection required positive CPU point estimates against both controls. This excluded callee8 '
            'despite its best external mean/p99 screen results, contrary to the user emphasis on E2E. '
            'Retain that original analysis; run a distinct E2E-first validation on NEW seeds.',
        selection='Largest mean-latency reduction versus original baseline among the three frozen policies; screen only',
        screen_sha256=b.sha(root/'screen/summary.json'),
        builds='Rebuild both baseline and selected policy using the same retained source, plugin and image. '
            'Audit exact-layout NOP twin; record full SHA equality with original artifacts. Reuse original baseline only if all three SHA hashes match.',
        arms=['base','callee8_nop','callee8'],blocks=7,seedbase=44001,rate=1000,pool=8,roi_s=90,warmup_s=50,
        timing='Fresh stacks, rotated/reversed order; no PMU recorder, no build/decoding overlap',
        promotion='One SAME external latency endpoint (mean or p99) must have a positive 97.5% CI lower bound '
            'against BOTH baseline and NOP. All mean/p99 point regressions must be <=2% versus either control. '
            'CPU/request is reported independently and is not an eligibility gate.',
        analysis='Paired log ratios; 95% intervals for descriptive comparisons and 97.5% intervals for the '
            'two latency endpoints (Bonferroni for endpoint selection). Screening and prior seq4k data are not pooled.',
        rejection='Keep every operating failure and stop for diagnosis; do not retry based on latency. '
            'Remove rejected generated PF/NOP binaries immediately after final decision.'))
    print(path)


def run(root):
    assert os.geteuid()==0
    import dense_study as ds
    from e2e_lbr import remove_generated
    protocol=read(b.REPO/'llvm_prefetchit/migration/evidence/class_b_dense_20260927/latency_followup_protocol.json')
    assert b.sha(root/'screen/summary.json')==protocol['screen_sha256']
    assert (root/'measurements_complete.json').exists(), 'Finish prior timings before building'
    assert read(root/'concurrency/complete.json')['rows']==18
    assert b.sha(b.REPO/'llvm_prefetchit/build/PrefetchITPass.so')==read(root/'protocol.json')['plugin_sha256']
    expected_image=read(b.REPO/'llvm_prefetchit/migration/evidence/class_b_dense_20260927/environment.json')['image']
    assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','dsb-deps-jammy'],text=True).strip()==expected_image
    b.save(root/'latency_followup_protocol.json',protocol)
    sources=root/'latency_followup_sources';sources.mkdir(exist_ok=False)
    source_files=[Path(__file__),Path(b.__file__),Path(ds.__file__),Path(ds.__file__).with_name('fullset.py')]
    for source in source_files:shutil.copyfile(source,sources/source.name)
    b.save(sources/'hashes.json',{str(p):b.sha(p) for p in source_files})
    variants={'base':'latency_base','callee8':'latency_callee8'}
    for arm,tag in variants.items():b.build(root,arm,tag)
    ds.audit(root,variants,'latency_followup_')
    original={(r['arm'],r['service']):r for r in read(root/'binary_audit.json')}
    rebuilt=read(root/'latency_followup_binary_audit.json');equivalence=[]
    for row in rebuilt:
        old=original[row['arm'],row['service']]
        equivalence.append(dict(arm=row['arm'],service=row['service'],original_sha256=old['sha256'],
            rebuilt_sha256=row['sha256'],identical=row['sha256']==old['sha256']))
    b.save(root/'latency_followup_build_equivalence.json',equivalence)
    arms=read(root/'latency_followup_arms.json')
    if all(r['identical'] for r in equivalence if r['arm']=='base'):
        duplicates=[Path(p) for p in arms['base']['overrides'].values()]
        arms['base']=read(root/'arms.json')['base']
        b.save(root/'latency_followup_arms.json',arms)
        remove_generated(duplicates,root/'latency_baseline_dedup_cleanup.json',
            'Fresh rebuild is byte-identical to retained baseline; use that existing reference in all followup timings')
    ordered={name:arms[name] for name in protocol['arms']}
    summary=ds.study(root,'latency_followup',ordered,protocol['blocks'],protocol['seedbase'])
    rows=read(root/'latency_followup/rows.json');assert len(rows)==21 and all(r['valid'] for r in rows)
    from scipy.stats import t
    metrics=summary['callee8']
    for control,values in metrics.items():
        for key in ('mean_ms','p99_ms'):
            by_block={block:{r['arm']:r['metrics'][key] for r in rows if r['block']==block} for block in range(7)}
            ratios=[math.log(p[control]/p['callee8']) for p in by_block.values()]
            mean=statistics.mean(ratios);half=float(t.ppf(.9875,6))*statistics.stdev(ratios)/math.sqrt(7)
            values[key]['ci97_5_pct']=[100*(1-math.exp(-(mean-half))),100*(1-math.exp(-(mean+half)))]
    endpoints=[key for key in ('mean_ms','p99_ms') if all(v[key]['ci97_5_pct'][0]>0 for v in metrics.values())]
    safe=all(v[key]['cost_reduction_pct']>=-2 for v in metrics.values() for key in ('mean_ms','p99_ms'))
    promoted=bool(endpoints) and safe
    b.save(root/'latency_followup_decision.json',dict(selected='callee8',promoted=promoted,
        confirmed_latency_endpoints=endpoints,point_regression_gate=safe,metrics=metrics,
        cpu_improved_95=all(v['stack_cpu']['ci95_pct'][0]>0 for v in metrics.values()),
        ten_percent_supported=any(all(v[key]['ci97_5_pct'][0]>=10 for v in metrics.values()) for key in ('mean_ms','p99_ms'))))
    if not promoted:
        paths=[Path(p) for arm in ('callee8','callee8_nop') for p in arms[arm]['overrides'].values()]
        remove_generated(paths,root/'latency_followup_rejected_cleanup.json',
            'Independent E2E-first validation failed frozen latency criteria; all outcomes, sources, hashes and patches retained')
    b.save(root/'latency_followup_complete.json',dict(complete=True,promoted=promoted,rows=len(rows)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['preregister','run']);parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    globals()[args.action](args.root)
