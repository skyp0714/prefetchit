#!/usr/bin/env python3
"""Compact age distributions and request-normalized before/after figures."""
import argparse
import collections
import json
from pathlib import Path

import dense_build as b
from temporal_path_common import EDGES


def summarize(root):
    rows=[]
    for path in sorted((root/'profiles').glob('*/*/*/timeline.json')):
        data=json.loads(path.read_text());window=json.loads((path.parent/'request_window.json').read_text())
        protocol=json.loads((path.parents[2]/'protocol.json').read_text());n=window['completed_requests']
        total=sum(v['estimated_events'] for v in data['bins'])
        rows.append(dict(run=path.parents[2].name,arm=protocol.get('arm'),phase=protocol.get('phase'),
            service=path.parents[1].name,kind=data['kind'],samples=data['quality']['complete_samples'],
            joined_pct=data['quality']['complete_sample_pct'],period=data['period'],requests=n,
            events_per_request=total/n,median_run_us=data['median_run_us'],
            early20_pct=100*sum(v['estimated_events'] for v in data['bins'] if v['lo_us']<20)/total,
            bins=[dict(v,events_per_request=v['estimated_events']/n) for v in data['bins']],
            origins={key:dict(value,events_per_request=value['estimated_events']/n) for key,value in data['origins'].items()}))
    result=dict(rows=rows,bins_us=EDGES,
        limitation='Separate perturbing diagnostic captures. PEBS retirement age since scheduler selection is not fetch time. Period-weighted/request and scheduled-exposure normalizations are estimates. Never infer clean speedup from these windows.')
    b.save(root/'analysis/temporal_summary.json',result)
    return result


def plot(root,data,phases=None,prefix=''):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    if phases is not None:data=dict(data,rows=[row for row in data['rows'] if row['phase'] in phases])
    assert data['rows'],'No profiles selected for plotting'
    b.save(root/'analysis'/(prefix+'temporal_plot_protocol.json'),dict(phases=phases,
        captures=[dict(run=row['run'],service=row['service'],kind=row['kind']) for row in data['rows']],
        source_sha256=b.sha(__file__),limitation=data['limitation']))
    plt.rcParams.update({'font.size':9,'svg.hashsalt':'class-b-temporal-20261001'})
    services=['movie','compose','rating','unique','text','user','storage','userreview','moviereview','mongo_user','mongo_movie','mongo_storage']
    kinds=[kind for kind in ('l2','lat128','l1') if any(row['kind']==kind for row in data['rows'])]
    arms=sorted({row['arm'] for row in data['rows'] if row['kind'] in kinds},
        key=lambda arm:({'original':0,'mongo':1,'combined':2,'pathwide':3}.get(arm,4),arm))
    colors={arm:plt.get_cmap('tab10')(i) for i,arm in enumerate(arms)}
    for kind,mode in [(kind,mode) for kind in kinds for mode in ('per_request','exposure')]:
        fig,axes=plt.subplots(4,3,figsize=(14,12))
        for service,ax in zip(services,axes.flat):
            limit=500 if service.startswith('mongo_') else 100
            for arm in arms:
                selected=[r for r in data['rows'] if r['kind']==kind and r['service']==service and r['arm']==arm]
                if not selected:continue
                values=[];lows=[];highs=[]
                for i,lo in enumerate(EDGES[:-1]):
                    hi=EDGES[i+1]
                    if hi>limit:break
                    if mode=='per_request':
                        observations=[r['bins'][i]['events_per_request']/(hi-lo) for r in selected]
                    else:
                        observations=[r['bins'][i]['estimated_events']/r['bins'][i]['exposure_us'] if r['bins'][i]['exposure_us'] else 0 for r in selected]
                    values.append(np.mean(observations));lows.append(min(observations));highs.append(max(observations))
                ax.stairs(values,EDGES[:len(values)+1],label=arm,color=colors[arm],linewidth=1.5)
                if len(selected)>1:
                    ax.fill_between(EDGES[:len(values)+1],lows+[lows[-1]],highs+[highs[-1]],step='post',color=colors[arm],alpha=.15)
            ax.axvspan(10,20,color='#999999',alpha=.12);ax.set_title(service);ax.grid(alpha=.2)
            ax.set_xlim(0,limit);ax.set_ylim(bottom=0)
        handles,labels=axes.flat[0].get_legend_handles_labels();fig.legend(handles,labels,loc='upper center',bbox_to_anchor=(.5,.968),ncol=len(labels))
        fig.supxlabel('Sample retirement age after sched_switch selection (µs)',y=.025)
        event={'l2':'Retired L2 misses','l1':'Retired L1I misses','lat128':'Frontend delivery gaps ≥128 cycles'}[kind]
        fig.supylabel(event+(' / request / age-bin µs' if mode=='per_request' else ' / scheduled µs'))
        fig.suptitle('Media before/after prefetch — diagnostic captures; bands show repeat ranges',y=.992)
        fig.text(.5,.005,'Schedules include kernel time; LBR/sample retirement timing is not the instruction-fetch deadline.',ha='center',fontsize=8)
        fig.tight_layout(rect=(.025,.05,1,.95))
        for suffix in ['png','svg']:fig.savefig(root/'analysis'/(prefix+{'l2':'miss','l1':'l1','lat128':'lat128'}[kind]+'_age_'+mode+'.'+suffix),dpi=160)
        plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--plot',action='store_true')
    p.add_argument('--phases',nargs='+');p.add_argument('--prefix',default='');a=p.parse_args()
    assert '/' not in a.prefix and '..' not in a.prefix
    data=summarize(a.root)
    if a.plot:plot(a.root,data,a.phases,a.prefix)
