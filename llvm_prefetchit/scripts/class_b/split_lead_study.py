#!/usr/bin/env python3
"""Frozen follow-up: residual targets versus budgeted earlier placement."""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b
import fullset as h
from fullset_study import summarize
from mechanism_report import evaluate
from split_coverage_campaign import trial_orders
import split_hybrid_study as study
from split_topdown_report import report as topdown_report

L1_EVENTS = ('cycles:u,instructions:u,'
    'cpu/event=0xc6,umask=0x3,config1=0x12,name=FE_L1I/u,'
    'cpu/event=0x61,umask=0x2,name=DSB_SWITCH_STALL/u,'
    'cpu/event=0x80,umask=0x4,cmask=1,edge=1,name=ICACHE_STALL_PERIODS/u,'
    'cpu/event=0x80,umask=0x4,name=ICACHE_DATA_STALL/u')


def trial(spec):
    study.EVENTS['l1'] = L1_EVENTS
    study.trial(spec)


def prepare(root):
    assert (root/'hybrid_screen/complete.json').exists()
    initial = json.loads((root/'prepared_complete.json').read_text())
    residual = json.loads((root/'residual_retarget/complete.json').read_text()); assert residual['valid']
    lead = json.loads((root/'lead512/prepared.json').read_text())
    source = initial['arms']['split75']; base = json.loads(Path(source['mongo_binary']+'.json').read_text())
    assert lead['extra_instruction_bytes'] <= base['extra_instruction_bytes']
    arms = dict(split75=dict(source), residual_t1=dict(source, mongo_binary=residual['binary'], controls=['split75']),
        lead512_nop=dict(source, mongo_binary=lead['nop'], controls=['split75']),
        lead512=dict(source, mongo_binary=lead['binary'], controls=['split75','lead512_nop','residual_t1']))
    arms['split75'].pop('controls', None)
    for value in arms.values(): assert not value.get('hybrid')
    files = [Path(__file__), Path(study.__file__), Path(study.hybrid.__file__),
        Path(study.balanced_backend.__file__), Path(study.backend_study.__file__),
        Path(__file__).with_name('balanced_load.py'), Path(__file__).with_name('dense_causes.py')]
    protocol = dict(arms=arms, control='split75', blocks=4, seedbase=88101,
        orders=trial_orders(list(arms),4), monitored=study.MONITORED,
        source_hashes={str(p):b.sha(p) for p in files},
        binary_hashes={v['mongo_binary']:b.sha(v['mongo_binary']) for v in arms.values()},
        scope='Fresh full Media compose-review C4 including MovieId. 8 workload CPUs, 50s warmup, 60s clean ROI; all PMU follows. Four balanced blocks; no performance-based exclusions or retries. Compare within this campaign only.',
        hypotheses='residual_t1 replaces target displacements using first-half residual observations, with fixed code addresses, per-site hint counts and exact NOP. It changes target coverage rather than layout or total hint emission. lead512 selects >=512 accumulated retired LBR cycles under split75 site/hint budgets; different paths/coverage/emission may confound timing, so its own NOP is included. Neither measures instruction-fetch issue lead directly.',
        selection_sha256=b.sha(root/'residual_retarget/selection_frozen.json'),
        limitation=study.LIMIT)
    stage = root/'lead_screen'; stage.mkdir(exist_ok=False); (stage/'screen').mkdir(); b.space(root)
    protocol['additional_events'] = dict(l1=L1_EVENTS)
    b.run(['perf','stat','-x,','-o',str(stage/'l1_preflight.csv'),'-e',L1_EVENTS,'-a','-C','84',
        '--','taskset','-c','84','python3','-c','sum(i*i for i in range(1000000))'],stage/'l1_preflight.log')
    counts = study.counters(stage/'l1_preflight.csv'); assert counts['fully_scheduled']
    b.save(stage/'l1_preflight.json', counts)
    b.save(stage/'protocol.json', protocol); b.save(stage/'screen/protocol.json', protocol)
    return stage, protocol


