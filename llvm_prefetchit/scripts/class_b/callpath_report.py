#!/usr/bin/env python3
"""Connect completed call-path E2E, emission cost, frontend counters and residuals."""
import argparse
import json
from pathlib import Path
import dense_build as b

SERVICES={'mongo_user':'user-review-mongodb','mongo_movie':'movie-review-mongodb',
          'mongo_storage':'review-storage-mongodb'}


def report(root,make_plot=False):
    assert (root/'complete.json').exists()
    evaluation=json.loads((root/'screen_evaluation.json').read_text())
    prepared=json.loads((root/'prepared.json').read_text())
    residual=json.loads((root/'residual_analysis.json').read_text());assert residual['complete']
    records={}
    for arm,absolute in evaluation['absolute'].items():
        services={};pmu=absolute['pmu']
        for service,name in SERVICES.items():
            def value(group,event):return pmu[group+':'+service+':'+event]
            decode_cycles=value('decode','cycles:u')
            dsb=value('decode','DSB_UOPS');mite=value('decode','MITE_UOPS')
            services[name]=dict(
                user_cpu_us_per_request=absolute['service_cpu'][name+':user_us/request'],
                retired_l2_per_request=value('cache','FE_L2'),
                code_read_miss_per_request=value('cache','L2I'),
                icache_stall_cycles_per_request=value('cache','ICACHE_DATA_STALL'),
                itlb_walk_cycles_per_request=value('frontend','ITLB_WALK_ACTIVE'),
                frontend_bound_pct=value('frontend','frontend_bound_pct'),
                t1_t2_instructions_per_request=value('prefetch','T1_T2_EXECUTED'),
                software_prefetch_miss_per_request=value('prefetch','SWPF_MISS'),
                software_prefetch_hit_per_request=value('prefetch','SWPF_HIT'),
                unknown_branch_cycles_per_request=value('decode','UNKNOWN_BRANCH_CYCLES'),
                unknown_branch_cycles_pct=100*value('decode','UNKNOWN_BRANCH_CYCLES')/decode_cycles,
                dsb_uops_per_request=dsb,mite_uops_per_request=mite,
                dsb_share_of_dsb_mite_pct=100*dsb/(dsb+mite))
        records[arm]=services
    limit=('Arm counters are averages of separate service/window request-normalized observations. '
        'The residual capture and heldout baseline use different diagnostic seeds/windows, and their request '
        'normalization brackets perf startup/teardown. No E2E claim or exclusive cause partition follows from '
        'these counters. An observed retired hint is not proof of early issue, accepted request, fill or residency. '
        'Finite LBR history changes with added jumps; absence is not proof that no hint executed.')
    b.save(root/'cause_summary.json',dict(services=records,prepared=prepared,residual=residual,
        source_sha256=b.sha(__file__),evaluation_sha256=b.sha(root/'screen_evaluation.json'),limitation=limit))
    lines=['# Call-path implementation: request performance and remaining misses','',
           'Full paired E2E results: [screen report](screen_report.md).','',
           '| Policy / original | Throughput speedup | Whole-stack CPU reduction | p99 reduction |',
           '|---|---:|---:|---:|']
    for arm in prepared['candidates']:
        for policy in [arm+'_nop',arm]:
            m=evaluation['e2e'][policy]['original'];r=m['inverse_rps'];ci=r['speedup_ci95']
            lines.append(f"| {policy} | {r['speedup']:.5f}× [{ci[0]:.5f}, {ci[1]:.5f}] | {m['stack_cpu']['cost_reduction_pct']:+.3f}% | {m['p99_ms']['cost_reduction_pct']:+.3f}% |")
    lines += ['', '| Arm / MongoDB service | User CPU µs/request | Retired L2/request | I-cache stall cycles/request | T1/T2 instructions/request | Unknown-branch cycles (%) | DSB/(DSB+MITE) (%) |',
              '|---|---:|---:|---:|---:|---:|---:|']
    fields=['user_cpu_us_per_request','retired_l2_per_request','icache_stall_cycles_per_request',
            't1_t2_instructions_per_request','unknown_branch_cycles_pct','dsb_share_of_dsb_mite_pct']
    for arm,services in records.items():
        for name,row in services.items():
            lines.append('| '+arm+' / '+name+' | '+' | '.join(f'{row[key]:.3f}' for key in fields)+' |')
    lines += ['', '| Residual service | Main-image samples | On selected target line | Matching hint observed | Matching hint with retired age ≥512 |',
              '|---|---:|---:|---:|---:|']
    for name,row in residual['records'].items():
        counts=row['counts']
        lines.append('| '+name+' | '+' | '.join(str(counts.get(key,0)) for key in
            ['main_samples','on_selected_target_line','matching_hint_observed','matching_hint_age_ge512'])+' |')
    lines += ['',limit]
    (root/'cause_report.md').write_text('\n'.join(lines)+'\n')
    if not make_plot:return
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,len(residual['records']),figsize=(13,4.5),squeeze=False,constrained_layout=True)
    for ax,(name,row) in zip(axes.flat,residual['records'].items()):
        source=[row['baseline_heldout']['estimated_events_per_request'],row['estimated_events_per_request']]
        selected=[v['on_selected_target_line'] for v in source]
        other=[v['main_samples']-v['on_selected_target_line'] for v in source]
        ax.bar([0,1],selected,label='Selected target line',color='#357aa5')
        ax.bar([0,1],other,bottom=selected,label='Other main-image line',color='#b7c7d4')
        ax.set_xticks([0,1],['Original heldout','Patched residual']);ax.set_title(name,fontsize=10)
        ax.set_ylabel('Estimated retired L2 events / request');ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='y',alpha=.2)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Where misses remain after call-path prefetch')
    fig.supxlabel('Separate diagnostic captures and seeds; no E2E inference. Bar colors describe target addresses, not verified hint execution.',fontsize=9)
    out=root/'figures';out.mkdir(exist_ok=True)
    for extension in ['png','svg']:fig.savefig(out/('residual.'+extension),dpi=180)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--plot',action='store_true');a=p.parse_args();report(a.root,a.plot)
