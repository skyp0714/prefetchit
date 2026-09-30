#!/usr/bin/env python3
"""Keep slot fractions, absolute work, and whole-request performance separate."""
import argparse
import json
from pathlib import Path
import statistics
import dense_build as b
from fullset_study import summarize
from split_hybrid_study import MONITORED, LIMIT


def td(c, privilege):
    slots = c['slots:'+privilege]
    values = {key: c['topdown-'+key+':'+privilege] for key in
        ['retiring', 'bad-spec', 'fe-bound', 'be-bound', 'fetch-lat', 'mem-bound']}
    values['fetch-bw'] = max(0, values['fe-bound']-values['fetch-lat'])
    values['core-bound'] = max(0, values['be-bound']-values['mem-bound'])
    closure = sum(values[key] for key in ['retiring','bad-spec','fe-bound','be-bound'])/slots-1
    return dict(slots_per_request=slots, closure_error_pct=100*closure,
        **{key+'_slots_per_request': value for key, value in values.items()},
        **{key+'_pct': 100*value/slots for key, value in values.items()})


def aggregate(groups):
    keys = next(iter(groups.values()))['per_request']
    return {key: sum(value['per_request'][key] for value in groups.values()) for key in keys}


def report(root, partial=False, plot=False):
    screen = root/'screen'; protocol = json.loads((screen/'protocol.json').read_text())
    if not partial: assert (root/'complete.json').exists()
    records = []; inputs = {}
    for row in json.loads((screen/'rows.json').read_text()):
        path = Path(row['output'])/'result.json'; inputs[str(path)] = b.sha(path)
        result = json.loads(path.read_text()); assert result['valid']
        scope_data = {name: ('u', result['pmu_extra']['topdown'][name]['per_request'],
            result['pmu_extra']['memory'][name]['per_request']) for name in MONITORED}
        scope_data['mongo3'] = ('u', aggregate(result['pmu_extra']['topdown']), aggregate(result['pmu_extra']['memory']))
        for p in ['u', 'k']:
            scope_data['pool_'+p] = (p, result['pool_pmu']['topdown'][p]['per_request'],
                result['pool_pmu']['memory'][p]['per_request'])
        for scope, (privilege, top, mem) in scope_data.items():
            values = td(top, privilege)
            values.update({name+'_cycles_per_request': mem[name] for name in
                ['EXE_STALL', 'LOAD_L1D_STALL', 'LOAD_L3_STALL', 'STORE_STALL']})
            values['memory_window_cycles_per_request'] = mem['cycles:'+privilege]
            records.append(dict(block=row['block'], arm=row['arm'], scope=scope, valid=True, metrics=values))
    absolute = {}; comparisons = {}
    for scope in [*MONITORED, 'mongo3', 'pool_u', 'pool_k']:
        scoped = [row for row in records if row['scope'] == scope]
        comparisons[scope] = summarize(scoped, protocol['arms'])
        absolute[scope] = {}
        for arm in protocol['arms']:
            matching = [row for row in scoped if row['arm'] == arm]
            if not matching: continue
            absolute[scope][arm] = {key: statistics.mean(row['metrics'][key] for row in matching)
                for key in matching[0]['metrics']}
    result = dict(complete=not partial, records=records, absolute=absolute, comparisons=comparisons,
        max_abs_closure_error_pct=max(abs(row['metrics']['closure_error_pct']) for row in records),
        inputs=inputs, source_sha256=b.sha(__file__), limitation=LIMIT,
        weighting='Each record is normalized by its own completed-request window. Mongo3 sums separately observed request-normalized counters before taking slot ratios. Reported percentages average per-block ratios. CPU-pool and service values overlap; do not add them.')
    name = 'topdown_partial' if partial else 'topdown'
    b.save(root/(name+'.json'), result)
    lines = ['# Split75: frontend versus backend diagnosis', '', LIMIT, '', result['weighting'], '',
        'Clean throughput, mean/p99 latency and whole CPU/request are in report.md. These are separate post-ROI diagnostics.', '',
        f'Maximum absolute raw level-1 closure error: {result["max_abs_closure_error_pct"]:.3f}% of slots. Raw values are retained, without forcing the sum to 100%. Hardware metrics use 8-bit fractions and kernel accounting clamps negative fraction-derived deltas; tiny differences below this precision should not be interpreted.', '',
        '| Scope / policy | Retiring | Bad speculation | Frontend | Fetch latency | Fetch bandwidth | Backend | Memory bound | Core bound |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    fields = ['retiring', 'bad-spec', 'fe-bound', 'fetch-lat', 'fetch-bw', 'be-bound', 'mem-bound', 'core-bound']
    for scope in ['mongo3', 'pool_u', 'pool_k']:
        for arm, values in absolute[scope].items():
            lines.append('| '+scope+' / '+arm+' | '+' | '.join(f'{values[key+"_pct"]:.3f}%' for key in fields)+' |')
    lines += ['', '| Scope / policy | FE slots/request | BE slots/request | Execution-stall cycles/request | L1D-load stall | L3-load stall | Store stall |',
        '|---|---:|---:|---:|---:|---:|---:|']
    fields = ['fe-bound_slots_per_request', 'be-bound_slots_per_request', 'EXE_STALL_cycles_per_request',
              'LOAD_L1D_STALL_cycles_per_request', 'LOAD_L3_STALL_cycles_per_request', 'STORE_STALL_cycles_per_request']
    for scope in ['mongo3', 'pool_u', 'pool_k']:
        for arm, values in absolute[scope].items():
            lines.append('| '+scope+' / '+arm+' | '+' | '.join(f'{values[key]:,.1f}' for key in fields)+' |')
    lines += ['', 'Level-2 percentages are subsets: do not add them to their level-1 parent. Fetch latency is not a measurement of prefetch lead time. Memory stall counters may overlap frontend starvation. A changing percentage alone does not establish that absolute backend cost grew. Controlled timing/placement changes are required to test insufficient lead.', '',
        'Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/) and [Intel top-down method](https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-0/top-down-microarchitecture-analysis-method.html).']
    (root/(name+'.md')).write_text('\n'.join(lines)+'\n')
    if plot:
        assert not partial
        figure(root,result)
    print(json.dumps(dict(complete=not partial, trials=len(inputs), output=str(root/(name+'.json')))))


def figure(root,data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,3,figsize=(15,8),constrained_layout=True)
    for column,scope in enumerate(['mongo3','pool_u','pool_k']):
        arms=data['absolute'][scope];names=list(arms);left=[0]*len(names)
        for key,color,label in [('retiring','#228833','Retiring'),('bad-spec','#ccbb44','Bad speculation'),
            ('fe-bound','#4477aa','Frontend'),('be-bound','#ee6677','Backend')]:
            values=[arms[name][key+'_pct'] for name in names]
            axes[0,column].barh(range(len(names)),values,left=left,color=color,label=label)
            left=[a+z for a,z in zip(left,values)]
        axes[0,column].set_xlim(0,102);axes[0,column].set_title(scope)
        axes[0,column].set_xlabel('Raw slot fraction (%)')
        for key,offset,color,label in [('fe-bound',-.17,'#4477aa','Frontend'),('be-bound',.17,'#ee6677','Backend')]:
            axes[1,column].barh([i+offset for i in range(len(names))],
                [arms[name][key+'_slots_per_request']/1e6 for name in names],height=.32,color=color,label=label)
        axes[1,column].set_xlabel('Million slots / request')
        for axis in axes[:,column]:
            axis.set_yticks(range(len(names)),names);axis.invert_yaxis();axis.spines[['top','right']].set_visible(False)
            axis.grid(axis='x',alpha=.15)
    axes[0,0].legend(ncol=2,fontsize=8,loc='lower left',bbox_to_anchor=(0,1.02))
    fig.suptitle('Slot fractions and absolute frontend/backend work')
    fig.supxlabel('Post-ROI diagnostics; four trial means. Scopes overlap and must not be added.\n'
        'Raw 8-bit metric accounting is not forced to 100%; slots are not request critical-path time.',fontsize=9)
    dest=root/'figures';dest.mkdir(exist_ok=True)
    for extension in ['png','svg']:fig.savefig(dest/('topdown.'+extension),dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('root', type=Path); parser.add_argument('--partial', action='store_true')
    parser.add_argument('--plot',action='store_true')
    args = parser.parse_args(); report(args.root, args.partial, args.plot)
