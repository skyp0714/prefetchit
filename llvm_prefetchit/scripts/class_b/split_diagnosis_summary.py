#!/usr/bin/env python3
"""Join completed diagnostic views without pooling independent campaigns."""
import argparse
import json
from pathlib import Path
import dense_build as b


PMU = {
    'Retired L2': 'cache:sum:FE_L2',
    'L2 code-read miss': 'cache:sum:L2I',
    'I-cache stall cycles': 'cache:sum:ICACHE_DATA_STALL',
    'ITLB walk-active cycles': 'front:sum:ITLB_WALK_ACTIVE',
    'Unknown-branch bubble cycles': 'front:sum:UNKNOWN_BRANCH_CYCLES',
    'Branch mispredictions': 'late:sum:branch-misses:u',
    'DSB uops': 'front:sum:DSB_UOPS',
    'MITE uops': 'front:sum:MITE_UOPS',
    'Retired L1I': 'l1:sum:FE_L1I',
    'DSB-to-MITE penalty cycles': 'l1:sum:DSB_SWITCH_STALL',
    'I-cache stall periods': 'l1:sum:ICACHE_STALL_PERIODS',
    'Late instruction prefetch': 'late:sum:FE_LATE_SWPF',
    'Speculative T1/T2 executions': 'prefetch:sum:T1_T2_EXECUTED',
    'L1D fill-buffer-full cycles': 'prefetch:sum:L1D_FB_FULL',
    'Frontend gaps >=128 cycles': 'lat128:sum:FE_LAT128',
}
SERVICES = {'mongo_user':'user-review-mongodb', 'mongo_movie':'movie-review-mongodb',
            'mongo_storage':'review-storage-mongodb'}
LIMIT = ('Completed campaigns remain separate. PMU windows follow clean endpoint timing; '
         'each has its own request denominator. Different event populations and overlapping '
         'stall counts are not an exclusive causal partition. Retired LBR ages do not measure '
         'prefetch issue-to-fetch lead. Branch-target association does not establish BTB/FDIP '
         'state. Top-down slots are not request critical-path time or an Amdahl bound.')


