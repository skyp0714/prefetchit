#!/usr/bin/env python3
"""Display the held-aside alignment test of the native IT0 positional rule."""
import argparse
import json
from pathlib import Path
import dense_build as b


def report(root):
    assert json.loads((root/'complete.json').read_text())['valid']
    records=json.loads((root/'summary.json').read_text())['records']
    rows=json.loads((root/'rows.json').read_text());audit=json.loads((root/'binary_audit.json').read_text())
    predicted=[];other=[]
    for row in rows:
        if row['kind']!='it0_8':continue
        wanted=audit[str(root/f'a{row["offset"]}_it0_8')]['predicted_targets']
        for index,value in enumerate(row['target_tsc']):(predicted if index in wanted else other).append(value)
    separation=dict(max_predicted_target_mean_tsc=max(predicted),min_other_target_mean_tsc=min(other),
        predicted_observations=len(predicted),other_observations=len(other),
        scope='Per-target means in each of two repetitions, not per-request maxima or percentiles. Prediction came from the earlier independent offset-zero burst probe; no latency threshold was used to choose positions.')
    b.save(root/'positional_separation.json',separation)
    lines=['# Native IT0 positional calibration','',
        'Eight function offsets, four opcode policies, two repetitions: 64 fully scheduled trials after actual same-CPU blocking handoff. One dependency-delayed demand target from eight flushed candidate lines; same-address NOP control for each offset.',
        '', '| Function offset | Predicted IT0 target positions | Eight IT0 retired L2/iteration | Only predicted IT0 slots | Predicted IT0 + remaining T1 |',
        '|---|---|---:|---:|---:|']
    offsets=sorted({r['offset'] for r in records})
    for offset in offsets:
        r={row['kind']:row for row in records if row['offset']==offset}
        lines.append(f'| {offset} | '+', '.join(map(str,r['it0_8']['predicted_targets']))+' | '+
            ' | '.join(f'{r[k]["per_iteration"]["FE_L2"]:.5f}' for k in ['it0_8','end32_it0','mixed32'])+' |')
    lines += ['', f'Across all 16 all-IT0 runs, the 40 predicted-position per-target means were at most {max(predicted):.2f} TSC ticks; the 88 remaining means were at least {min(other):.2f}. These are aggregate target means, not individual latency bounds.',
        '', 'The observed pattern follows the first IT0 whose final byte lies in each 32-byte region. Retaining only those IT0 slots preserved broadly similar retired-miss behavior; making the remaining slots T1 removed most residual demand misses. This is a repeatable property of this calibration on this processor. It does not establish the internal queue structure, architectural acceptance rules, or production-code behavior.',
        '', 'No hint, target, or original instruction addresses move between opcode controls at one offset. Across offsets, the hint function moves within alignment padding while main and all demand targets retain their addresses. These synthetic measurements are not application E2E speedup.']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import numpy as np
    selected=[next(r for r in records if r['offset']==offset and r['kind']=='it0_8') for offset in offsets]
    data=np.array([r['target_tsc'] for r in selected])
    fig,ax=plt.subplots(figsize=(10,5.7),constrained_layout=True)
    im=ax.imshow(data,aspect='auto',cmap='viridis',vmin=50,vmax=420)
    for i,row in enumerate(selected):
        for j in range(8):
            ax.text(j,i,f'{data[i,j]:.0f}',ha='center',va='center',color='white' if data[i,j]<220 else 'black',fontsize=9)
            if j in row['predicted_targets']:ax.add_patch(Rectangle((j-.49,i-.49),.98,.98,fill=False,edgecolor='#efefef',linewidth=2))
    ax.set_yticks(range(len(offsets)),[str(v) for v in offsets]);ax.set_xticks(range(8))
    ax.set_ylabel('Hint function offset within 4 KiB page');ax.set_xlabel('Target position in contiguous eight-IT0 burst')
    ax.set_title('Effective IT0 positions move with a 32-byte instruction-end boundary')
    fig.colorbar(im,ax=ax,label='Mean target call latency (TSC ticks)')
    fig.supxlabel('White boxes: positions predicted before the alignment test. Two-repeat means after task handoff.\nSynthetic calibration; not a queue-capacity claim or application speedup.',fontsize=9)
    out=root/'figures';out.mkdir(exist_ok=True)
    for ext in ['png','svg']:fig.savefig(out/('alignment.'+ext),dpi=180)
    plt.close(fig)
    b.save(root/'report_manifest.json',dict(source_sha256=b.sha(__file__),input_sha256=b.sha(root/'summary.json'),
        files={str(p.relative_to(root)):b.sha(p) for p in [root/'report.md',root/'positional_separation.json',*out.iterdir()]}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();report(args.root)
