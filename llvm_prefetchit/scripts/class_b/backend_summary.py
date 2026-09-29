#!/usr/bin/env python3
"""E2E-first summaries of completed backend/opcode or call-path screens."""
import argparse
import gzip
import json
from pathlib import Path
import statistics
import dense_build as b
from fullset_study import summarize

GROUPS={'native3':['movie','compose','rating'],
        'review_mongo2':['mongo_user','mongo_movie'],
        'mongo3':['mongo_user','mongo_movie','mongo_storage']}


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
    ages=[]
    for row in json.loads((root/'screen/rows.json').read_text()):
        folder=Path(row['output']);measurement=json.loads((folder/'result.json').read_text())
        pool=measurement['pool']
        before=measurement.get('completed_before_roi')
        raw=folder/'load/requests.json.gz'
        if before is None and raw.exists():
            with gzip.open(raw,'rt') as stream:requests=json.load(stream)
            before=sum(finished<pool['start'] for _,finished in requests)
        ages.append(dict(arm=row['arm'],block=row['block'],roi_begin_epoch=pool['start'],roi_end_epoch=pool['end'],
            completed_before_roi=before,roi_completed=pool['completed'],
            rps=row['achieved_rps'],cpu=row['metrics']['stack_cpu'],mean_ms=row['metrics']['mean_ms'],p99_ms=row['metrics']['p99_ms']))
    b.save(root/'workload_age.json',dict(rows=ages,
        limitation='Fresh initial data and fixed warmup duration. Faster closed-loop arms can complete more writes before ROI; counts are retained when available. Null means older runs compacted raw timestamps before this field was added, not zero or equal writes.'))
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
    lines += ['', '| Policy / control | Three MongoDBs retired L2 reduction | Three MongoDBs code-read miss reduction | Three MongoDBs I-cache data-stall reduction |',
        '|---|---:|---:|---:|']
    for arm,controls in comparison.items():
        for against,metrics in controls.items():
            fields=['mongo3:'+event for event in ['FE_L2','L2I','ICACHE_DATA_STALL']]
            lines.append('| '+arm+' / '+against+' | '+' | '.join(pct(metrics[k]) for k in fields)+' |')
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
    trial_order_plot(root)


def wake_report(root,make_plot=False):
    paths=sorted((root/'timeline').glob('*_p*/timeline.json'))
    if not paths:return
    records=[]
    for path in paths:
        data=json.loads(path.read_text());bins=data['bins']
        service,period=path.parent.name.rsplit('_p',1)
        requests=json.loads((path.parent/'request_window.json').read_text())
        records.append(dict(service=service,period=int(period),quality=data['quality'],bins=bins,
            source_sha256=b.sha(path),request_window=requests,
            share_10_20_pct=sum(row['event_share_pct'] for row in bins if 10<=row['lo_us']<20),
            share_50_200_pct=sum(row['event_share_pct'] for row in bins if 50<=row['lo_us']<200),
            density_peak=max(bins,key=lambda row:row['estimated_events_per_scheduled_us'])))
    b.save(root/'wake_summary.json',dict(records=records,
        limitation='Original MongoDB diagnostic only. Sample periods check directional stability; they are not statistical replicates or confidence intervals. Switch age includes kernel return/interrupt time and is not hint-to-fetch lead.'))
    if not make_plot:return
    import matplotlib.pyplot as plt
    services=list(dict.fromkeys(row['service'] for row in records))
    fig,axes=plt.subplots(len(services),2,figsize=(11,3.6*len(services)),squeeze=False,constrained_layout=True)
    for i,service in enumerate(services):
        for row in records:
            if row['service']!=service:continue
            finite=[b for b in row['bins'] if b['hi_us'] is not None and b['lo_us']<500]
            label='period '+str(row['period'])
            axes[i,0].stairs([b['estimated_events_per_scheduled_us'] for b in finite],
                [b['lo_us'] for b in finite]+[finite[-1]['hi_us']],label=label)
            axes[i,1].plot([b['hi_us'] for b in finite],[b['cumulative_pct'] for b in finite],marker='.',label=label)
        for ax in axes[i]:
            ax.set_title(service);ax.set_xlabel('Time since switch-in (µs)');ax.grid(alpha=.2)
            ax.spines[['top','right']].set_visible(False);ax.axvspan(10,20,color='#999',alpha=.15)
        axes[i,0].set_xlim(0,250);axes[i,0].set_ylabel('Estimated events / scheduled µs');axes[i,0].legend()
        axes[i,1].set_xscale('log');axes[i,1].set_xlim(1,500);axes[i,1].set_ylim(0,100);axes[i,1].set_ylabel('Cumulative event share (%)')
    fig.suptitle('MongoDB miss timing extends beyond the native-service 10–20 µs peak')
    fig.supxlabel('Original code; separate diagnostic captures. Shading: 10–20 µs. Retirement age is not issue-to-fetch lead.',fontsize=9)
    out=root/'figures';out.mkdir(exist_ok=True)
    for extension in ['png','svg']:fig.savefig(out/('wake.'+extension),dpi=180)
    plt.close(fig)


def trial_order_plot(root):
    import matplotlib.pyplot as plt
    out=root/'figures';out.mkdir(exist_ok=True)
    trials=json.loads((root/'workload_age.json').read_text())['rows']
    ordered=sorted(trials,key=lambda r:r['roi_begin_epoch'])
    colors={name:plt.get_cmap('tab10')(i) for i,name in enumerate(dict.fromkeys(r['arm'] for r in ordered))}
    fig,axes=plt.subplots(3,1,figsize=(12,8),sharex=True,constrained_layout=True)
    for ax,key,label in zip(axes,['rps','cpu','p99_ms'],['Throughput (RPS)','Whole-stack CPU (µs/request)','p99 latency (ms)']):
        for i,row in enumerate(ordered):
            ax.scatter(i,row[key],color=colors[row['arm']],s=35,zorder=3)
        for block in sorted({row['block'] for row in ordered}):
            indices=[i for i,row in enumerate(ordered) if row['block']==block]
            if block%2:ax.axvspan(min(indices)-.5,max(indices)+.5,color='#789',alpha=.08)
        ax.set_ylabel(label);ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    axes[-1].set_xticks(range(len(ordered)),[f"{row['block']}: {row['arm']}" for row in ordered],rotation=45,ha='right',fontsize=8)
    fig.suptitle('Every clean trial in chronological order')
    fig.supxlabel('Each point starts a fresh stack. Reversed arm order in block 1; no points removed based on performance.\n'
        'Inspect run variation alongside paired estimates; plotted differences alone do not establish policy effects.',fontsize=9)
    for extension in ['png','svg']:fig.savefig(out/('trial_order.'+extension),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--plot',action='store_true');args=parser.parse_args()
    data,groups=report(args.root)
    if args.plot:plot(args.root,data,groups)
    wake_report(args.root,args.plot)
