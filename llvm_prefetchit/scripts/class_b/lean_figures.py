#!/usr/bin/env python3
"""Standalone figures for static inflation and independent E2E confirmation."""
import argparse
import json
from pathlib import Path


def finish(fig,destination):
    import matplotlib.pyplot as plt
    destination.parent.mkdir(parents=True,exist_ok=True)
    for suffix in ('.png','.svg'):fig.savefig(destination.with_suffix(suffix),dpi=180)
    plt.close(fig)


def static(spec,destination):
    import matplotlib.pyplot as plt
    rows=spec['rows'];policies=list(dict.fromkeys(v['policy'] for v in rows))
    services=list(dict.fromkeys(v['service'] for v in rows))
    fig,axes=plt.subplots(1,2,figsize=(13,5.5))
    for service in services:
        values={v['policy']:v for v in rows if v['service']==service}
        for ax,key in zip(axes,('prefetch_instructions','executable_growth_pct')):
            ax.plot(range(len(policies)),[values[p][key] for p in policies],marker='o',label=service)
    for ax in axes:
        ax.set_yscale('log');ax.set_xticks(range(len(policies)),policies,rotation=30,ha='right')
        ax.grid(alpha=.25);ax.legend()
    axes[0].set_ylabel('Static prefetch instructions (log scale)')
    axes[1].set_ylabel('Executable-section growth over original (%) — log scale')
    fig.suptitle('Dominator policies: static injection and code-size reduction')
    fig.text(.5,.01,'Different placement/coverage policies. Lower static size does not establish lower latency.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,.96));finish(fig,destination)


def confirmation(root,destination):
    import matplotlib.pyplot as plt
    datasets={c:json.loads((root/f'confirmation_c{c}/evaluation.json').read_text()) for c in (4,16)}
    assert all(d['independent_confirmation'] and d['rows']==18 for d in datasets.values())
    metrics=['stack_cpu','mean_ms','p99_ms','throughput']
    labels=['CPU / request reduction','Mean latency reduction','p99 latency reduction','Throughput increase']
    rows=[(c,control) for c in datasets for control in ('base','matched_nop')]
    fig,axes=plt.subplots(1,4,figsize=(14,4.5),sharey=True)
    for ax,metric,label in zip(axes,metrics,labels):
        for y,(concurrency,control) in enumerate(rows):
            data=datasets[concurrency]
            value=(data['throughput'] if metric=='throughput' else data['comparisons'])['selected_candidate'][control]
            if metric!='throughput':value=value[metric]
            point=value['gain_pct' if metric=='throughput' else 'cost_reduction_pct']
            lo,hi=value['ci95_pct'];assert lo<=point<=hi
            ax.errorbar(point,y,xerr=[[point-lo],[hi-point]],fmt='o',capsize=4,
                color='#2865a6' if concurrency==4 else '#c5671b')
        ax.axvline(0,color='black',lw=.8)
        if metric=='p99_ms':ax.axvline(-2,color='firebrick',linestyle='--',lw=.8)
        ax.set_title(label);ax.set_xlabel('Paired change (%)');ax.grid(axis='x',alpha=.2)
    axes[0].set_yticks(range(len(rows)),['C%d vs %s'%(c,'original' if a=='base' else 'own NOP') for c,a in rows])
    axes[0].invert_yaxis()
    fig.suptitle('Independent confirmation: six new seed blocks per concurrency')
    fig.text(.5,.01,'Positive is better; bars: individual paired-log t95 intervals. Closed-loop throughput and mean latency are related.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,.95));finish(fig,destination)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['static','confirmation']);parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path);args=parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    if args.action=='static':static(json.loads(args.source.read_text()),args.destination)
    else:confirmation(args.source,args.destination)