def report(stage):
    data = evaluate(stage/'screen', stage/'screen_evaluation.json')
    protocol = json.loads((stage/'protocol.json').read_text())
    lines = ['# Residual targets and earlier placement: fresh full Media C4', '', protocol['scope'], '', protocol['hypotheses'], '',
        '| Arm | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |',
        '|---|---:|---:|---:|---:|---:|']
    for name, v in data['absolute'].items():
        e = v['e2e']; lines.append(f'| {name} | {v["rps"]:.2f} | {e["mean_ms"]:.4f} | {e["p99_ms"]:.4f} | {e["stack_cpu"]:.2f} | {v["util_pct"]:.2f}% |')
    def pct(v):
        ci = v['ci95_pct']; return f'{v["cost_reduction_pct"]:+.3f}% [{ci[0]:+.3f}, {ci[1]:+.3f}]'
    lines += ['', '| Arm / control | Throughput speedup [95% CI] | Mean reduction | p99 reduction | Whole CPU reduction |',
        '|---|---:|---:|---:|---:|']
    for arm, controls in data['e2e'].items():
        for control, v in controls.items():
            speed = v['inverse_rps']; ci = speed['speedup_ci95']
            lines.append(f'| {arm} / {control} | {speed["speedup"]:.5f}x [{ci[0]:.5f}, {ci[1]:.5f}] | '+' | '.join(pct(v[k]) for k in ['mean_ms','p99_ms','stack_cpu'])+' |')
    lines += ['', '| Arm / control | Mongo3 retired L2 reduction | Code-read miss reduction | I-cache stall reduction |',
        '|---|---:|---:|---:|']
    for arm, controls in data['pmu'].items():
        for control, v in controls.items():
            lines.append(f'| {arm} / {control} | '+' | '.join(pct(v['cache:sum:'+k]) for k in ['FE_L2','L2I','ICACHE_DATA_STALL'])+' |')
    lines += ['', '| Arm | Mongo3 retired L1I/request | DSB-to-MITE penalty cycles/request | I-cache stall cycles/request |',
        '|---|---:|---:|---:|']
    for arm, values in data['absolute'].items():
        lines.append('| '+arm+' | '+' | '.join(f'{values["pmu"]["l1:sum:"+key]:,.2f}' for key in
            ['FE_L1I','DSB_SWITCH_STALL','ICACHE_DATA_STALL'])+' |')
    lines += ['', 'L1I and L2 retired-event populations are collected in separate windows. Their ratio is descriptive; subtracting them is not an exclusive critical-path attribution. DSB-switch penalty is not a BTB occupancy measurement.']
    lines += ['', data['interpretation'], '', study.LIMIT]
    (stage/'report.md').write_text('\n'.join(lines)+'\n')
    topdown_report(stage)
    plot(stage, data)


def plot(stage, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names = [name for name, c in data['e2e'].items() if 'split75' in c]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    for axis, key, title in zip(axes, ['inverse_rps','p99_ms','stack_cpu'],
        ['Throughput speedup','p99 latency reduction (%)','Whole CPU reduction (%)']):
        ratio = key == 'inverse_rps'
        for i, name in enumerate(names):
            v = data['e2e'][name]['split75'][key]
            value = v['speedup'] if ratio else v['cost_reduction_pct']
            ci = v['speedup_ci95'] if ratio else v['ci95_pct']
            axis.errorbar(value, i, xerr=[[value-ci[0]],[ci[1]-value]], fmt='o', capsize=3)
        axis.set_yticks(range(len(names)), names); axis.invert_yaxis()
        axis.axvline(1 if ratio else 0, color='#888', linewidth=.8); axis.grid(axis='x', alpha=.2)
        axis.set_title(title); axis.spines[['top','right']].set_visible(False)
    fig.suptitle('Residual targets and earlier placement versus split75: full Media C4')
    fig.supxlabel('Four fresh-stack paired blocks; individual 95% intervals, no multiplicity correction. Endpoint timing precedes PMU.', fontsize=9)
    dest = stage/'figures'; dest.mkdir(exist_ok=True)
    for ext in ['png','svg']: fig.savefig(dest/('lead.'+ext), dpi=180)
    plt.close(fig)


def campaign(root):
    stage, protocol = prepare(root); rows = []
    for block, order in enumerate(protocol['orders']):
        for arm in order:
            b.space(root); out = stage/'screen'/f'{block:02d}_{arm}'; manifest = out.with_suffix('.json')
            assert all(b.sha(p)==sha for p,sha in protocol['source_hashes'].items())
            b.save(manifest, dict(protocol['arms'][arm], out=str(out), seed=protocol['seedbase']+block, reverse_pmu=bool(block%2)))
            h.platform(out, ['python3', Path(__file__), 'trial', manifest])
            r = json.loads((out/'result.json').read_text()); assert r['valid']
            row = dict(block=block, arm=arm, valid=True, output=str(out), achieved_rps=r['pool']['achieved_rps'],
                pool_util_pct=r['pool_util_pct'], metrics=dict(mean_ms=r['pool']['mean_ms'], p99_ms=r['pool']['p99_ms'],
                stack_cpu=r['whole_stack_cpu_us_per_request'], inverse_rps=1/r['pool']['achieved_rps']))
            rows.append(row); b.save(stage/'screen/rows.json', rows)
            b.save(stage/'screen/summary.json', summarize(rows, protocol['arms'])); print(json.dumps(row), flush=True)
    b.save(stage/'screen/complete.json', dict(rows=len(rows)))
    b.save(stage/'complete.json', dict(valid=True, clean_trials=len(rows)))
    report(stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['campaign','report','trial']); parser.add_argument('path', type=Path)
    args = parser.parse_args()
    def interrupted(sig, frame): raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM, interrupted)
    if args.action == 'campaign': campaign(args.path)
    elif args.action == 'trial': trial(json.loads(args.path.read_text()))
    else: report(args.path)
