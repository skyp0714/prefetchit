#!/usr/bin/env python3
"""MovieId schedule-relative PEBS diagnostic, separate from performance trials."""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import fullset as h
from wake_miss_timeline import analyze, parse


def capture(out, pid, period):
    h.c.space()
    out.mkdir()
    tids = sorted(int(p.name) for p in Path(f'/proc/{pid}/task').iterdir())
    group = str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
    command = ['perf', 'record', '--no-buildid', '--no-buildid-cache', '-a', '-C', '32-39',
        '-m', '8M', '-e', f'cpu/event=0xc6,umask=0x03,config1=0x13,period={period},name=fe_l2/upp',
        '-e', 'sched:sched_switch', '-G', group+',',
        '-o', str(out/'perf.data'), '--', 'sleep', '15']
    h.c.save(out/'protocol.json', dict(pid=pid, tids=tids, cgroup=group, period=period,
        clock='Single perf recorder, default clock; no --clockid override',
        current_clocksource=Path('/sys/devices/system/clocksource/clocksource0/current_clocksource').read_text().strip(),
        kernel=os.uname().release, cpus='32-39', seconds=15,
        source_hashes={str(p):h.c.sha(p) for p in (Path(__file__), Path(__file__).with_name('wake_miss_timeline.py'))}))
    h.c.run(command, out/'record.log')
    h.c.save(out/'end_tids.json', sorted(int(p.name) for p in Path(f'/proc/{pid}/task').iterdir()))
    assert not re.search(r'\b(lost|truncated|throttled)\b', (out/'record.log').read_text(), re.I)


def decode_capture(out, sample_callback=None, before_cleanup=None):
    meta = json.loads((out/'protocol.json').read_text())
    pid, tids, period = meta['pid'], meta['tids'], meta['period']
    decode = ['perf', 'script', '--ns', '-i', str(out/'perf.data'), '--show-lost-events', '--show-task-events',
              '-F', 'comm,pid,tid,cpu,time,event,ip,period,trace']
    h.c.save(out/'decode_command.json', decode)
    with (out/'events.txt').open('w') as dest, (out/'decode.log').open('w') as err:
        subprocess.run(decode, stdout=dest, stderr=err, check=True)
    # Decode raw record headers separately to catch throttling/loss, even when
    # ordinary perf script does not display those record types.
    raw = ['perf', 'script', '-D', '-i', str(out/'perf.data')]
    h.c.save(out/'quality_command.json', raw)
    counts = {}
    with (out/'raw_decode.log').open('w') as err:
        process = subprocess.Popen(raw, stdout=subprocess.PIPE, stderr=err, text=True)
        for line in process.stdout:
            match = re.search(r'PERF_RECORD_(\w+)', line)
            if match:
                name = match[1]; counts[name] = counts.get(name, 0)+1
        assert process.wait() == 0
    h.c.save(out/'record_types.json', counts)
    assert not any(counts.get(name, 0) for name in ('LOST', 'LOST_SAMPLES', 'THROTTLE', 'UNTHROTTLE'))
    result = analyze(parse((out/'events.txt').read_text().splitlines(), pid), set(tids), pid, sample_callback)
    assert not result['quality'].get('foreign_samples', 0)
    assert result['quality']['complete_sample_pct'] > 99
    result['period'] = period
    h.c.save(out/'timeline.json', result)
    if before_cleanup is not None:
        before_cleanup()
    # Compact evidence and hashes precede immediate bulk removal.
    removed = []
    for p in (out/'perf.data', out/'events.txt'):
        removed.append(dict(path=str(p), bytes=p.stat().st_size, sha256=h.c.sha(p)))
    cleanup=dict(removed=removed,bytes_removed=sum(p['bytes'] for p in removed),
                 status='prepared',free_before=shutil.disk_usage(out).free)
    h.c.save(out/'cleanup.json',cleanup)
    for p in (out/'perf.data', out/'events.txt'):
        p.unlink()
    cleanup.update(status='complete',free_after=shutil.disk_usage(out).free)
    h.c.save(out/'cleanup.json',cleanup)
    print(json.dumps(dict(out=str(out), quality=result['quality'], median_run_us=result['median_run_us'])), flush=True)


