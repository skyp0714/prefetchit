#!/usr/bin/env python3
"""Aggregate coarse shared-host placement observations without process identities."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import statistics

import dense_build as b


def summarize(root):
    # Pytest's root-owned basetemp is mode 0700. Preserve its remaining source
    # records here while the post-measurement controller still has read access.
    # Executables were removed immediately after those tests completed.
    test_root = root / 'tests_alignment'
    if test_root.exists():
        assert os.access(test_root, os.R_OK | os.X_OK), test_root
        cleanup = json.loads((root / 'tests_alignment_cleanup.json').read_text())
        assert cleanup['status'] == 'complete'
        sources = []
        for path in sorted(test_root.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            value = path.read_bytes()
            assert value[:4] != b'\x7fELF', path
            record = dict(path=str(path.relative_to(test_root)), bytes=len(value),
                          sha256=hashlib.sha256(value).hexdigest())
            try:
                record['text'] = value.decode()
            except UnicodeDecodeError:
                record['base64'] = base64.b64encode(value).decode('ascii')
            sources.append(record)
        b.save(root / 'analysis/retained_alignment_sources.json', dict(valid=True, source=str(test_root),
            no_generated_elf=True, cleanup_sha256=b.sha(root / 'tests_alignment_cleanup.json'), records=sources))
    watch = root / 'background_cpu_watch.jsonl'
    observations = []
    source = watch.read_bytes()
    for line in source.decode().splitlines():
        try:
            observations.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # A still-running observer may be writing its final line.
    clock_ticks = os.sysconf('SC_CLK_TCK')
    windows, variation = [], []
    for campaign in ('screen1', 'screen2', 'screen3', 'confirmation'):
        path = root / campaign / 'rows.json'
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        for arm in sorted({row['arm'] for row in rows}):
            values = [row['achieved_rps'] for row in rows if row['arm'] == arm]
            variation.append(dict(campaign=campaign, arm=arm, trials=len(values), mean_rps=statistics.mean(values),
                min_rps=min(values), max_rps=max(values),
                rps_cv_pct=100 * statistics.stdev(values) / statistics.mean(values) if len(values) > 1 else None))
        for row in rows:
            result = json.loads((Path(row['output']) / 'result.json').read_text())
            pool = result['pool']
            selected = [value for value in observations if pool['start'] <= value['epoch'] < pool['end']]
            item = dict(campaign=campaign, block=row['block'], arm=row['arm'], start=pool['start'], end=pool['end'],
                        observation_count=len(selected), performance_excluded=False)
            if selected:
                item.update(active_process_range=[min(v['active'] for v in selected), max(v['active'] for v in selected)],
                    observed_placement_overlap_snapshots=sum(bool(v['overlap_last_cpu']) for v in selected))
                elapsed = selected[-1]['epoch'] - selected[0]['epoch']
                # Only constant populations permit a meaningful difference of cumulative ticks.
                if elapsed > 0 and len({v['active'] for v in selected}) == 1:
                    delta = selected[-1]['total_cpu_ticks'] - selected[0]['total_cpu_ticks']
                    if delta >= 0:
                        item['background_cpu_cores_estimate'] = delta / clock_ticks / elapsed
            windows.append(item)
    output = dict(windows=windows, variation=variation, source_sha256=b.sha(__file__),
        observation_prefix_bytes=len(source), observation_prefix_sha256=hashlib.sha256(source).hexdigest(),
        limitation='One-second /proc last-CPU snapshots on controller CPU84, without perf/tracing in clean ROI. These observations cannot exclude brief placement overlap or shared-socket bandwidth/cache interference. No unrelated process was altered; no performance-based exclusions or background-adjusted speedups.')
    b.save(root / 'analysis/final_environment_summary.json', output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    summarize(parser.parse_args().root)
