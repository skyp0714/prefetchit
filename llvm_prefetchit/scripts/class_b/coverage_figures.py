#!/usr/bin/env python3
"""Plot static target overlap or independent code-miss and E2E effects."""
import argparse
import json
from pathlib import Path


def plot(root, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data = json.loads((root/'coverage_progression.json').read_text())
    fig, ax = plt.subplots(figsize=(9.2, 4.5), constrained_layout=True)
    labels = ['V5\nprevious', 'V6\nbroader direct', 'V7\ntrained indirect', 'V8\none call earlier']
    names = {'movie':'MovieId', 'compose':'ComposeReview', 'rating':'Rating'}
    colors = {'movie':'#176B87', 'compose':'#DB6B27', 'rating':'#6A5ACD'}
    for service, label in names.items():
        rows = {row['policy']:row for row in data['rows'] if row['service']==service}
        values = [rows[policy]['coverage_pct'] for policy in ('v5','v6','v7','v8')]
        ax.plot(range(4), values, marker='o', linewidth=2, label=label, color=colors[service])
        ax.annotate(f'{values[-1]:.1f}%', (3,values[-1]), xytext=(8,0),
                    textcoords='offset points', color=colors[service], va='center')
    ax.set_xticks(range(4), labels)
    ax.set_xlim(-.15,3.55);ax.set_ylim(0,70)
    ax.set_ylabel('Original main-image miss samples on target lines (%)')
    ax.set_title('Static entry-target coverage on the same held-out samples')
    ax.grid(axis='y',alpha=.22);ax.legend(loc='upper left',frameon=False)
    ax.spines[['top','right']].set_visible(False)
    fig.supxlabel('Target overlap only; actual miss reduction is measured separately.',fontsize=10)
    out.parent.mkdir(parents=True,exist_ok=True)
    for extension in ('png','svg'):
        fig.savefig(out.with_suffix('.'+extension),dpi=180)
    plt.close(fig)


def plot_effects(root, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    miss = json.loads((root/'confirmation_miss.json').read_text())
    e2e = json.loads((root/'confirmation_evaluation/evaluation.json').read_text())
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8), constrained_layout=True)
    labels = ['Retired FE_L2 / request', 'Speculative L2I / request',
              'Whole-stack CPU / request', 'Mean request latency',
              'p99 request latency', 'Throughput']
    for ax, control, title in zip(axes, ('base', 'selected_nop'),
                                  ('Versus original', 'Versus same-layout NOP')):
        events = miss['comparisons']['selected_it0'][control]
        costs = e2e['comparisons']['selected_it0'][control]
        throughput = e2e['throughput']['selected_it0'][control]
        values = [events['sum:FE_L2'], events['sum:L2I'],
                  costs['stack_cpu'], costs['mean_ms'], costs['p99_ms']]
        points = [x['cost_reduction_pct'] for x in values]+[throughput['gain_pct']]
        intervals = [x['ci95_pct'] for x in values]+[throughput['ci95_pct']]
        for y, (point, (lo, hi)) in enumerate(zip(points, intervals)):
            color = '#176B87' if y < 2 else '#DB6B27'
            ax.errorbar(point, y, xerr=[[point-lo], [hi-point]], fmt='o',
                        color=color, capsize=4, linewidth=1.6)
        ax.axvline(0, color='#555555', linewidth=1)
        ax.axhline(1.5, color='#aaaaaa', linewidth=.7, linestyle='--')
        ax.set_yticks(range(len(labels)), labels if control == 'base' else [])
        ax.set_ylim(5.6, -.6)
        ax.set_title(title)
        ax.set_xlabel('Improvement (%)')
        ax.grid(axis='x', alpha=.2)
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle('Selected service policies: six independent paired blocks', fontsize=13)
    fig.supxlabel('Individual paired-log 95% intervals. Positive = improvement.\n'
                  'Media C4; PMU windows are separate from clean request timing.', fontsize=9)
    out.parent.mkdir(parents=True, exist_ok=True)
    for extension in ('png', 'svg'):
        fig.savefig(out.with_suffix('.'+extension), dpi=180)
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--effects', action='store_true')
    a=p.parse_args();(plot_effects if a.effects else plot)(a.root,a.out)
