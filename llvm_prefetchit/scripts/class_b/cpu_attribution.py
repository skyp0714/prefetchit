#!/usr/bin/env python3
"""Explain E2E CPU cost with the clean ROI's existing cgroup measurements."""
import argparse
import json
from pathlib import Path
import statistics
import dense_build as b

GROUPS={
    'MongoDB 3':{'user-review-mongodb','movie-review-mongodb','review-storage-mongodb'},
    'Native 3':{'movie-id-service','compose-review-service','rating-service'},
    'Nginx':{'nginx-web-server'},'Jaeger':{'jaeger'}}
LIMIT=('Clean-ROI cgroup CPU accounting, divided by the same pool completed-request denominator used by whole-stack CPU/request. '
       'User time is not code-miss stall time, an exclusive causal partition, or an achievable speedup bound. '
       'Pool and sequential cgroup snapshots have different accounting boundaries; do not interpret their difference as prefetch overhead. '
       'Tables average per-trial statistics; p99 is not pooled across requests.')


def analyze(root,plot=False,destination=None):
    assert (root/'screen/complete.json').exists();b.space(root)
    destination=Path(destination) if destination is not None else root
    destination.mkdir(parents=True,exist_ok=True)
    rows=json.loads((root/'screen/rows.json').read_text());records=[]
    for row in rows:
        path=Path(row['output'])/'result.json';result=json.loads(path.read_text());assert result['valid']
        groups={name:dict(cpu=0,user=0,kernel=0) for name in [*GROUPS,'Other']}
        denominator=result['pool']['completed']
        for name,cost in result['all_services'].items():
            group=next((key for key,services in GROUPS.items() if name in services),'Other')
            for field,source in [('cpu','cpu_us'),('user','user_us'),('kernel','system_us')]:
                groups[group][field]+=cost[source]/denominator
        whole=sum(group['cpu'] for group in groups.values())
        assert abs(whole-result['whole_stack_cpu_us_per_request'])<1e-6
        records.append(dict(block=row['block'],arm=row['arm'],groups=groups,whole=whole,
            rps=result['pool']['achieved_rps'],mean_ms=result['pool']['mean_ms'],p99_ms=result['pool']['p99_ms'],
            pool_cpu=result['pool']['cpu_us']/denominator,pool_util_pct=result['pool_util_pct'],source=str(path),sha256=b.sha(path)))
    def describe(values):
        mean=statistics.mean(values)
        return dict(mean=mean,range=[min(values),max(values)],cv_pct=100*statistics.stdev(values)/mean if len(values)>1 and mean else None)
    aggregate={}
    for arm in dict.fromkeys(row['arm'] for row in records):
        selected=[row for row in records if row['arm']==arm]
        aggregate[arm]=dict(trials=len(selected),groups={group:{key:describe([row['groups'][group][key] for row in selected])
            for key in ['cpu','user','kernel']} for group in groups},
            **{key:describe([row[key] for row in selected]) for key in ['whole','rps','mean_ms','p99_ms','pool_cpu','pool_util_pct']})
    control='original' if 'original' in aggregate else 'base'
    base=aggregate[control]
    share=100*sum(base['groups'][group]['user']['mean'] for group in ['MongoDB 3','Native 3'])/base['whole']['mean']
    output=dict(control=control,rows=records,arms=aggregate,native3_and_mongo3_baseline_user_time_share_pct=share,
        source_sha256=b.sha(__file__),limitation=LIMIT)
    b.save(destination/'cpu_attribution.json',output)
    lines=['# Clean-ROI CPU accounting and request performance','',
        '| Arm | RPS | Mean ms | p99 ms | Whole CPU µs/request | Pool CPU µs/request | Pool util % |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for arm,record in aggregate.items():
        lines.append('| '+arm+' | '+' | '.join(f'{record[key]["mean"]:.3f}' for key in ['rps','mean_ms','p99_ms','whole','pool_cpu','pool_util_pct'])+' |')
    lines += ['','| Arm / scope | Total CPU µs/request | User µs/request | Kernel µs/request |','|---|---:|---:|---:|']
    for arm,record in aggregate.items():
        for group,values in record['groups'].items():
            lines.append('| '+arm+' / '+group+' | '+' | '.join(f'{values[key]["mean"]:.3f}' for key in ['cpu','user','kernel'])+' |')
    lines += ['',f'Original Native-3 plus Mongo-3 user time: {share:.2f}% of whole-stack CPU time. This includes all user work, not just frontend stalls.','',LIMIT]
    (destination/'cpu_attribution.md').write_text('\n'.join(lines)+'\n')
    if plot:figure(destination,output)
    return output


def figure(root,data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    arms=data['arms'];names=list(arms);control=data['control'];groups=list(next(iter(arms.values()))['groups'])
    fig,axes=plt.subplots(1,2,figsize=(12,max(4,1+.55*len(names))),gridspec_kw={'width_ratios':[1.7,1]},constrained_layout=True)
    left=[0.]*len(names)
    colors=['#4477aa','#66ccee','#228833','#ccbb44','#bbbbbb']
    for group,color in zip(groups,colors):
        values=[arms[name]['groups'][group]['cpu']['mean'] for name in names]
        axes[0].barh(range(len(names)),values,left=left,label=group,color=color)
        left=[a+z for a,z in zip(left,values)]
    axes[0].set_yticks(range(len(names)),names);axes[0].invert_yaxis();axes[0].set_xlabel('Whole-stack CPU (µs / request)')
    axes[0].legend(ncol=3,fontsize=8,loc='lower left',bbox_to_anchor=(0,1.01));axes[0].grid(axis='x',alpha=.2)
    means=[arms[name]['rps']['mean'] for name in names]
    axes[1].errorbar(means,range(len(names)),xerr=[[mean-arms[name]['rps']['range'][0] for name,mean in zip(names,means)],
        [arms[name]['rps']['range'][1]-mean for name,mean in zip(names,means)]],fmt='o',color='#334455',capsize=3)
    axes[1].set_yticks(range(len(names)),['']*len(names));axes[1].invert_yaxis();axes[1].set_xlabel('Throughput (RPS), mean and trial range')
    axes[1].axvline(arms[control]['rps']['mean'],color='#777777',linestyle=':',label='Original mean')
    axes[1].legend(fontsize=8,loc='lower left',bbox_to_anchor=(0,1.01));axes[1].grid(axis='x',alpha=.2)
    for axis in axes:axis.spines[['top','right']].set_visible(False)
    fig.suptitle('CPU savings and request throughput are separate measurements')
    fig.supxlabel('Fresh stacks, clean ROI before PMU. CPU components are accounting scopes, not exclusive stall causes.\n'
        'The adjacent report includes mean/p99 latency and paired E2E confidence intervals.',fontsize=8)
    out=root/'figures';out.mkdir(exist_ok=True)
    for extension in ['png','svg']:fig.savefig(out/('cpu_attribution.'+extension),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--plot',action='store_true');p.add_argument('--out',type=Path)
    a=p.parse_args();analyze(a.root,a.plot,a.out)
