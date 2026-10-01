#!/usr/bin/env python3
"""Build final endpoint, temporal and residual summaries from frozen results."""
import argparse
import collections
import json
from pathlib import Path
import statistics

import dense_build as b
from temporal_path_common import EDGES


def change(before, after):
    return 100 * (after / before - 1) if before else None


def summarize(root):
    decision = json.loads((root / 'confirmation_selection.json').read_text())
    best = decision['selected']
    e2e = json.loads((root / 'confirmation/evaluation.json').read_text())
    assert e2e['complete']
    pmu = json.loads((root / 'analysis/final_pmu_summary.json').read_text())
    temporal = json.loads((root / 'analysis/temporal_summary.json').read_text())
    residual = json.loads((root / 'analysis/residual_final_summary.json').read_text())
    prepared = json.loads((root / 'prepared_candidates.json').read_text())
    cpu = collections.defaultdict(list)
    windows = []
    for row in json.loads((root / 'confirmation/rows.json').read_text()):
        result = json.loads((Path(row['output']) / 'result.json').read_text())
        totals = collections.Counter()
        for name, cost in result['all_services'].items():
            group = 'mongo' if name.endswith('-mongodb') else 'native' if name in (
                'movie-id-service', 'compose-review-service', 'rating-service', 'unique-id-service',
                'text-service', 'user-service', 'review-storage-service', 'user-review-service',
                'movie-review-service') else 'other'
            for field in ('cpu_us', 'user_us', 'system_us'):
                totals[group + ':' + field] += cost[field] / cost['completed']
                totals['all:' + field] += cost[field] / cost['completed']
        for key, value in totals.items():
            cpu[row['arm'], key].append(value)
        path = Path(row['output']) / 'endpoint_windows.json'
        if path.exists():
            data = json.loads(path.read_text())
            windows.append(dict(arm=row['arm'], block=row['block'], **data))
    cpu = {arm: {key: statistics.mean(values) for (a, key), values in cpu.items() if a == arm}
           for arm in e2e['absolute']}
    pmu_changes = {}
    for scope in pmu['arms']['original']:
        before = pmu['arms']['original'][scope]
        after = pmu['arms'][best][scope]
        pmu_changes[scope] = {}
        for kind in ('per_request', 'ratios'):
            pmu_changes[scope][kind] = {
                key: dict(before=value, after=after[kind][key], change_pct=change(value, after[kind][key]))
                for key, value in before.get(kind, {}).items() if key in after.get(kind, {})}
    time_groups = []
    for group in ('native', 'mongo'):
        for kind in ('l2', 'lat128', 'l1'):
            records = {}
            for phase in ('baseline2', 'final'):
                rows = [row for row in temporal['rows'] if row['phase'] == phase and row['kind'] == kind
                        and row['service'].startswith('mongo_') == (group == 'mongo')]
                assert len(rows) == (3 if group == 'mongo' else 9), (phase, group, kind, len(rows))
                records[phase] = dict(total=sum(row['events_per_request'] for row in rows),
                    bins=[sum(row['bins'][i]['events_per_request'] for row in rows) for i in range(len(EDGES))],
                    sample_count=sum(row['samples'] for row in rows),
                    origins={origin: dict(
                        total=sum(row['origins'].get(origin, {}).get('events_per_request', 0) for row in rows),
                        bins=[sum(row['origins'].get(origin, {}).get('bins', [{}]*len(EDGES))[i]
                                  .get('estimated_events', 0)/row['requests'] for row in rows)
                              for i in range(len(EDGES))])
                             for origin in ('new_thread_first_run', 'resume', 'boundary_or_initial')})
            before, after = records['baseline2'], records['final']
            time_groups.append(dict(group=group, kind=kind, **records,
                                    change_pct=change(before['total'], after['total']),
                                    bins_change_pct=[change(x, y) for x, y in zip(before['bins'], after['bins'])]))
    residual_groups = []
    for group in ('native', 'mongo'):
        for kind in ('l2', 'lat128', 'l1'):
            rows = [row for row in residual['records'] if row['kind'] == kind
                    and row['service'].startswith('mongo_') == (group == 'mongo')]
            counts, weighted, ages = collections.Counter(), collections.Counter(), collections.Counter()
            age_events, branches, instructions = collections.Counter(), collections.Counter(), collections.Counter()
            any_stub = collections.Counter()
            locations = collections.Counter()
            for row in rows:
                counts.update(row['counts'])
                weighted.update(row['events_per_request'])
                scale = sum(row['events_per_request'].values()) / sum(row['counts'].values())
                for item in row['age_classes']:
                    ages[item['bin'], item['classification']] += item['samples']
                    age_events[item['bin'], item['classification']] += item['samples'] * scale
                for item in row['branches']:
                    branches[item['kind']] += item['samples']
                instructions.update(row['instruction_classes'])
                any_stub.update(row.get('any_stub_witness', {}))
                for item in row['top_locations']:
                    index = item['dso']
                    digest = row['digests'][index] if 0 <= index < len(row['digests']) else 'unmapped'
                    name = row['names'][index] if 0 <= index < len(row['names']) else 'unmapped'
                    locations[digest, name, item['line'], item['classification']] += item['samples'] * scale
            assert abs(sum(age_events.values()) - sum(weighted.values())) < 1e-7
            residual_groups.append(dict(group=group, kind=kind, counts=dict(counts),
                sample_pct={key: 100 * value / sum(counts.values()) for key, value in counts.items()},
                events_per_request=dict(weighted),
                age_classes=[dict(bin=i, classification=key, samples=value,
                                  events_per_request=age_events[i, key]) for (i, key), value in sorted(ages.items())],
                branch_association_sample_pct={key: 100 * value / sum(counts.values()) for key, value in branches.items()},
                instruction_classes=dict(instructions),
                any_stub_witness=dict(any_stub),
                top_locations=[dict(sha256=sha, image=image, line_address=hex(line * 64), classification=cls,
                                    estimated_events_per_request=value)
                               for (sha, image, line, cls), value in locations.most_common(16)]))
    builds = prepared[best]['builds']
    result = dict(selected=best, confirmation=e2e, pmu=pmu_changes, pmu_absolute=pmu['arms'],
        cpu_us_per_request=cpu, temporal=time_groups, residual=residual_groups,
        representative_unknown_branch=[row for row in residual['records'] if row['kind'] == 'unknown'],
        endpoint_windows=windows, source_sha256=b.sha(__file__),
        schedule_details=[{key: row[key] for key in ('phase', 'service', 'kind', 'samples', 'joined_pct',
                          'requests', 'quality', 'median_run_us', 'median_off_us', 'runs_with_prior_out', 'migrated_pct', 'origins')}
                          for row in temporal['rows'] if row['phase'] in ('baseline2', 'final') and row['kind'] == 'l2'],
        footprint=dict(elf_count=len(builds), sites=sum(row['sites'] for row in builds.values()),
                       appended_code_bytes=sum(row['extra_instruction_bytes'] for row in builds.values())),
        limitations=[
            'Endpoint inference uses independent fresh-stack blocks only; ten-second bins are within-trial descriptions.',
            'Temporal before/after uses baseline2 and final only, both after the external host-load change.',
            'Retired L2 miss tags, L2 code-read requests and frontend stall periods are distinct event populations.',
            'PMU counters are separate diagnostic windows. Slot percentages are not fractions of request latency.',
            'Residual shares are sample shares; per-request weights are retained separately. Missing bounded-LBR witnesses do not prove no hint executed.',
            'Symbol labels in stripped libraries can be nearest exported labels, not exact source-function ownership.',
        ])
    b.save(root / 'analysis/final_summary.json', result)
    return result


