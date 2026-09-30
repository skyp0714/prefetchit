#!/usr/bin/env python3
"""Plot incremental policies against each campaign's own split75 control."""
import argparse
import json
from pathlib import Path
import dense_build as b


def report(root):
    diagnosis_path = root / 'diagnosis/summary.json'
    diagnosis = json.loads(diagnosis_path.read_text())
    assert diagnosis['complete']
    definitions = [
        ('A', 'hybrid_screen', 'early_it0', 'Early IT0 burst'),
        ('B', 'lead_screen', 'residual_t1', '116 residual targets'),
        ('B', 'lead_screen', 'lead512', 'Earlier placement (age 512)'),
        ('D', 'l1_screen', 'extra_t1', '256 L1I-guided T1 slots'),
        ('D', 'l1_screen', 'extra_it0', '256 L1I-guided IT0 slots'),
        ('E', 'latency_screen', 'latency_t1', 'Long-stall-guided T1 targets'),
    ]
    inputs = {str(diagnosis_path): b.sha(diagnosis_path)}
    rows = []
    for campaign, stage, arm, label in definitions:
        path = root / stage / 'screen_evaluation.json'
        inputs[str(path)] = b.sha(path)
        evaluation = json.loads(path.read_text())
        assert evaluation['complete'] and evaluation['trials'] == 16
        e2e = evaluation['e2e'][arm]['split75']
        pmu = diagnosis['stages'][stage]['comparisons'][arm + '/split75']
        throughput = e2e['inverse_rps']
        metrics = {'Throughput gain (%)': {
            'point': 100 * (throughput['speedup'] - 1),
            'ci95': [100 * (v - 1) for v in throughput['speedup_ci95']],
            'pairs': throughput['pairs']}}
        for title, value in [
            ('Whole CPU/request reduction (%)', e2e['stack_cpu']),
            ('Retired L2 event reduction (%)', pmu['Retired L2']),
            ('I-cache stall reduction (%)', pmu['I-cache stall cycles']),
        ]:
            metrics[title] = dict(point=value['cost_reduction_pct'], ci95=value['ci95_pct'], pairs=value['pairs'])
        assert all(v['pairs'] == 4 and len(v['ci95']) == 2 for v in metrics.values())
        rows.append(dict(campaign=campaign, stage=stage, arm=arm, label=label, metrics=metrics))
    record = dict(complete=True, rows=rows, inputs=inputs, source_sha256=b.sha(__file__),
        scope='Each row uses its own four-block campaign split75 control; no pooling or multiplication across campaigns. '
        'Full Media compose-review C4 including MovieId on eight workload CPUs. Individual paired-log t95 intervals, '
        'without multiplicity correction. Endpoint metrics are clean ROI; MongoDB-three PMU is post-ROI. '
        'Positive values are improvements. Retired L2 and speculative code-read miss are different populations.')
    b.save(root / 'policy_overview.json', record)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    colors = {'A': '#4965aa', 'B': '#ba702b', 'D': '#7c65a8', 'E': '#158176'}
    fig, axes = plt.subplots(1, 4, figsize=(16.8, 5.3), sharey=True)
    for axis, metric in zip(axes, rows[0]['metrics']):
        for index, row in enumerate(rows):
            value = row['metrics'][metric]
            point = value['point']; low, high = value['ci95']
            axis.errorbar(point, index, xerr=[[point-low], [high-point]], fmt='o',
                color=colors[row['campaign']], capsize=3, markersize=6)
            axis.annotate(f'{point:+.2f}', (point, index), xytext=(0, 9),
                textcoords='offset points', ha='center', fontsize=8)
        axis.axvline(0, color='#555555', ls='--', lw=.9)
        axis.set_xlabel(metric, fontsize=10)
        axis.grid(axis='x', alpha=.18)
        axis.set_ylim(len(rows)-.45, -.65)
        axis.margins(x=.13)
        axis.spines[['top', 'right']].set_visible(False)
    axes[0].set_yticks(range(len(rows)), [f"{v['campaign']}: {v['label']}" for v in rows], fontsize=9)
    fig.suptitle('Incremental policies versus split75 in each independent campaign', fontsize=14)
    fig.text(.5, .04, 'Four paired blocks per row; individual 95% intervals. Positive = improvement. '
        'No pooling across campaigns. MongoDB PMU follows the clean endpoint ROI.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .10, 1, .95))
    output = root / 'latency_screen/figures'; output.mkdir(exist_ok=True)
    for suffix in ['png', 'svg']:
        fig.savefig(output / ('policy_overview.' + suffix), dpi=170)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    report(parser.parse_args().root)
