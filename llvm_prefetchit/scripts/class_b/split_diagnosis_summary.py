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
}
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
    for stage in ['confirmation_screen','l1_screen','l1_confirmation_screen']:
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
        summaries[stage] = dict(absolute=absolute, comparisons=comparisons,
            mongo_topdown=top['absolute']['mongo3'], e2e=data['e2e'])
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
    result = dict(complete=True, stages=summaries, modeled_residual=modeled, residual=residual, padding=padding, l1_supplement=l1,
        inputs=inputs, source_sha256=b.sha(__file__), limitation=LIMIT)
    b.save(out/'summary.json', result)
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(output=str(out), inputs=len(inputs))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('root', type=Path)
    report(parser.parse_args().root)