def report(root):
    inputs = {}
    def read(path):
        inputs[str(path.relative_to(root))] = b.sha(path)
        return json.loads(path.read_text())
    out = root/'diagnosis'; out.mkdir(exist_ok=True)
    lines = ['# Split75: measured frontend components and residual coverage', '', LIMIT]
    summaries = {}
    stages=['hybrid_screen', 'lead_screen']
    for stage in ['confirmation_screen','l1_screen','l1_confirmation_screen','latency_screen']:
        if (root/stage).exists(): stages.append(stage)
    for stage in stages:
        assert read(root/stage/'complete.json')['valid']
        data = read(root/stage/'screen_evaluation.json')
        top = read(root/stage/'topdown.json')
        assert data['complete'] and top['complete']
        arms = list(data['absolute'])
        lines += ['', '## '+stage, '', 'Raw Mongo3 counts/request, arithmetic mean of four trials.', '',
                  '| Event | '+' | '.join(arms)+' |', '|---|'+'---:|'*len(arms)]
        absolute = {}
        for label, key in PMU.items():
            if not all(key in data['absolute'][arm]['pmu'] for arm in arms): continue
            absolute[label] = {arm: data['absolute'][arm]['pmu'][key] for arm in arms}
            lines.append('| '+label+' | '+' | '.join(f'{absolute[label][arm]:,.3f}' for arm in arms)+' |')
        populations = {}
        lines += ['', 'Service MPKI uses retired user instructions from the same counter window. '
            'Speculative code-read requests and retired frontend miss events have different '
            'populations; neither is an exclusive measure of request waiting time. CPU shares '
            'are clean-ROI accounting ratios, not request-critical-path or Amdahl bounds.', '',
            '| Service / policy | Retired L2 MPKI | Code-read MPKI | Service CPU us/request | Share of whole CPU |',
            '|---|---:|---:|---:|---:|']
        for arm in arms:
            values=data['absolute'][arm]
            for short,name in SERVICES.items():
                cpu=values['service_cpu'][name+':cpu_us/request']
                item=dict(retired_l2_mpki=values['pmu']['cache:'+short+':FE_L2/ki'],
                    code_read_mpki=values['pmu']['cache:'+short+':L2I/ki'],
                    cpu_us_per_request=cpu,whole_cpu_share_pct=100*cpu/values['e2e']['stack_cpu'])
                populations[short+'/'+arm]=item
                lines.append('| '+short+' / '+arm+' | '+
                    f'{item["retired_l2_mpki"]:.3f} | {item["code_read_mpki"]:.3f} | '+
                    f'{cpu:.3f} | {item["whole_cpu_share_pct"]:.3f}% |')
        comparisons = {}
        lines += ['', 'Individual paired-log t95 reductions; negative means an increase. No multiplicity correction.', '',
                  '| Policy / control | Event | Reduction [95% CI] |', '|---|---|---:|']
        for arm, controls in data['pmu'].items():
            for control, metrics in controls.items():
                comparisons[arm+'/'+control] = {}
                for label, key in PMU.items():
                    if key not in metrics: continue
                    value = metrics[key]; low, high = value['ci95_pct']
                    comparisons[arm+'/'+control][label] = value
                    lines.append(f'| {arm} / {control} | {label} | {value["cost_reduction_pct"]:+.3f}% [{low:+.3f}, {high:+.3f}] |')
        summaries[stage] = dict(absolute=absolute, comparisons=comparisons, populations=populations,
            mongo_topdown=top['absolute']['mongo3'], e2e=data['e2e'],
            invalid_pmu_windows=data.get('invalid_pmu_windows',[]),
            topdown_valid_trials=top.get('valid_trials'),
            invalid_topdown_records=top.get('invalid_topdown_records',[]))
    modeled = {}
    lines += ['', '## Selected targets among remaining misses', '',
        'Separate PEBS/LBR diagnostics; split instructions use the calibrated continuation-line model. '
        'Static selected-line membership does not prove a hint executed. Missing matching hints may '
        'be outside finite LBR history; observed retirement age is not issue-to-fetch lead.', '',
        '| Policy / service | Main samples | On a selected target line | Matching hint in LBR | Matching hint age >=512 | Split instruction | Added stub |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for arm in ['split75', 'lead512']:
        analysis=read(root/'residual_diagnostics'/arm/'analysis.json')
        assert analysis['complete']
        for service, value in analysis['records'].items():
            counts=value['modeled_counts']; n=counts['main_samples']
            item=dict(main_samples=n,
                selected_line_pct=100*counts['on_selected_target_line']/n,
                matching_hint_pct=100*counts['matching_hint_observed']/n,
                matching_age_ge512_pct=100*counts['matching_hint_age_ge512']/n,
                split_instruction_pct=100*value['spans']['counts']['crosses_64']/n,
                added_stub_pct=100*sum(g['added_stub_samples'] for g in value['locations']['groups'].values())/n)
            modeled[arm+'/'+service]=item
            lines.append('| '+arm+' / '+service+f' | {n:,} | '+' | '.join(f'{item[key]:.3f}%' for key in
                ['selected_line_pct','matching_hint_pct','matching_age_ge512_pct','split_instruction_pct','added_stub_pct'])+' |')
    residual = {}
    lines += ['', '## Residual retired-L2 samples on split75', '',
              'Independent padding train/heldout captures. Denominator: all main-image samples. '
              'A sample near a taken-branch destination is not necessarily a branch instruction.', '',
              '| Capture / service | Main samples | Within 64 B of prior taken target | Prior branch mispredicted | Added prefetch stub | Sample is a branch instruction |',
              '|---|---:|---:|---:|---:|---:|']
    quality = read(root/'padding_residual/profile_quality.json')
    for key, value in quality['records'].items():
        count = value['main_samples']
        stub = sum(row['samples'] for row in value['top_functions'] if row['name']=='.text.prefetch_calls')
        branch = sum(value['instruction_classes'].get(name, 0) for name in
                     ['conditional_branch', 'direct_call', 'indirect_call', 'direct_jump', 'indirect_jump', 'return'])
        item = dict(main_samples=count, within_64B_pct=100*value['within_64B_of_target']/count,
            prior_mispredicted_pct=100*value['nearest_branch_mispredicted']/count,
            stub_pct=100*stub/count, branch_instruction_pct=100*branch/count)
        residual[key] = item
        lines.append('| '+key+f' | {count:,} | '+' | '.join(f'{item[name]:.3f}%' for name in
            ['within_64B_pct', 'prior_mispredicted_pct', 'stub_pct', 'branch_instruction_pct'])+' |')
    selection = read(root/'padding_residual/selection.json')
    qualification = read(root/'padding_residual/complete.json')
    padding = dict(qualification, selected_hints=len(selection['changes']),
        heldout_coverage_pct=100*selection['heldout_covered']/selection['heldout_samples'])
    lines += ['', f'Existing-padding qualification: {padding["selected_hints"]} targets; '
        f'train coverage {padding["train_coverage_pct"]:.3f}%, heldout {padding["heldout_coverage_pct"]:.3f}%. '
        f'Compiled: {padding["compiled"]}. Train-only minimum was 5%; no endpoint measurement is inferred.', '',
        'Definitions: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).']
    l1 = {}
    if (root/'l1_supplement/complete.json').exists():
        prepared = read(root/'l1_supplement/complete.json'); assert prepared['valid']
        quality = read(root/'l1_supplement/profile_quality.json')
        selection = read(root/'l1_supplement/selection.json')
        l1 = dict(preparation=prepared, captures={})
        lines += ['', '## L1I-guided supplement: independent training and heldout captures', '',
            'Both captures use the unchanged split75 binary. Retain all main-image samples in '
            'the coverage denominator, including split instructions and added stubs that the '
            'new selector cannot target. These are modeled paths, not observed prefetch acceptance '
            'or a prediction of endpoint speedup.', '',
            '| Capture / service | Main samples | Within 64 B of prior taken target | Prior branch mispredicted | Eligible after exclusions | Split instruction excluded |',
            '|---|---:|---:|---:|---:|---:|']
        for key, value in quality['records'].items():
            n = value['main_samples']
            item = dict(main_samples=n, within_64B_pct=100*value['within_64B_of_target']/n,
                prior_mispredicted_pct=100*value['nearest_branch_mispredicted']/n,
                selection_eligible_pct=100*value['selection_eligible']/n,
                split_instruction_excluded_pct=100*value['exclusions'].get('split_instruction',0)/n)
            l1['captures'][key] = item
            lines.append('| '+key+f' | {n:,} | '+' | '.join(f'{item[name]:.3f}%' for name in
                ['within_64B_pct','prior_mispredicted_pct','selection_eligible_pct','split_instruction_excluded_pct'])+' |')
        assert abs(100*selection['covered']/selection['samples']-prepared['train_coverage_pct']) < 1e-9
        assert abs(100*selection['heldout']['covered']/selection['heldout']['samples']-prepared['heldout_coverage_pct']) < 1e-9
        lines += ['', f'Train-only selected hints: {len(selection["choices"])}; '
            f'train coverage {prepared["train_coverage_pct"]:.3f}%, '
            f'heldout coverage {prepared["heldout_coverage_pct"]:.3f}%. '
            'The heldout capture did not select targets. Existing T1 targets remain unchanged. '
            'Incremental IT0/T1/NOP variants have identical layout and added target addresses; '
            'only the new-slot opcodes differ. There are no new call sites, jumps, or timing guards. '
            'The added instruction bytes can still change frontend work and cache layout versus split75.']
    latency = {}
    if (root/'latency_retarget/complete.json').exists():
        prepared=read(root/'latency_retarget/complete.json');assert prepared['valid']
        selected=read(root/'latency_retarget/selection.json')
        latency=dict(preparation=prepared,train_before=selected['train_before'],train_after=selected['train_after'],
            heldout_before=selected['heldout_before'],heldout_after=selected['heldout_after'])
        lines += ['', '## Long frontend-stall retargeting', '',
            'The training event selects retired instructions after frontend delivery gaps of '
            'at least 128 cycles, not interrupted by a backend stall. It can include branch '
            'and translation effects; it is not a code-cache-miss event or a request critical-path measure. '
            'Only supplemental target displacements may change. Static call sites, hint counts '
            'per call, code layout and all original split75 T1 hints are preserved.', '',
            '| Capture | Old supplemental target coverage | Retargeted coverage |', '|---|---:|---:|']
        for phase in ['train','heldout']:
            old=selected[phase+'_before'];new=selected[phase+'_after']
            lines.append(f'| {phase} | {100*old["covered"]/old["samples"]:.3f}% | {100*new["covered"]/new["samples"]:.3f}% |')
        lines += ['', f'Changed displacements: {len(selected["changed_choices"])}. '
            f'Compiled: {prepared["compiled"]}. Frozen train-only thresholds: coverage >=5% '
            'and improvement >=1.5 percentage points. No endpoint improvement is inferred from modeled coverage.']
    result = dict(complete=True, stages=summaries, modeled_residual=modeled, residual=residual, padding=padding, l1_supplement=l1, latency_retarget=latency,
        inputs=inputs, source_sha256=b.sha(__file__), limitation=LIMIT)
    b.save(out/'summary.json', result)
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(output=str(out), inputs=len(inputs))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('root', type=Path)
    report(parser.parse_args().root)
