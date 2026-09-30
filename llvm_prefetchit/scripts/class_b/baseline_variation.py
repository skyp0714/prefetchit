#!/usr/bin/env python3
"""Expose every baseline repeat beside policy effects, without exclusions."""
import argparse
import json
from pathlib import Path
import statistics
import dense_build as b


def report(root):
    assert (root/'complete.json').exists()
    protocol=json.loads((root/'screen/protocol.json').read_text())
    control=protocol.get('control') or ('original' if 'original' in protocol['arms'] else 'base')
    records=json.loads((root/'screen/rows.json').read_text())
    rows=[dict(block=row['block'],rps=row['achieved_rps'],pool_util_pct=row['pool_util_pct'],
               **{k:v for k,v in row['metrics'].items() if k!='inverse_rps'})
          for row in records if row['arm']==control]
    assert len(rows)==protocol['blocks'] and len(rows)>=2
    fields=[key for key in rows[0] if key!='block']
    summary={}
    for field in fields:
        values=[row[field] for row in rows];mean=statistics.mean(values)
        summary[field]=dict(mean=mean,sample_sd=statistics.stdev(values),
            sample_cv_pct=100*statistics.stdev(values)/mean,minimum=min(values),maximum=max(values),
            full_range_over_mean_pct=100*(max(values)-min(values))/mean)
    result=dict(control=control,n=len(rows),rows=rows,summary=summary,
        source_sha256=b.sha(__file__),rows_sha256=b.sha(root/'screen/rows.json'),
        interpretation='Sample variation across fresh-stack baseline repeats, including workload seed, time and system variation. Small n; not a confidence interval, a pure hardware-noise estimate, or an exclusion rule. Policy comparisons use their prespecified paired blocks, not this descriptive range.')
    b.save(root/'baseline_variation.json',result)
    lines=['# Baseline variation','',result['interpretation'],'',
        '| Block | RPS | Mean ms | p99 ms | Whole CPU us/request | Pool utilization |',
        '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f'| {row["block"]} | {row["rps"]:.2f} | {row["mean_ms"]:.4f} | {row["p99_ms"]:.4f} | {row["stack_cpu"]:.2f} | {row["pool_util_pct"]:.2f}% |')
    lines += ['', '| Metric | Mean | Sample CV | Full range / mean |', '|---|---:|---:|---:|']
    for key,value in summary.items():
        lines.append(f'| {key} | {value["mean"]:.4f} | {value["sample_cv_pct"]:.3f}% | {value["full_range_over_mean_pct"]:.3f}% |')
    (root/'baseline_variation.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    report(parser.parse_args().root)
