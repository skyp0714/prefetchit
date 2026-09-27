#!/usr/bin/env python3
"""Post-hoc request p99 and delivered RPS from the retained seven-pair campaign."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from scipy.stats import t


def compare(rows, control, metric, higher_better=False):
    pairs = {}
    for row in rows:
        if row['arm'] in ('new', control) and row['valid']:
            assert row['arm'] not in pairs.setdefault(row['block'], {})
            pairs[row['block']][row['arm']] = row[metric]
    logs = [math.log(p['new'] / p[control]) * (1 if higher_better else -1)
            for p in pairs.values() if len(p) == 2]
    mean = statistics.mean(logs)
    half = float(t.ppf(.975, len(logs)-1))*statistics.stdev(logs)/math.sqrt(len(logs))
    convert = (lambda x: 100*math.expm1(x)) if higher_better else (lambda x: -100*math.expm1(-x))
    return dict(pairs=len(logs), improvement_pct=convert(mean),
                ci95_pct=[convert(mean-half), convert(mean+half)])


def analyze(root):
    output = dict(analysis='Post-hoc individual paired-log t 95% intervals, no multiplicity correction',
                  scope='External HTTP planned-arrival to completion latency, per family bundle; not individual RPC latency',
                  throughput='Achieved RPS under fixed 600 RPS offered load; maximum capacity not measured',
                  unavailable='p50/p95/mean cannot be recovered: original compact results retained p99 only',
                  families={})
    for family in ('media', 'social'):
        rows = []
        for row in json.loads((root/'confirmation'/family/'rows.json').read_text()):
            path = Path(row['output'])/'result.json'
            data = json.loads(path.read_text())
            rows.append(dict(block=row['block'], arm=row['arm'], valid=row['valid'],
                             p99_ms=data['pool']['p99_ms'], rps=data['pool']['achieved_rps'],
                             pool_util_pct=data['pool_util_pct'], path=str(path),
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        output['families'][family] = dict(rows=rows, arm_means={
            arm: {metric: statistics.mean(r[metric] for r in rows if r['valid'] and r['arm'] == arm)
                  for metric in ('p99_ms', 'rps', 'pool_util_pct')}
            for arm in ('base', 'reference', 'new_nop', 'new')}, comparisons={
                ctrl: {metric: compare(rows, ctrl, metric, metric == 'rps')
                       for metric in ('p99_ms', 'rps')}
                for ctrl in ('base', 'reference', 'new_nop')})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('/storage/prefetchit/class_b_fullset_20260926'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analyze(args.source), indent=2)+'\n')
