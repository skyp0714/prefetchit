#!/usr/bin/env python3
"""Account for observed L1I misses at added stub addresses, without a causal ceiling."""
import argparse
import json
from pathlib import Path

import dense_build as b


def report(root):
    source = root / 'analysis/final_summary.json'
    data = json.loads(source.read_text())
    rows = []
    for group in ('native', 'mongo'):
        temporal = next(row for row in data['temporal'] if row['group'] == group and row['kind'] == 'l1')
        residual = next(row for row in data['residual'] if row['group'] == group and row['kind'] == 'l1')
        original, final = temporal['baseline2']['total'], temporal['final']['total']
        stub = residual['events_per_request']['added_hint_stub_fetch']
        rows.append(dict(group=group, original=original, final=final, added_stub=stub,
                         other_final_addresses=final-stub, observed_increase=final-original,
                         stub_to_observed_increase_pct=100*stub/(final-original)))
    b.save(root / 'analysis/final_l1_stub_cost.json', dict(rows=rows, source_sha256=b.sha(__file__),
        summary_sha256=b.sha(source), limitation='Address-based descriptive accounting from separate diagnostic captures. Added-stub counts are not a counterfactual recoverable gain; deleting stubs also removes or changes prefetch coverage. Other final addresses include unmapped samples.'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10, 'svg.hashsalt':'class-b-temporal-20261001'})
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    for ax, row in zip(axes, rows):
        ax.bar(0, row['original'], color='#7b8894', label='Original: all addresses')
        ax.bar(1, row['other_final_addresses'], color='#4294a9', label='Final: other addresses')
        ax.bar(1, row['added_stub'], bottom=row['other_final_addresses'], color='#9b77b7', label='Final: added hint stubs')
        ax.set_xticks([0, 1], ['Original', 'Final prefetch'])
        ax.set_title(row['group'])
        ax.set_ylabel('Estimated retired L1I events / request')
        ax.set_ylim(0, row['final']*1.22)
        ax.text(1, row['final']*1.035, f"Total {100*(row['final']/row['original']-1):+.2f}%", ha='center')
        ax.grid(axis='y', alpha=.2)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=3, bbox_to_anchor=(.5,.91))
    fig.suptitle('L1I miss cost at newly inserted prefetch code', y=.98)
    fig.text(.5, .025, 'Separate diagnostic captures. This accounting does not predict the effect of deleting the stubs.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0,.07,1,.85))
    for suffix in ('png', 'svg'):
        fig.savefig(root / 'analysis' / ('final_l1_stub_cost.'+suffix), dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    report(parser.parse_args().root)
