#!/usr/bin/env python3
"""Report gate activity separately from clean hybrid E2E and late-hint PMU."""
import argparse
import json
from pathlib import Path
import statistics
import dense_build as b

SERVICES=['user-review-mongodb','movie-review-mongodb','review-storage-mongodb']
SCOPES=['mongo_user','mongo_movie','mongo_storage']


def gate_rows(path,policy):
    data=json.loads(path.read_text());assert data['valid']
    rows=[]
    for service in SERVICES:
        counts=data['delta'][service]
        assert all(value>=0 for value in counts.values()) and counts['bursts']>0
        # The shared ABI records the start and dense deadline in invariant TSC
        # ticks. Use their difference rather than an assumed core frequency.
        rates={(entry['clock'][0]-entry['clock'][3])/data['window_us']
               for entry in data['after'][service]['active']
               if entry['clock'][0]>entry['clock'][3]}
        assert len(rates)==1 and next(iter(rates))>0
        ticks_per_us=next(iter(rates))
        rows.append(dict(policy=policy,service=service,**counts,
            ticks_per_us=ticks_per_us,
            mean_qualifying_age_us=counts['burst_age_ticks_sum']/counts['bursts']/ticks_per_us,
            early_half_pct=100*counts['early_half_bursts']/counts['bursts'],
            checks_per_completed_request=counts['checks']/data['load']['completed'],
            bursts_per_completed_request=counts['bursts']/data['load']['completed']))
    return rows


def report(root):
    assert (root/'complete.json').exists()
    data=json.loads((root/'screen_evaluation.json').read_text());assert data['complete']
    protocol=json.loads((root/'protocol.json').read_text())
    full=root.parent/'hybrid_service_preflight/diagnostic/result.json'
    if not full.exists():full=root/'diagnostic/result.json'
    sparse=root/'sparse_diagnostic/result.json'
    gates=gate_rows(full,'full')+gate_rows(sparse,'sparse')
    selection=json.loads((root/'sparse/selection.json').read_text())
    events={'late:FE_LATE_SWPF':'late:FE_LATE_SWPF',
            'cache:FE_L2':'cache:FE_L2',
            'cache:L2I':'cache:L2I',
            'cache:ICACHE_DATA_STALL':'cache:ICACHE_DATA_STALL',
            'decode:UNKNOWN_BRANCH_CYCLES':'decode:UNKNOWN_BRANCH_CYCLES'}
    pmu=[]
    for row in data['pmu_rows']:
        values={}
        for name,event in events.items():
            label,counter=event.split(':')
            values[name]=sum(row['metrics'][f'{label}:{scope}:{counter}'] for scope in SCOPES)
        pmu.append(dict(arm=row['arm'],block=row['block'],metrics=values))
    absolute={arm:{event:statistics.mean(row['metrics'][event] for row in pmu if row['arm']==arm)
                   for event in events} for arm in protocol['arms']}
    result=dict(gates=gates,selection=selection,pmu_rows=pmu,pmu_absolute=absolute,
        source_sha256=b.sha(__file__),inputs={str(p):b.sha(p) for p in [full,sparse,root/'screen_evaluation.json',root/'protocol.json']},
        gate_interpretation='Different-seed, counter-instrumented 35-second diagnostic runs, including startup. Attempted gates are not accepted prefetches. Sparse selection used full diagnostic only; its independent verification is not a reselection input. Mean age includes qualifying 0..10us bursts only, not all scheduler switches.',
        pmu_interpretation='Post-ROI, separate request-normalized windows. LATE_SWPF counts overlap of demand misses with instruction-prefetch-triggered fetch; no ratio to FE_L2 from a different window is an accuracy or lateness probability. Zero does not prove timely success, no execution, or an empty fetch queue.')
    b.save(root/'hybrid_diagnostics.json',result)
    lines=['# Switch-age hybrid: endpoint performance and gate mechanism','',
        'Fresh full Media compose-review C4, eight workload CPUs, MovieId included. Individual paired-log t95 intervals; no multiplicity correction. Clean E2E precedes PMU.','',
        '| Policy | RPS | Speedup vs original [95% CI] | Mean ms | p99 ms | Whole CPU us/request |',
        '|---|---:|---:|---:|---:|---:|']
    for arm,values in data['absolute'].items():
        speed='1.00000x (reference)'
        if arm!='original':
            value=data['e2e'][arm]['original']['inverse_rps'];ci=value['speedup_ci95']
            speed=f'{value["speedup"]:.5f}x [{ci[0]:.5f}, {ci[1]:.5f}]'
        e=values['e2e']
        lines.append(f'| {arm} | {values["rps"]:.2f} | {speed} | {e["mean_ms"]:.4f} | {e["p99_ms"]:.4f} | {e["stack_cpu"]:.2f} |')
    lines += ['', '| Diagnostic | Service | Checks/request | Bursts/request | Mean qualifying age us | Fraction under 5us | Late gates | Observed races |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in gates:
        lines.append(f'| {row["policy"]} | {row["service"]} | {row["checks_per_completed_request"]:.2f} | {row["bursts_per_completed_request"]:.3f} | {row["mean_qualifying_age_us"]:.3f} | {row["early_half_pct"]:.2f}% | {row["late"]} | {row["observed_races"]} |')
    lines += ['',result['gate_interpretation'],'',
        f'Sparse selection: {len(selection["selected_groups"])} groups, {selection["selected_calls"]} call sites; {100*selection["retained_burst_fraction"]:.2f}% of first-diagnostic bursts. This retained fraction is not measured cache-miss coverage.','',
        '| Policy / Mongo-3 per request | LATE_SWPF | Retired L2 | Speculative code-read miss | I-cache stall cycles | Unknown-branch cycles |',
        '|---|---:|---:|---:|---:|---:|']
    for arm,values in absolute.items():lines.append('| '+arm+' | '+' | '.join(f'{values[key]:,.3f}' for key in events)+' |')
    lines += ['',result['pmu_interpretation'],'',
        'The kernel publishes the time of incoming-task selection. User-space RIP-relative hints run at the first selected call that observes a new epoch before the deadline; this is not execution of IT0 inside the scheduler. Gate checks, instruction expansion and the module are included in whole-policy E2E comparisons. Exact-layout NOP and early-T1 controls retain their guard costs.']
    (root/'hybrid_diagnostic_report.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    report(parser.parse_args().root)
