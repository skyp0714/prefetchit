#!/usr/bin/env python3
"""E2E-first summaries of completed backend/opcode or call-path screens."""
import argparse
import json
from pathlib import Path
import statistics
import dense_build as b
from fullset_study import summarize

GROUPS={'native3':['movie','compose','rating'],'review_mongo2':['mongo_user','mongo_movie']}


def report(root):
    data=json.loads((root/'screen_evaluation.json').read_text());assert data['complete']
    protocol=json.loads((root/'screen/protocol.json').read_text())
    control='base' if 'base' in protocol['arms'] else 'original'
    grouped=[]
    for row in data['pmu_rows']:
        metrics={}
        for group,services in GROUPS.items():
            for event in ['FE_L2','L2I','ICACHE_DATA_STALL']:
                metrics[group+':'+event]=sum(row['metrics']['cache:'+service+':'+event] for service in services)
        grouped.append(dict(row,metrics=metrics))
    comparison=summarize(grouped,protocol['arms'])
    result=dict(control=control,trials=data['trials'],groups=GROUPS,pmu=comparison,rows=grouped,
        limitation='Service sums combine separate PMU windows, normalized by each window\'s completed requests. They are not simultaneous global miss fractions.')
    b.save(root/'grouped_pmu.json',result)
    def pct(row):
        ci=row['ci95_pct']
        return f"{row['cost_reduction_pct']:+.3f}%"+(f" [{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else '')
    lines=['# Fresh-stack backend screen','',f"{data['trials']} valid fresh-stack trials. Control: `{control}`. Individual paired-log 95% t intervals; exploratory comparisons without multiplicity correction.",
        '', '| Policy / control | Throughput speedup [95% CI] | Mean latency reduction | p99 reduction | Whole-stack CPU reduction |',
        '|---|---:|---:|---:|---:|']
    for arm,controls in data['e2e'].items():
        for against,metrics in controls.items():
            r=metrics['inverse_rps'];ci=r['speedup_ci95']
            speed=f"{r['speedup']:.5f}×"+(f" [{ci[0]:.5f}, {ci[1]:.5f}]" if ci else '')
            lines.append(f"| {arm} / {against} | {speed} | {pct(metrics['mean_ms'])} | {pct(metrics['p99_ms'])} | {pct(metrics['stack_cpu'])} |")
    lines += ['', '| Policy / control | Native-3 retired L2 reduction | Review-Mongo-2 retired L2 reduction | Review-Mongo-2 code-read miss reduction | Review-Mongo-2 I-cache data-stall reduction |',
        '|---|---:|---:|---:|---:|']
    for arm,controls in comparison.items():
        for against,metrics in controls.items():
            fields=['native3:FE_L2','review_mongo2:FE_L2','review_mongo2:L2I','review_mongo2:ICACHE_DATA_STALL']
            lines.append('| '+arm+' / '+against+' | '+' | '.join(pct(metrics[k]) for k in fields)+' |')
    lines += ['',result['limitation'],'', 'Clean E2E precedes all PMU windows. Equal initial data and warmup/ROI duration do not imply identical completed request counts.']
    (root/'screen_report.md').write_text('\n'.join(lines)+'\n')
    return data,result


def plot(root,data,groups):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    control=groups['control']
    names=[a for a,c in data['e2e'].items() if control in c]
    panels=[('e2e','inverse_rps','Throughput speedup',True),('e2e','mean_ms','Mean latency reduction',False),
        ('e2e','p99_ms','p99 latency reduction',False),('e2e','stack_cpu','Whole-stack CPU reduction',False),
        ('group','review_mongo2:FE_L2','Review MongoDB retired L2 reduction',False),
        ('group','review_mongo2:ICACHE_DATA_STALL','Review MongoDB I-cache stall reduction',False)]
    fig,axes=plt.subplots(2,3,figsize=(15,8.5),constrained_layout=True)
    for ax,(kind,key,title,ratio) in zip(axes.flat,panels):
        for i,arm in enumerate(names):
            row=(data['e2e'] if kind=='e2e' else groups['pmu'])[arm][control][key]
            value=row['speedup'] if ratio else row['cost_reduction_pct']
            ci=row['speedup_ci95'] if ratio else row['ci95_pct']
            error=[[max(0,value-ci[0])],[max(0,ci[1]-value)]] if ci else None
            ax.errorbar(value,i,xerr=error,fmt='o',capsize=3,color=f'C{i}')
            ax.annotate(f'{value:.4f}×' if ratio else f'{value:+.2f}%',(value,i),xytext=(0,8),textcoords='offset points',ha='center',fontsize=8)
        ax.set_yticks(range(len(names)),names);ax.set_ylim(len(names)-.5,-.65)
        ax.axvline(1 if ratio else 0,color='#777',linewidth=.7);ax.grid(axis='x',alpha=.2)
        ax.spines[['top','right']].set_visible(False);ax.set_title(title,fontsize=10)
        ax.set_xlabel('versus '+control+('' if ratio else ' (%)'))
    fig.suptitle('Full Media C4: fresh stacks, matched warmup and ROI windows')
    fig.supxlabel('Exploratory paired-log 95% intervals; no multiplicity correction. Each PMU service has a separate request denominator.\n'
        'NOP controls retain binding/layout and, for call stubs, the extra direct jump. No E2E claim from miss counts alone.',fontsize=9)
    out=root/'figures';out.mkdir(exist_ok=True)
    for extension in ['png','svg']:fig.savefig(out/('screen.'+extension),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--plot',action='store_true');args=parser.parse_args()
    data,groups=report(args.root)
    if args.plot:plot(args.root,data,groups)