def figures(root, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.size': 10, 'svg.hashsalt': 'temporal-final-20261001'})
    best = data['selected']
    names = list(data['confirmation']['absolute'])
    labels = [name.replace('pathwide_', '').replace('_', '\n') for name in names]
    fig, axes = plt.subplots(1, 4, figsize=(14, 4))
    metrics = [('RPS (higher is better)', 'rps'), ('Mean latency (ms)', 'mean_ms'),
               ('p99 latency (ms)', 'p99_ms'), ('Stack CPU / request (µs)', 'stack_cpu')]
    rows = json.loads((root / 'confirmation/rows.json').read_text())
    for ax, (label, key) in zip(axes, metrics):
        values = [[row['achieved_rps'] if key == 'rps' else row['metrics'][key]
                   for row in rows if row['arm'] == name] for name in names]
        ax.bar(range(len(names)), [statistics.mean(v) for v in values],
               color=['#2372a1' if name == best else '#a2b7c7' for name in names], alpha=.8)
        for i, observations in enumerate(values):
            ax.scatter(np.linspace(i-.15, i+.15, len(observations)), observations, s=16, color='#273746', zorder=3)
        ax.set_xticks(range(len(names)), labels, fontsize=8)
        ax.set_title(label)
        ax.grid(axis='y', alpha=.2)
        ax.set_ylim(bottom=0)
    fig.suptitle('Independent fresh-stack confirmation — dots are complete trials', y=.99)
    fig.text(.5, .015, 'C4, 8 CPUs, 2 GHz; clean 60-second ROI after 50-second warmup; no PMU in timing.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .06, 1, .95))
    savefig(root, fig, 'final_endpoint')
    contrasts = data['confirmation']['e2e'][best]
    controls = list(contrasts)
    fig, axes = plt.subplots(1, 4, figsize=(14, 4.5))
    for ax, key, title in zip(axes, ('inverse_rps', 'mean_ms', 'p99_ms', 'stack_cpu'),
                              ('Throughput gain', 'Mean latency reduction', 'p99 latency reduction', 'CPU/request reduction')):
        for i, control in enumerate(controls):
            row = contrasts[control][key]
            value = 100 * (row['speedup']-1) if key == 'inverse_rps' else row['cost_reduction_pct']
            lo, hi = [100 * (v-1) for v in row['speedup_ci95']] if key == 'inverse_rps' else row['ci95_pct']
            ax.errorbar(value, i, xerr=[[value-lo], [hi-value]], fmt='o', color='#2372a1', capsize=4)
        ax.axvline(0, color='#777777', linewidth=1)
        ax.set_yticks(range(len(controls)), ['vs ' + name.replace('pathwide_', '') for name in controls], fontsize=8)
        ax.invert_yaxis()
        ax.set_title(title)
        ax.set_xlabel('Improvement (%)')
        ax.grid(axis='x', alpha=.2)
    fig.suptitle(best + ' — independent paired contrasts', y=.98)
    fig.text(.5, .02, 'Points: paired log-ratios. Bars: individual t95 intervals, without multiplicity adjustment. Right of zero is better.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .93))
    savefig(root, fig, 'final_endpoint_effects')
    fig, axes = plt.subplots(2, 3, figsize=(14, 7))
    for row_index, group in enumerate(('native', 'mongo')):
        limit = 100 if group == 'native' else 500
        for col, kind in enumerate(('l2', 'lat128', 'l1')):
            ax = axes[row_index, col]
            row = next(row for row in data['temporal'] if row['group'] == group and row['kind'] == kind)
            indices = [i for i in range(len(EDGES)-1) if EDGES[i+1] <= limit]
            for phase, label, color in [('baseline2', 'original', '#7b8894'), ('final', best, '#007b9b')]:
                values = [row[phase]['bins'][i] / (EDGES[i+1]-EDGES[i]) for i in indices]
                ax.stairs(values, EDGES[:len(values)+1], label=label, color=color, linewidth=1.7)
            ax.axvspan(10, 20, color='#999999', alpha=.12)
            ax.set_title(group + ' — ' + {'l2':'retired L2 miss', 'lat128':'delivery gap ≥128 cycles', 'l1':'retired L1I miss'}[kind])
            ax.set_xlim(0, limit)
            ax.set_ylim(bottom=0)
            ax.grid(alpha=.2)
            if col == 0:
                ax.set_ylabel('Estimated events / request / age-bin µs')
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(.5, .967))
    fig.suptitle('Misses after schedule-in: remeasured original versus final policy', y=.997)
    fig.supxlabel('Sample retirement age after scheduler selection (µs)', y=.035)
    fig.text(.5, .008, 'Separate diagnostic captures. Samples retire after fetch; scheduler age includes kernel time. Later bins remain in JSON.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .075, 1, .91))
    savefig(root, fig, 'final_temporal_overview')
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    for row_index, group in enumerate(('native', 'mongo')):
        limit = 100 if group == 'native' else 500
        row = next(item for item in data['temporal'] if item['group'] == group and item['kind'] == 'l2')
        indices = [i for i in range(len(EDGES)-1) if EDGES[i+1] <= limit]
        for col, origin in enumerate(('new_thread_first_run', 'resume')):
            ax = axes[row_index, col]
            for phase, label, color in [('baseline2', 'original', '#7b8894'), ('final', best, '#007b9b')]:
                values = [row[phase]['origins'][origin]['bins'][i]/(EDGES[i+1]-EDGES[i]) for i in indices]
                ax.stairs(values, EDGES[:len(values)+1], label=label, color=color, linewidth=1.7)
            ax.axvspan(10, 20, color='#999999', alpha=.12)
            ax.set_title(group + ' — ' + ('new thread: first run' if col == 0 else 'resumed thread'))
            ax.set_xlim(0, limit)
            ax.set_ylim(bottom=0)
            ax.grid(alpha=.2)
            if not any(row[phase]['origins'][origin]['total'] for phase in ('baseline2', 'final')):
                ax.text(.5, .5, 'No new-thread samples in these captures', transform=ax.transAxes,
                        ha='center', va='center', fontsize=9)
                ax.set_ylim(0, 1)
            if col == 0:
                ax.set_ylabel('Retired L2 events / request / age-bin µs')
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, bbox_to_anchor=(.5, .967))
    fig.suptitle('First execution versus resume: where residual misses occur', y=.997)
    fig.supxlabel('Sample retirement age after scheduler selection (µs)', y=.035)
    fig.text(.5, .008, 'Observed thread births and scheduler records; retirement age includes kernel time. Boundary runs are excluded.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .075, 1, .91))
    savefig(root, fig, 'final_temporal_origin')
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    classes = [('line_not_statically_targeted', 'Not statically targeted', '#d68c45'),
               ('targeted_line_without_matching_stub_in_bounded_lbr', 'Targeted; no bounded-LBR witness', '#c75356'),
               ('added_hint_stub_fetch', 'Added hint stub', '#8c6bb1'),
               ('matching', 'Matching stub observed', '#3c9b95'),
               ('other', 'Other / unmodified image', '#a4adb5')]
    for ax, group in zip(axes, ('native', 'mongo')):
        limit = 100 if group == 'native' else 500
        indices = [i for i in range(len(EDGES)-1) if EDGES[i+1] <= limit]
        edges = np.array(EDGES[:len(indices)+1])
        residual_row = next(row for row in data['residual'] if row['group'] == group and row['kind'] == 'l2')
        bins = collections.defaultdict(lambda: np.zeros(len(indices)))
        for item in residual_row['age_classes']:
            if item['bin'] not in indices:
                continue
            cls = item['classification']
            cls = 'matching' if cls.startswith('matching_stub_observed_') else cls
            if cls not in {key for key, _, _ in classes}:
                cls = 'other'
            i = item['bin']
            bins[cls][i] += item['events_per_request'] / (EDGES[i+1]-EDGES[i])
        bottom = np.zeros(len(indices))
        for key, label, color in classes:
            top = bottom + bins[key]
            ax.stairs(top, edges, baseline=bottom, fill=True, color=color, alpha=.85, label=label)
            bottom = top
        baseline = next(row for row in data['temporal'] if row['group'] == group and row['kind'] == 'l2')
        old = np.array(baseline['baseline2']['bins'][:len(indices)]) / np.diff(edges)
        ax.stairs(old, edges, color='#233647', linewidth=1.5, label='Original total')
        ax.set_title(group + ' — remaining retired L2 misses')
        ax.set_xlim(0, limit)
        ax.set_ylim(bottom=0)
        ax.set_xlabel('Retirement age after schedule-in (µs)')
        ax.set_ylabel('Estimated events / request / age-bin µs')
        ax.grid(alpha=.2)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=3, fontsize=9)
    fig.text(.5, .015, 'Stacked areas are final residuals; the line is original. A bounded-LBR witness does not establish hint acceptance or completion.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0, .05, 1, .85))
    savefig(root, fig, 'final_residual_time')
    valid = [row for row in data['endpoint_windows'] if row.get('valid')]
    if valid:
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
        for ax, key, title in zip(axes, ('achieved_rps', 'mean_ms', 'p99_ms'), ('RPS', 'Mean latency (ms)', 'p99 latency (ms)')):
            for name in names:
                selected = [row for row in valid if row['arm'] == name]
                assert selected and len({len(row['windows']) for row in selected}) == 1
                x = [w['relative_start_s'] + w['seconds']/2 for w in selected[0]['windows']]
                y = [[row['windows'][i][key] for row in selected] for i in range(len(x))]
                ax.plot(x, [statistics.mean(v) for v in y], marker='o', markersize=3, label=name)
            ax.set_title(title)
            ax.set_xlabel('Seconds within clean ROI')
            ax.grid(alpha=.2)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='upper center', ncol=3, fontsize=8)
        fig.text(.5, .01, 'Means across independent trials; ten-second windows are descriptive, not additional replications.', ha='center', fontsize=9)
        fig.tight_layout(rect=(0, .06, 1, .86))
        savefig(root, fig, 'final_endpoint_time')


def savefig(root, fig, name):
    from matplotlib import pyplot as plt
    for suffix in ('png', 'svg'):
        fig.savefig(root / 'analysis' / (name + '.' + suffix), dpi=160)
    plt.close(fig)


def tables(root, data):
    best = data['selected']
    e2e = data['confirmation']
    lines = ['| 정책 | RPS | 평균 지연 ms | p99 ms | 전체 CPU µs/request | CPU util |',
             '|---|---:|---:|---:|---:|---:|']
    for arm, values in e2e['absolute'].items():
        costs = values['e2e']
        lines.append(f"| `{arm}` | {values['rps']:.2f} | {costs['mean_ms']:.4f} | {costs['p99_ms']:.4f} | {costs['stack_cpu']:.2f} | {values['util_pct']:.2f}% |")
    lines += ['', '각 수치는 독립 실행의 산술평균이다. 아래 변화율과 구간은 같은 블록끼리의 로그 비율을 사용한다.', '',
              '| 최종 정책의 비교 대상 | 처리량 증가, 95% CI | 평균 지연 절감, 95% CI | p99 절감, 95% CI | CPU/request 절감, 95% CI |',
              '|---|---:|---:|---:|---:|']
    for control, metrics in e2e['e2e'][best].items():
        values = []
        for key in ('inverse_rps', 'mean_ms', 'p99_ms', 'stack_cpu'):
            row = metrics[key]
            value = 100 * (row['speedup'] - 1) if key == 'inverse_rps' else row['cost_reduction_pct']
            interval = [100 * (x - 1) for x in row['speedup_ci95']] if key == 'inverse_rps' else row['ci95_pct']
            values.append(f'{value:+.2f}% [{interval[0]:+.2f}, {interval[1]:+.2f}]')
        lines.append('| `' + control + '` | ' + ' | '.join(values) + ' |')
    lines += ['', 'CI는 개별 대비의 paired-log t95이며 다중 비교 보정은 하지 않았다. p99 절감이 음수이면 악화다.', '',
              '| 전체 CPU/request 구성 | 원본 µs | 최종 µs | 변화 |', '|---|---:|---:|---:|']
    before, after = data['cpu_us_per_request']['original'], data['cpu_us_per_request'][best]
    for key, label in [('all:user_us', '사용자 코드'), ('all:system_us', '커널'),
                       ('native:cpu_us', '앱 서버 9개'), ('mongo:cpu_us', 'MongoDB 컨테이너 전체'), ('other:cpu_us', '그 외 서비스')]:
        lines.append(f"| {label} | {before[key]:.2f} | {after[key]:.2f} | {change(before[key], after[key]):+.2f}% |")
    lines += ['', '사용자/커널 행과 서비스 그룹 행은 서로 다른 분류이므로 함께 더하지 않는다. 요청의 순차 critical path를 뜻하지 않는다.', '',
              '| 별도 PMU 진단, 요청당 | 앱 서버 9개: 원본 → 최종 (변화) | MongoDB 3개: 원본 → 최종 (변화) |', '|---|---:|---:|']
    counter_rows = [
        ('cache:FE_L2', 'Retired L2 code miss'), ('cache:L2I', 'L2 code-read miss'),
        ('cache:L2_CODE_ALL', 'L2 code-read 요청'), ('l1:FE_L1', 'Retired L1I miss'),
        ('cache:ICACHE_DATA_STALL', 'I-cache data stall cycles'), ('cache:ICACHE_STALL_PERIODS', 'I-cache stall periods'),
        ('l1:ICACHE_TAG_STALL', 'I-cache tag stall cycles'), ('l1:ITLB_STLB_HIT', 'ITLB miss → STLB hit'),
        ('l1:ITLB_WALK_COMPLETED', 'ITLB page walk 완료'), ('front:ITLB_WALK_ACTIVE', 'ITLB page walk active cycles'),
        ('recovery:branch-misses:u', 'Branch misprediction'), ('recovery:RECOVERY_CYCLES', 'Recovery cycles'),
        ('recovery:CLEAR_RESTEER_CYCLES', 'Clear → 첫 uop cycles'), ('front:UNKNOWN_BRANCH_CYCLES', 'Unknown-branch bubble cycles'),
        ('front:DSB_UOPS', 'µop cache (DSB) 공급 uops'), ('front:MITE_UOPS', 'Decoder (MITE) 공급 uops'),
        ('topdown:cycles:u', 'User cycles'), ('topdown:instructions:u', 'Retired instructions'),
        ('topdown:topdown-fe-bound:u', 'Frontend-bound slots')]
    for key, label in counter_rows:
        values = []
        for group in ('native', 'mongo'):
            row = data['pmu'][group]['per_request'].get(key)
            values.append('—' if row is None else f"{row['before']:,.1f} → {row['after']:,.1f} ({row['change_pct']:+.2f}%)" if row['change_pct'] is not None else f"{row['before']:,.1f} → {row['after']:,.1f}")
        lines.append('| ' + label + ' | ' + ' | '.join(values) + ' |')
    lines += ['', '| PMU 비율 | 앱 서버: 원본 → 최종 | MongoDB: 원본 → 최종 |', '|---|---:|---:|']
    for key, label in [('fe-bound_pct', 'Frontend-bound slots %'), ('be-bound_pct', 'Backend-bound slots %'),
                       ('fetch-lat_pct', 'Fetch-latency-bound slots %'), ('mem-bound_pct', 'Memory-bound slots %'),
                       ('bad-spec_pct', 'Bad-speculation slots %'), ('recovery_cycles_pct', 'Recovery / cycles %'),
                       ('clear_resteer_cycles_pct', 'Clear-resteer / cycles %'), ('unknown_branch_cycles_pct', 'Unknown-branch bubbles / cycles %'),
                       ('code_read_mpki', 'Code-read MPKI'), ('retired_l2_mpki', 'Retired L2 MPKI'), ('retired_l1_mpki', 'Retired L1I MPKI'),
                       ('code_read_miss_pct', 'Code-read miss / 요청 %'), ('cycles_per_icache_stall_period', 'Cycles / I-cache stall period')]:
        values = []
        for group in ('native', 'mongo'):
            row = data['pmu'][group]['ratios'].get(key)
            values.append('—' if row is None else f"{row['before']:.2f} → {row['after']:.2f}")
        lines.append('| ' + label + ' | ' + ' | '.join(values) + ' |')
    lines += ['', 'PMU는 독립된 짧은 진단 구간이다. 서로 다른 이벤트 그룹은 다른 시간에 측정했다. 중첩되는 stall cycle 비율은 합산할 수 없고, frontend-bound slots %를 요청 지연 비중으로 해석하면 안 된다.', '',
              '| 같은 코드 배치의 NOP와 비교, 요청당 | 원본 | NOP | Prefetch | Prefetch/NOP 변화 |', '|---|---:|---:|---:|---:|']
    for group in ('native', 'mongo'):
        for key, label in [('cache:L2I', 'L2 code-read miss'), ('cache:FE_L2', 'Retired L2 miss'),
                           ('l1:FE_L1', 'Retired L1I miss'), ('cache:ICACHE_DATA_STALL', 'I-cache stall cycles'),
                           ('recovery:branch-misses:u', 'Branch misprediction'),
                           ('recovery:RECOVERY_CYCLES', 'Recovery cycles'),
                           ('recovery:CLEAR_RESTEER_CYCLES', 'Clear-resteer cycles'),
                           ('front:UNKNOWN_BRANCH_CYCLES', 'Unknown-branch bubbles')]:
            original = data['pmu_absolute']['original'][group]['per_request'][key]
            nop = data['pmu_absolute'][best + '_nop'][group]['per_request'][key]
            prefetch = data['pmu_absolute'][best][group]['per_request'][key]
            value = change(nop, prefetch)
            delta = '—' if value is None else f'{value:+.2f}%'
            lines.append(f'| {group} / {label} | {original:,.1f} | {nop:,.1f} | {prefetch:,.1f} | {delta} |')
    lines += ['', 'NOP은 추가 분기·GOT 접근·코드 배치를 유지하고 삽입한 prefetch 명령만 같은 길이의 NOP으로 바꾼 대조군이다.', '',
              '| 서비스별 결과 | E2E CPU µs/request: 원본 → 최종 | FE-bound slots %: 원본 → 최종 | L2 code-read miss 변화 | Retired L2 변화 | Retired L1I 변화 | ITLB page walk 완료 변화 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    from media_system_study import MONITORED
    for scope, service in MONITORED.items():
        old_cpu = e2e['absolute']['original']['service_cpu'][service + ':cpu_us/request']
        new_cpu = e2e['absolute'][best]['service_cpu'][service + ':cpu_us/request']
        fe = data['pmu'][scope]['ratios']['fe-bound_pct']
        values = []
        for key in ('cache:L2I', 'cache:FE_L2', 'l1:FE_L1', 'l1:ITLB_WALK_COMPLETED'):
            delta = data['pmu'][scope]['per_request'][key]['change_pct']
            values.append('—' if delta is None else f'{delta:+.2f}%')
        lines.append(f'| {service} | {old_cpu:.2f} → {new_cpu:.2f} | '
                     f'{fe["before"]:.2f} → {fe["after"]:.2f} | ' + ' | '.join(values) + ' |')
    lines += ['', 'CPU는 clean E2E 실행의 cgroup 값이고 PMU는 별도 진단 실행이다. '
              '음의 미스 변화율은 감소를 뜻한다. Nginx 실행 파일은 수정하지 않은 관찰 대조군이다.', '',
              '| 서비스 CPU의 사용자/커널 분해 | 원본의 커널 CPU 비중 | User CPU/request 변화 | Kernel CPU/request 변화 | 전체 CPU/request 변화 |',
              '|---|---:|---:|---:|---:|']
    for _, service in MONITORED.items():
        old = e2e['absolute']['original']['service_cpu']
        new = e2e['absolute'][best]['service_cpu']
        values = [change(old[service + ':' + field], new[service + ':' + field])
                  for field in ('user_us/request', 'system_us/request', 'cpu_us/request')]
        fraction = 100 * old[service + ':system_us/request'] / old[service + ':cpu_us/request']
        lines.append(f'| {service} | {fraction:.2f}% | ' +
                     ' | '.join('—' if value is None else f'{value:+.2f}%' for value in values) + ' |')
    lines += ['', '위 PMU frontend 비율은 사용자 코드에서 측정한 값이다. 이 표의 커널 CPU 비중과 분모를 혼동하지 않는다.', '',
              '| 시간대별 진단 | 전체 이벤트/request 변화 | 0–20µs 변화 | 20–100µs 변화 | ≥100µs 변화 |', '|---|---:|---:|---:|---:|']
    for row in data['temporal']:
        values = []
        for lo, hi in [(0, 20), (20, 100), (100, float('inf'))]:
            indices = [i for i, edge in enumerate(EDGES) if lo <= edge < hi]
            old = sum(row['baseline2']['bins'][i] for i in indices)
            new = sum(row['final']['bins'][i] for i in indices)
            value = change(old, new)
            values.append('—' if value is None else f'{value:+.2f}%')
        lines.append(f"| {row['group']} / {row['kind']} | {row['change_pct']:+.2f}% | " + ' | '.join(values) + ' |')
    lines += ['', '시간축은 scheduler가 다음 태스크를 선택한 뒤 샘플 명령이 retire할 때까지다. fetch 시점이나 prefetch lead-time 자체가 아니다. 요청당 값은 perf 시작·종료를 둘러싼 요청 구간으로 정규화한 추정치다.', '',
              '| L2 진단의 스케줄 특성 | 원본 → 최종 중앙 실행 구간 µs | 새 스레드 첫 실행의 미스 비중 | 재실행 때 코어 이동 비율 | 샘플 스케줄 연결률 |',
              '|---|---:|---:|---:|---:|']
    for service in sorted({row['service'] for row in data['schedule_details']}):
        pair = [next(row for row in data['schedule_details'] if row['service'] == service and row['phase'] == phase)
                for phase in ('baseline2', 'final')]
        metrics = []
        for row in pair:
            origins = row['origins']
            total = sum(value['estimated_events'] for value in origins.values())
            metrics.append([row['median_run_us'], 100*origins.get('new_thread_first_run', {}).get('estimated_events', 0)/total,
                            row['migrated_pct'], row['joined_pct']])
        lines.append('| ' + service + ' | ' + ' | '.join(f'{old:.2f} → {new:.2f}' for old, new in zip(*metrics)) + ' |')
    lines += ['', '새 스레드 첫 실행은 FORK 기록 이후의 첫 스케줄 구간이다. 코어 이동 비율의 분모는 직전 실행 코어를 확인할 수 있는 재실행 구간이며, 전체 요청 수나 미스 수가 아니다. 후반 세 열의 단위는 %다.', '',
              '| 남은 미스의 샘플 분포 | 정적 타깃 밖 | 타깃이지만 LBR에 대응 힌트 없음 | 삽입한 hint stub | 대응 힌트가 LBR에 있음 | 미수정·타깃 없는 ELF |', '|---|---:|---:|---:|---:|---:|']
    for row in data['residual']:
        pct = row['sample_pct']
        values = [pct.get('line_not_statically_targeted', 0), pct.get('targeted_line_without_matching_stub_in_bounded_lbr', 0),
                  pct.get('added_hint_stub_fetch', 0), sum(value for key, value in pct.items() if key.startswith('matching_stub_observed_')),
                  pct.get('unmodified_image', 0)]
        lines.append(f"| {row['group']} / {row['kind']} | " + ' | '.join(f'{value:.2f}%' for value in values) + ' |')
    lines += ['', 'LBR는 최근 32개 분기로 제한된다. 대응 힌트가 보이지 않는다고 발행되지 않았다고 단정할 수 없고, 보인다고 캐시 채움이 완료됐다는 뜻도 아니다. 잔여 미스의 구성 비율과 원본 대비 절대 미스 감소율은 다른 지표다.', '']
    lines += ['| 잔여 샘플과 직전 taken branch의 관계 | 타깃 이후 64B 안 | 직전 분기가 mispredicted | 직전 분기가 correctly predicted |',
              '|---|---:|---:|---:|']
    for row in data['residual']:
        pct = row['branch_association_sample_pct']
        values = [pct.get(key, 0) for key in ('within_64B_after_taken_target',
                  'preceding_mispredicted_taken_branch', 'preceding_correctly_predicted_taken_branch')]
        lines.append(f"| {row['group']} / {row['kind']} | " + ' | '.join(f'{value:.2f}%' for value in values) + ' |')
    lines += ['', '분모는 해당 그룹의 전체 잔여 샘플이다. 뒤 두 열은 첫 열의 부분집합이며, 미스 원인의 배타적 분해나 BTB miss 비율이 아니다. 실제 미스 명령 종류와 ELF 주소별 잔여 위치도 final_summary.json에 보존했다.', '']
    (root / 'analysis/final_tables.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    result = summarize(args.root)
    tables(args.root, result)
    if args.plot:
        figures(args.root, result)
