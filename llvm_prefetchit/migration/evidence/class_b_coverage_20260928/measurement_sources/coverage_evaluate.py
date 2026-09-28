#!/usr/bin/env python3
"""Paired code-miss diagnostics, kept separate from clean E2E measurements."""
import argparse
import json
from pathlib import Path

import dense_build as b
from fullset_study import summarize


def evaluate(root, out):
    protocol = json.loads((root/'protocol.json').read_text())
    complete = json.loads((root/'complete.json').read_text())
    rows = json.loads((root/'rows.json').read_text())
    assert len(rows) == complete['rows'] == protocol['blocks']*len(protocol['arms'])
    assert all(row['valid'] for row in rows)
    diagnostics = []
    for row in rows:
        result = json.loads((Path(row['output'])/'result.json').read_text())
        metrics = {}
        for service, values in result['pmu'].items():
            assert values['fully_scheduled'] and values['window']['completed'] > 0
            for event, value in values['per_request'].items():
                metrics[service+':'+event] = value
                metrics['sum:'+event] = metrics.get('sum:'+event, 0)+value
        if metrics:
            assert set(result['pmu']) == set(b.SERVICES)
            diagnostics.append(dict(arm=row['arm'],block=row['block'],valid=True,metrics=metrics,
                                    result_sha256=b.sha(Path(row['output'])/'result.json')))
    summary = summarize(diagnostics, protocol['arms'])
    decisions = {}
    for arm, settings in protocol['arms'].items():
        if not arm.endswith('_it0'):
            continue
        comparisons = {}
        for control in settings['controls']:
            effects = []
            for block in range(protocol['blocks']):
                pair = {row['arm']:row['metrics']['sum:FE_L2'] for row in diagnostics
                        if row['block']==block and row['arm'] in (arm,control)}
                if len(pair)==2:
                    effects.append(100*(1-pair[arm]/pair[control]))
            comparisons[control] = dict(paired_reductions_pct=effects,
                every_block_reduces=bool(effects) and all(value>0 for value in effects),
                summary=summary[arm][control]['sum:FE_L2'])
        decisions[arm] = dict(contrasts=comparisons,
            miss_screen_eligible=all(x['every_block_reduces'] for x in comparisons.values()))
    result = dict(campaign=str(root),rows=diagnostics,comparisons=summary,decisions=decisions,
        interpretation='Positive values mean fewer events/request. FE_L2 retired-event population differs from speculative L2I. PMU windows follow clean E2E timing; service sums combine sequential request-normalized windows. Individual paired-log t95 intervals, no multiplicity correction; screen and confirmation never pooled.')
    b.save(out, result)
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();result=evaluate(a.root,a.out);print(json.dumps(result['decisions'],indent=2))
