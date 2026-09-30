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
    return dict(slots_per_request=slots,
        **{key+'_slots_per_request': value for key, value in values.items()},
        **{key+'_pct': 100*value/slots for key, value in values.items()})


def aggregate(groups):
    keys = next(iter(groups.values()))['per_request']
    return {key: sum(value['per_request'][key] for value in groups.values()) for key in keys}


def report(root, partial=False):
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
        inputs=inputs, source_sha256=b.sha(__file__), limitation=LIMIT,
        weighting='Each record is normalized by its own completed-request window. Mongo3 sums separately observed request-normalized counters before taking slot ratios. Reported percentages average per-block ratios. CPU-pool and service values overlap; do not add them.')
    name = 'topdown_partial' if partial else 'topdown'
    b.save(root/(name+'.json'), result)
    lines = ['# Split75: frontend versus backend diagnosis', '', LIMIT, '', result['weighting'], '',
        'Clean throughput, mean/p99 latency and whole CPU/request are in report.md. These are separate post-ROI diagnostics.', '',
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
    print(json.dumps(dict(complete=not partial, trials=len(inputs), output=str(root/(name+'.json')))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('root', type=Path); parser.add_argument('--partial', action='store_true')
    args = parser.parse_args(); report(args.root, args.partial)
