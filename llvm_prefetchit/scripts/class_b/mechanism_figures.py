#!/usr/bin/env python3
"""Standalone figures for opcode calibration and clean service effects."""
import argparse
import json
from pathlib import Path

def confirmation(root,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    path=root/'confirmation_evaluation.json'
    if not path.exists():return
    data=json.loads(path.read_text());assert data['complete']
    names={'candidate':'Retargeted T1','thin_by_age':'Age-preserving thinning','aggressive64':'Lower gain threshold'}
    panels=[('e2e','inverse_rps','Throughput speedup',True),('e2e','mean_ms','Mean latency reduction',False),
        ('e2e','p99_ms','p99 latency reduction',False),('e2e','stack_cpu','Whole-stack CPU reduction',False),
        ('pmu','cache:sum:FE_L2','Retired L2 / request reduction',False),
        ('pmu','frontend:sum:ICACHE_DATA_STALL','I-cache data stall / request reduction',False)]
    fig,axes=plt.subplots(2,3,figsize=(14,7),constrained_layout=True)
    for ax,(group,key,title,ratio) in zip(axes.flat,panels):
        for i,arm in enumerate(names):
            row=data[group][arm]['base'][key]
            point=row['speedup'] if ratio else row['cost_reduction_pct']
            ci=row['speedup_ci95'] if ratio else row['ci95_pct']
            error=[[max(0,point-ci[0])],[max(0,ci[1]-point)]] if ci else None
            ax.errorbar(point,i,xerr=error,fmt='o',capsize=3,color=f'C{i}')
            ax.annotate(f'{point:.4f}×' if ratio else f'{point:+.2f}%',(point,i),xytext=(0,9),textcoords='offset points',ha='center',fontsize=8)
        ax.set_yticks(range(len(names)),names.values());ax.set_ylim(len(names)-.5,-.7)
        ax.axvline(1 if ratio else 0,color='#777',linewidth=.7)
        ax.set_title(title,fontsize=10);ax.set_xlabel('versus original'+('' if ratio else ' (%)'))
        ax.grid(axis='x',alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Fresh-stack Media C4: four independent workload seeds, equal data age')
    fig.supxlabel('Individual paired-log 95% t intervals; exploratory refinements, no multiplicity correction.\n'
        '60-second clean ROI after 50-second warmup. Separate PMU windows; no performance-based run exclusions.',fontsize=9)
    out.mkdir(parents=True,exist_ok=True)
    for ext in ['png','svg']:fig.savefig(out/('fresh_confirmation.'+ext),dpi=180)
    plt.close(fig)

def whole_stack(root,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    path=root/'stack_frontend/result.json'
    if not path.exists():return
    data=json.loads(path.read_text());costs=data['costs']
    names=sorted(costs,key=lambda n:costs[n]['cpu_us_per_request'],reverse=True)[:12]
    labels=[n.removesuffix('-service').replace('compose-review','ComposeReview').replace('movie-id','MovieId') for n in names]
    fig,axes=plt.subplots(1,2,figsize=(12,6),constrained_layout=True)
    user=[costs[n]['user_us']/costs[n]['completed'] for n in names]
    kernel=[costs[n]['system_us']/costs[n]['completed'] for n in names]
    axes[0].barh(range(len(names)),user,color='#277da8',label='User CPU')
    axes[0].barh(range(len(names)),kernel,left=user,color='#a7bdce',label='Kernel CPU')
    fe={r['service']:r['per_request']['FE_L2'] for r in data['windows'] if r['label']=='cache'}
    axes[1].barh(range(len(names)),[fe.get(n,0) for n in names],color=['#d47739' if n.endswith('-mongodb') else '#479483' for n in names])
    for ax in axes:
        ax.set_yticks(range(len(names)),labels);ax.invert_yaxis();ax.grid(axis='x',alpha=.2);ax.spines[['top','right']].set_visible(False)
    axes[0].set_xlabel('CPU µs / request, clean ROI');axes[0].legend(frameon=False)
    axes[1].set_xlabel('Retired L2 events / request, separate PMU windows')
    fig.suptitle('Whole-stack attribution identifies additional instruction-prefetch targets')
    fig.supxlabel('One original-baseline diagnostic; PMU services are sampled sequentially at different workload ages.\n'
        'These bars do not establish causal speedup or a simultaneous global miss fraction.',fontsize=9)
    out.mkdir(parents=True,exist_ok=True)
    for ext in ['png','svg']:fig.savefig(out/('whole_stack.'+ext),dpi=180)
    plt.close(fig)

def plot(root,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=json.loads((root/'probe_summary.json').read_text())['rows']
    rows=[r for r in rows if r['experiment']=='probe_fixed' and r['demand']==1]
    fig,axes=plt.subplots(1,3,figsize=(12.6,4.3),constrained_layout=True)
    names=['NOP','IT0','IT1','T1'];kinds=['nop','it0','it1','t1']
    for mode,color,label in [(2,'#6b7b8c','Target-only flush'),(5,'#16877e','Target flush + 64 KiB code pad')]:
        values={r['kind']:r for r in rows if r['flush']==mode}
        offset=-.18 if mode==2 else .18
        for ax,field,title in zip(axes,['mean_call_tsc','FE_L2','L2I'],
            ['Serialized call time (TSC ticks)','Retired L2 events / iteration','L2 code-read misses / iteration']):
            data=[values[k][field] if field=='mean_call_tsc' else values[k]['events_per_iteration'][field] for k in kinds]
            ax.bar([i+offset for i in range(4)],data,width=.34,color=color,label=label)
            ax.set_title(title,fontsize=11);ax.set_xticks(range(4),names);ax.grid(axis='y',alpha=.2)
            ax.spines[['top','right']].set_visible(False)
    axes[0].legend(frameon=False,fontsize=8)
    fig.suptitle('Identical hint address and code layout: three repeats, 100,000 iterations each')
    fig.supxlabel('Synthetic calibration, not application speedup. Only the seven hint bytes differ.\n'
                  'All cases flush the target, serialize with CPUID, and use 64 dependent IMUL iterations before the call.',fontsize=9)
    out.mkdir(parents=True,exist_ok=True)
    for ext in ['png','svg']:fig.savefig(out/('calibration.'+ext),dpi=180)
    plt.close(fig)
    datasets=[('screen_evaluation.json','selected_it0','IT0'),('screen_evaluation.json','selected_t1','T1')]
    if (root/'retarget_screen_evaluation.json').exists():datasets.append(('retarget_screen_evaluation.json','retarget_t1','Retargeted T1'))
    fig,axes=plt.subplots(1,2,figsize=(11.7,4.5),constrained_layout=True)
    for index,(file,arm,label) in enumerate(datasets):
        data=json.loads((root/file).read_text());control='base';offset=(index-(len(datasets)-1)/2)*.22
        e=data['e2e'][arm][control];p=data['pmu'][arm][control]
        vals=[100*(e['inverse_rps']['speedup']-1),e['mean_ms']['cost_reduction_pct'],e['p99_ms']['cost_reduction_pct'],e['stack_cpu']['cost_reduction_pct']]
        axes[0].barh([i+offset for i in range(4)],vals,height=.2,label=label)
        vals=[p[k]['cost_reduction_pct'] for k in ['cache:sum:FE_L2','cache:sum:L2I','frontend:sum:ICACHE_DATA_STALL','frontend:sum:FE_L1']]
        axes[1].barh([i+offset for i in range(4)],vals,height=.2,label=label)
    axes[0].set_yticks(range(4),['Throughput gain','Mean latency reduction','p99 latency reduction','Whole-stack CPU reduction'])
    axes[1].set_yticks(range(4),['Retired L2 / request','L2 code-read miss / request','I-cache data stall / request','Retired L1I / request'])
    for ax in axes:
        ax.axvline(0,color='#444',linewidth=.8);ax.set_xlabel('Improvement versus original (%)');ax.invert_yaxis()
        ax.grid(axis='x',alpha=.2);ax.spines[['top','right']].set_visible(False)
    axes[0].legend(frameon=False,fontsize=8)
    fig.suptitle('Media C4: clean end-to-end measurements and separate PMU windows')
    fig.supxlabel('Exploratory two-block point estimates; uncertainty intervals are in the report.\n'
                  'Opcode and retarget screens use different seeds and are not pooled.',fontsize=9)
    for ext in ['png','svg']:fig.savefig(out/('service_effects.'+ext),dpi=180)
    plt.close(fig)
    if not (root/'crossover_evaluation.json').exists():return
    data=json.loads((root/'crossover_evaluation.json').read_text())
    if not data.get('e2e_causal_usable',True) or (root/'crossover_nonstationarity.json').exists():
        values=json.loads((root/'crossover/00/result.json').read_text())['rows']
        zero=values[0]['pool']['start']
        times=[((r['pool']['start']+r['pool']['end'])/2-zero)/60 for r in values]
        fig,axes=plt.subplots(1,2,figsize=(11,4.4),constrained_layout=True)
        axes[0].plot(times,[r['pool']['achieved_rps'] for r in values],'o-',color='#31688e')
        for t,r in zip(times,values):
            if r['arm']=='nop':axes[0].annotate('Same NOP',(t,r['pool']['achieved_rps']),xytext=(0,12),textcoords='offset points',ha='center',fontsize=9)
        axes[0].set_ylabel('Throughput (requests / second)')
        for names,label in [(['user-review-mongodb','movie-review-mongodb'],'Two review MongoDBs'),
            (['movie-id-service','compose-review-service','rating-service'],'Three modified services')]:
            axes[1].plot(times,[sum(r['services'][n]['cpu_us_per_request'] for n in names) for r in values],'o-',label=label)
        axes[1].set_ylabel('CPU µs / request');axes[1].legend(frameon=False,fontsize=9)
        for ax in axes:ax.set_xlabel('Minutes since first clean interval');ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
        fig.suptitle('Long same-stack writes grow review arrays: rejected for policy E2E attribution')
        fig.supxlabel('All 12 completed intervals retained. Different hint policies occur along this timeline.\n'
            'The repeated NOP endpoints expose workload drift; fresh-stack validation controls workload age.',fontsize=9)
        for ext in ['png','svg']:fig.savefig(out/('write_state_drift.'+ext),dpi=180)
        plt.close(fig)
        return
    names={'t1':'T1 / old targets','retarget':'T1 / retargeted','protected128':'Earlier / 128','protected512':'Earlier / 512','retarget_thin':'Retargeted / thinned'}
    fig,axes=plt.subplots(2,3,figsize=(13,7),constrained_layout=True)
    panels=[('e2e','inverse_rps','Throughput speedup','ratio'),('e2e','mean_ms','Mean latency reduction','pct'),
        ('e2e','p99_ms','p99 latency reduction','pct'),('e2e','stack_cpu','Whole-stack CPU / request reduction','pct'),
        ('pmu','cache:sum:FE_L2','Retired L2 / request reduction','pct'),
        ('pmu','frontend:sum:ICACHE_DATA_STALL','I-cache data stall / request reduction','pct')]
    for ax,(group,key,title,unit) in zip(axes.flat,panels):
        for i,arm in enumerate(names):
            row=data[group][arm]['nop'][key]
            point=row['speedup'] if unit=='ratio' else row['cost_reduction_pct']
            ci=row['speedup_ci95'] if unit=='ratio' else row['ci95_pct']
            error=[[max(0,point-ci[0])],[max(0,ci[1]-point)]] if ci else None
            ax.errorbar(point,i,xerr=error,fmt='o',capsize=3,color=f'C{i}')
        ax.set_yticks(range(len(names)),names.values());ax.invert_yaxis()
        ax.axvline(1 if unit=='ratio' else 0,color='#888',linewidth=.7)
        ax.set_title(title,fontsize=10);ax.set_xlabel('versus same-layout NOP'+(' (%)' if unit=='pct' else ''))
        ax.grid(axis='x',alpha=.2);ax.spines[['top','right']].set_visible(False)
    n=data['absolute']['nop']['stacks']
    fig.suptitle(f'Same-process crossover: {n} independent fresh stacks, two clean intervals per arm / stack')
    fig.supxlabel('Individual paired-log 95% t intervals; exploratory multiple-policy screen.\n'
                  'Original uninstrumented baseline is a separate comparison. Prefetch changes do not alter code size.',fontsize=9)
    for ext in ['png','svg']:fig.savefig(out/('crossover.'+ext),dpi=180)
    plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    plot(a.root,a.out);confirmation(a.root,a.out);whole_stack(a.root,a.out)
