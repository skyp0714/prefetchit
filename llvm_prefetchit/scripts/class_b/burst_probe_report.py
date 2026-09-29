#!/usr/bin/env python3
"""Report native burst observations separately from application performance."""
import argparse
import json
from pathlib import Path
import dense_build as b


def report(root):
    assert json.loads((root/'complete.json').read_text())['valid']
    values=json.loads((root/'summary.json').read_text())['records']
    records=[row for row in values if row['handoff']==1]
    lines=['# Native dependent-demand burst calibration','',
        'Eight possible target lines flushed per iteration; one target selected from the result of 512 dependent IMUL operations. Same-CPU blocking handoff. Three repeats per condition, 20,000 iterations per repeat; all 48 windows fully scheduled and every target return checked.',
        '', '| Policy | Retired L2 / iteration | Speculative code-read misses / iteration | Target call TSC | Hint body + target TSC |',
        '|---|---:|---:|---:|---:|']
    for row in records:
        p=row['per_iteration'];lines.append(f'| {row["kind"]} | {p["FE_L2"]:.5f} | {p["L2I"]:.5f} | {row["mean_calls_tsc"]:.2f} | {row["mean_body_tsc"]:.2f} |')
    lines += ['', 'The contiguous eight-IT0 burst consistently accelerated target positions 0 and 4; the other positions retained long call times. This is a measured layout-dependent pattern, not proof of fetch-queue capacity or a guarantee of one accepted hint per fetch block. Spaced IT0 and the mixed burst cover more target positions.',
        '', 'The earlier fixed-target probe is retained separately: its NOP already hid almost all demand misses during the long lead. It cannot identify a useful burst width.',
        '', 'These timings exclude CLFLUSH and handoff, include serial timestamp overhead, and are not application E2E speedup. Full iteration CPU cycles can rise because seven prefetched targets are unused in this artificial one-of-eight workload and all eight targets are flushed again. Neither event count nor local target latency alone establishes service benefit.',
        '', 'The hint code is not explicitly flushed; kernel execution can still affect its residency. No direct fetch-queue or DSB occupancy is measured.']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    names=[row['kind'] for row in records]
    labels=['NOP','IT0 x1','IT0 x2','IT0 x4','IT0 x8','T1 x8','Spaced IT0 x8','IT0 x1 + T1 x7']
    fig,axes=plt.subplots(1,3,figsize=(15,5.3),constrained_layout=True,gridspec_kw={'width_ratios':[1,1,1.4]})
    for ax,key,title in [(axes[0],'FE_L2','Retired L2 events / iteration'),(axes[1],'mean_body_tsc','Hint body + demand target (TSC ticks)')]:
        numbers=[row['per_iteration'][key] if key=='FE_L2' else row[key] for row in records]
        ax.barh(range(len(names)),numbers,color=['#82919c']+['#3c7893']*4+['#348b76','#7555a1','#bc7732'])
        ax.set_yticks(range(len(names)),labels);ax.invert_yaxis();ax.set_title(title,fontsize=10)
        ax.grid(axis='x',alpha=.2);ax.spines[['top','right']].set_visible(False)
    data=np.array([row['target_tsc'] for row in records])
    im=axes[2].imshow(data,aspect='auto',cmap='viridis',vmin=40,vmax=410)
    axes[2].set_yticks(range(len(names)),labels);axes[2].set_xticks(range(8));axes[2].set_xlabel('Demand target position')
    axes[2].set_title('Per-target call latency (TSC ticks)',fontsize=10)
    for i in range(len(names)):
        for j in range(8):axes[2].text(j,i,f'{data[i,j]:.0f}',ha='center',va='center',fontsize=7,color='white' if data[i,j]<230 else 'black')
    fig.colorbar(im,ax=axes[2],shrink=.7)
    fig.suptitle('Native calibration after task handoff: burst placement matters')
    fig.supxlabel('Three-repeat means; synthetic cold-target experiment, not service speedup.\nBody timing excludes flush/handoff; no direct observation of fetch-queue or DSB occupancy.',fontsize=9)
    out=root/'figures';out.mkdir(exist_ok=True)
    for suffix in ['png','svg']:fig.savefig(out/('burst.'+suffix),dpi=180)
    plt.close(fig)
    b.save(root/'report_manifest.json',dict(source_sha256=b.sha(__file__),input_sha256=b.sha(root/'summary.json'),
        files={str(p.relative_to(root)):b.sha(p) for p in [root/'report.md',*out.iterdir()]}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args();report(args.root)
