#!/usr/bin/env python3
"""Freeze one screen winner and confirm seven fresh-seed pairs.

Base and old wake16 are measured in all seven blocks. A distinct layout NOP is
included in the first three blocks only; its smaller sample is reported as such.
Screen data is never pooled with confirmation. No PMU runs in primary windows.
"""
import json
from pathlib import Path

import social_headroom as h
from paired_study import summarize
from retain_artifacts import cleanup


def main():
    screens=('screen','padding_screen','padding_wide_screen')
    candidates=[]
    for name in screens:
        directory=h.OUT/name
        assert (directory/'complete.json').exists(),name
        rows=json.loads((directory/'rows.json').read_text())
        spec=json.loads((directory/'protocol.json').read_text())
        base=next(r for r in rows if r['arm']=='base')
        assert base['valid']
        for row in rows:
            if row['valid'] and row['arm'].startswith(('stream_','padding')):
                candidates.append(dict(arm=row['arm'],binary=spec['arms'][row['arm']]['binary'],
                    screen=name,saving_pct=100*(1-row['target_cpu']/base['target_cpu']),row=row))
    assert candidates
    selected=max(candidates,key=lambda r:r['saving_pct'])
    base=str(h.c.S/'social_build/usertimeline/base'/h.EXE)
    old=str(h.c.S/'social_build/usertimeline/wake16'/h.EXE)
    nop=selected['binary']+'.nop' if selected['arm'].startswith('stream_') else base
    assert Path(nop).is_file()
    all_arms={'base':dict(binary=base), 'old_wake16':dict(binary=old,controls=['base']),
              'candidate':dict(binary=selected['binary'],controls=['base','old_wake16'])}
    if nop!=base:
        all_arms['layout_nop']=dict(binary=nop,controls=['base'])
        all_arms['candidate']['controls'].append('layout_nop')
    policy=dict(selected=selected,candidates=candidates,arms=all_arms,blocks=7,nop_blocks=3 if nop!=base else 7,
        seeds=list(range(9301,9308)),pmu=False,primary='target user+kernel CPU per completed request',
        inference='Seven fresh-seed paired log ratios against base and old wake16; separate three-block layout NOP contrast if applicable.',
        promotion='Require seven valid pairs and positive individual 95% lower bounds against both base and old wake16; 10% remains a target, not an assumption.')
    assert not (h.OUT/'confirmation_selection.json').exists()
    h.c.save(h.OUT/'confirmation_selection.json',policy)
    # The implementation and predeclared settings remain in Git/results. Keep
    # only the selected executable and its necessary NOP control for timing.
    losers=[]
    for row in candidates:
        if row is selected:continue
        for path in (Path(row['binary']),Path(row['binary']+'.nop')):
            if path.exists() and str(path) not in (selected['binary'],nop):losers.append(path)
    if losers:
        cleanup(sorted(set(losers)),h.OUT/'screen_candidate_cleanup.json',
                'Superseded by frozen confirmation candidate; screen measurements, settings, source and hashes retained')
    merged=[]
    for stage,blocks,start in [('a',3,0),('b',4,3)]:
        arms={k:v for k,v in all_arms.items() if stage=='a' or k!='layout_nop'}
        manifest=dict(out=str(h.OUT/('confirmation_'+stage)),pool=4,rate=600,seedbase=9301+start,
                      blocks=blocks,pmu=False,arms=arms,confirmation_policy=str(h.OUT/'confirmation_selection.json'))
        path=h.OUT/('confirmation_'+stage+'_manifest.json');h.c.save(path,manifest)
        h.c.run(['python3',h.REPO/'llvm_prefetchit/scripts/class_b/paired_study.py',path],
                h.OUT/('confirmation_'+stage+'.log'),timeout=14400)
        rows=json.loads((Path(manifest['out'])/'rows.json').read_text())
        for row in rows:row['block']+=start
        merged.extend(rows)
        h.c.save(h.OUT/'confirmation_rows.json',merged)
        h.c.save(h.OUT/'confirmation_summary.json',summarize(merged,all_arms))
    summary=summarize(merged,all_arms)
    checks=[summary['candidate'][control]['target_cpu'] for control in ('base','old_wake16')]
    promoted=all(r['pairs']==7 and r['ci95_pct'][0]>0 for r in checks)
    h.c.save(h.OUT/'confirmation_complete.json',dict(promoted=promoted,rows=len(merged),
        valid_rows=sum(r['valid'] for r in merged),selected=selected,summary=summary))
    if not promoted:
        cleanup([Path(p) for p in (selected['binary'],nop) if p!=base],h.OUT/'confirmation_rejection_cleanup.json',
                'Did not demonstrate a confirmed incremental CPU saving against both base and old wake16; retain compact results and source')
    print(json.dumps(dict(promoted=promoted,selected=selected['arm'],summary=summary),indent=2),flush=True)


if __name__=='__main__':main()