def trial(spec):
    out = Path(spec['out']); out.mkdir(parents=True)
    h.c.space()
    binary = h.baseline('media', 'movie') if spec['arm'] == 'base' else h.c.S/'media_build/movie/fullset_coverage/MovieIdService'
    h.c.save(out/'protocol.json', dict(**spec, binary=str(binary), sha256=h.c.sha(binary),
        purpose='Exploratory time distribution, not a performance confirmation',
        family='media', pool=8, rate=600, tracing=1., other_services='baseline',
        warmup_s=50, duration_each_s=15))
    stack = client = None
    try:
        stack = h.start(out, 'media', {'movie':binary}, 8)
        pid = stack.states['movie-id-service']['State']['Pid']
        client = h.load(out/'load', 'media', 600, spec['seed'], 150)
        time.sleep(50)
        for period in spec['periods']:
            assert client.poll() is None
            capture(out/f'p{period}', pid, period)
            time.sleep(3)
        assert client.poll() is None, 'load ended before diagnostics finished'
        rc = client.wait(timeout=160); client = None
        stack.check()
        info = json.loads((out/'load/load.json').read_text())
        assert rc == 0 and not info['steady_errors'] and not info['steady_drops']
        with gzip.open(out/'load/requests.json.gz', 'rt') as source:
            samples = json.load(source)
        start = json.loads((out/'load/started.json').read_text())['epoch']
        latencies = sorted((end-begin)*1000 for begin, end in samples if start+50 <= end < start+145)
        h.c.save(out/'load_validation.json', dict(valid=True, load=info, diag_p99_ms=latencies[int(.99*(len(latencies)-1))],
            note='Diagnostic workload health only; includes profiling and cannot establish latency effect'))
    except BaseException as error:
        h.c.save(out/'failure.json', dict(error=repr(error)))
        raise
    finally:
        h.c.stop(client)
        if stack is not None:
            stack.close()
        h.old.compact(out)
    # Decode only after the workload has completed and services have stopped.
    # It cannot consume offered-load time or perturb the next recording.
    for period in spec['periods']:
        decode_capture(out/f'p{period}')
    h.c.save(out/'complete.json', dict(valid=True, load_validation=json.loads((out/'load_validation.json').read_text()),
                                      periods=spec['periods']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['campaign', 'trial'])
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text())
    if args.action == 'trial':
        trial(spec)
    else:
        root = Path(spec['out']); root.mkdir(parents=True, exist_ok=False)
        sources = root/'sources'; sources.mkdir(exist_ok=True)
        source_paths = [Path(__file__), Path(__file__).with_name('wake_miss_timeline.py'),
                        Path(h.__file__), Path(h.old.__file__)]
        source_paths += [h.HARNESS/name for name in ('common.py', 'media.py', 'load.py', 'run_platform.py', 'platform_context.py', 'tracing_config.py')]
        for path in source_paths:
            (sources/path.name).write_bytes(path.read_bytes())
        h.c.save(root/'source_hashes.json', {str(p):h.c.sha(p) for p in source_paths})
        h.c.save(root/'protocol.json', dict(**spec, admission='No loss/throttle, dynamic thread lifetimes from task records, >99% complete-run sample joins, valid load',
            selection='Baseline and retained MovieId candidate; both sample periods regardless of result; no best-bin selection'))
        for arm, periods in [('base', [257, 1021]), ('new', [1021, 257])]:
            out = root/arm
            manifest = root/(arm+'.json')
            h.c.save(manifest, dict(out=str(out), arm=arm, seed=17001, periods=periods))
            h.platform(out, ['python3', Path(__file__), 'trial', manifest])
        h.c.save(root/'complete.json', dict(complete=True, arms=['base', 'new']))


if __name__ == '__main__':
    main()
