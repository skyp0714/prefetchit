#!/usr/bin/env python3
"""Summarize schedule-age diagnostics without mixing them into clean timings."""
import argparse
import json
from pathlib import Path

import dense_build as b


def summarize(root):
    protocol=json.loads((root/'protocol.json').read_text())
    assert json.loads((root/'complete.json').read_text())['trials']==len(protocol['trials'])
    rows=[]
    for index,setting in enumerate(protocol['trials']):
        trial=root/('%02d_%s'%(index,setting['name']))
        complete=json.loads((trial/'complete.json').read_text());assert complete['valid']
        if complete.get('gate_only'):
            data=json.loads((trial/'gate_only.json').read_text())
            for service,value in data['services'].items():
                rows.append(dict(name=setting['name'],concurrency=setting['concurrency'],service=service,
                    period=None,clock=True,counter_build=True,gate_only=True,gate=value['delta'],
                    request_window=data['request_window'],source_sha256=b.sha(trial/'gate_only.json')))
        for capture in complete['captures']:
            path=Path(capture)
            service,period=path.name.rsplit('_p',1)
            timeline=json.loads((path/'timeline.json').read_text())
            overlap=json.loads((path/'target_overlap.json').read_text())
            requests=json.loads((path/'request_window.json').read_text())
            total=sum(v['estimated_events'] for v in timeline['bins'])
            bins=[]
            for value,target in zip(timeline['bins'],overlap['bins'],strict=True):
                assert value['lo_us']==target['lo_us'] and value['hi_us']==target['hi_us']
                events=target.get('estimated_events',0)
                assert value['estimated_events']==events
                main=target.get('main',0)
                bins.append(dict(value,estimated_events_per_request=events/requests['completed_requests'],
                    main_events=main,static_target_line_events=target.get('static_target_line',0),
                    static_target_overlap_pct_of_main=(100*target.get('static_target_line',0)/main
                        if main and overlap['coverage_applicable'] else None)))
            def aggregate(values):
                events=sum(x['estimated_events'] for x in values)
                main=sum(x['main_events'] for x in values)
                target=sum(x['static_target_line_events'] for x in values)
                return dict(estimated_events=events,share_pct=100*events/total,
                    estimated_events_per_request=events/requests['completed_requests'],
                    main_pct=100*main/events if events else None,
                    static_target_overlap_pct_of_main=(100*target/main
                        if main and overlap['coverage_applicable'] else None))
            gate_path=path/'gate_activity.json'
            gate=json.loads(gate_path.read_text())['delta'] if gate_path.exists() else None
            rows.append(dict(name=setting['name'],concurrency=setting['concurrency'],service=service,
                period=int(period),clock=setting.get('clock',True),counter_build=bool(setting.get('gate_stats')),
                quality=timeline['quality'],median_run_us=timeline['median_run_us'],
                p90_run_us=timeline['p90_run_us'],bins=bins,all=aggregate(bins),
                before20=aggregate([v for v in bins if v['lo_us']<20]),
                peak10_20=aggregate([v for v in bins if 10<=v['lo_us']<20]),
                target_lines=overlap['target_lines'],coverage_applicable=overlap['coverage_applicable'],
                request_window=requests,gate=gate,top_unique_functions=overlap['top_unique_functions'],
                source_hashes={name:b.sha(path/name) for name in
                    ('timeline.json','target_overlap.json','request_window.json')}))
    result=dict(rows=rows,protocol_sha256=b.sha(root/'protocol.json'),
        limitations=[
            'PEBS estimates FRONTEND_RETIRED.L2_MISS at retirement, not fetch or all speculative requests.',
            'Schedule age and exposure include kernel return/interrupt time; they are not user-only time.',
            'Request denominators bracket perf startup/teardown; use exposure/switch normalization too.',
            'Each sample period and counter build is reported separately; no E2E latency claims from profiling.',
            'Static target overlap is among residual sampled misses, not original-miss coverage or proof a hint issued.',
            'Gate eligible counts are logical group returns, not individual hardware hints or successful fills.'])
    b.save(root/'timeline_summary.json',result)
    return result


def plot(result, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=[v for v in result['rows'] if not v['counter_build']]
    services=list(dict.fromkeys(v['service'] for v in selected))
    names=list(dict.fromkeys(v['name'] for v in selected))
    periods=sorted(set(v['period'] for v in selected))
    colors=dict(zip(names,plt.get_cmap('tab10').colors))
    styles={p:['-','--',':','-.'][i%4] for i,p in enumerate(periods)}
    fig,axes=plt.subplots(2,len(services),figsize=(4.5*len(services),7),squeeze=False)
    for column,service in enumerate(services):
        for row in (v for v in selected if v['service']==service):
            bins=[v for v in row['bins'] if v['hi_us'] is not None and v['hi_us']<=50]
            edges=[v['lo_us'] for v in bins]+[bins[-1]['hi_us']]
            label='%s, period %d'%(row['name'],row['period'])
            values=[v['estimated_events_per_scheduled_us'] or 0 for v in bins]
            mass=[v['estimated_events_per_1000_switchins']/(v['hi_us']-v['lo_us']) for v in bins]
            for ax,y in zip(axes[:,column],(values,mass)):
                ax.stairs(y,edges,label=label,color=colors[row['name']],linestyle=styles[row['period']])
        axes[0,column].set_title(service)
        for ax in axes[:,column]:
            ax.axvspan(10,20,color='grey',alpha=.1)
            ax.set_xlim(0,50);ax.grid(alpha=.2);ax.set_xlabel('Schedule age (µs)')
        axes[0,column].legend(fontsize=7)
    axes[0,0].set_ylabel('Estimated events / scheduled µs')
    axes[1,0].set_ylabel('Events / 1000 switch-ins / bin µs')
    fig.suptitle('Retired front-end L2 miss distribution — separate diagnostic captures')
    fig.text(.5,.01,'PEBS retirement time; kernel time included. Shaded region: prior 10–20 µs peak. No profiling latency claims.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,.96))
    destination.parent.mkdir(parents=True,exist_ok=True)
    for suffix in ('.png','.svg'):fig.savefig(destination.with_suffix(suffix),dpi=170)
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('--figure',type=Path)
    args=parser.parse_args();result=summarize(args.root)
    if args.figure:plot(result,args.figure)
    print(json.dumps([dict(name=v['name'],service=v['service'],period=v['period'],
        peak10_20=v.get('peak10_20'),gate=v['gate']) for v in result['rows']],indent=2))
