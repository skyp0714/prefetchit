#!/usr/bin/env python3
"""Train distributed code prefetches separately from fresh-stack E2E trials.

One small hint replaces an executed padding NOP; preceding retired branches
select a later miss line. This advances with the application's execution,
including later parts of a scheduling slice, without timer interrupts.
"""
import argparse
import collections
import gzip
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

import fullset as h


def capture(spec):
    out = Path(spec['out']); out.mkdir(parents=True, exist_ok=False)
    h.c.space()
    h.c.save(out/'protocol.json', dict(**spec, event='FRONTEND_RETIRED.L2_MISS',
        purpose='Training and held-out placement evidence only, never performance evidence',
        scope='Target cgroups include dynamically created threads', period=257,
        lead='Retired LBR cycles are a proxy, not a measured instruction-fetch deadline'))
    stack = client = None
    captures = []
    try:
        stack = h.start(out, spec['family'], {}, spec['pool'])
        seconds = 65 + 24 * len(h.TARGETS[spec['family']])
        client = h.load(out/'load', spec['family'], spec['rate'], spec['seed'], seconds)
        time.sleep(50)
        for phase in ('train', 'heldout'):
            for key, (name, exe, _) in h.TARGETS[spec['family']].items():
                h.c.space()
                dest = out/key/phase; dest.mkdir(parents=True)
                pid = stack.states[name]['State']['Pid']
                group = str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                (dest/'maps.txt').write_text(Path(f'/proc/{pid}/maps').read_text())
                command = ['perf', 'record', '--no-buildid', '--no-buildid-cache',
                    '-a', '-C', f'32-{31+spec["pool"]}', '-m', '8M',
                    '-e', 'cpu/event=0xc6,umask=0x03,config1=0x13,period=257,name=fe_l2/upp',
                    '-j', 'any,u', '-G', group, '-o', str(dest/'perf.data'), '--', 'sleep', '10']
                h.c.save(dest/'identity.json', dict(pid=pid, cgroup=group, exe=exe,
                    binary=str(h.baseline(spec['family'], key)),
                    sha256=h.c.sha(h.baseline(spec['family'], key))))
                h.c.run(command, dest/'record.log')
                assert client.poll() is None
                assert not re.search(r'\b(lost|truncated|throttled)\b', (dest/'record.log').read_text(), re.I)
                captures.append(dest)
        rc = client.wait(timeout=120); client = None
        stack.check()
        info = json.loads((out/'load/load.json').read_text())
        h.c.save(out/'load_validation.json', dict(valid=rc == 0, load=info))
        assert rc == 0 and not info['steady_errors'] and not info['steady_drops']
    except BaseException as error:
        h.c.save(out/'failure.json', dict(error=repr(error)))
        raise
    finally:
        h.c.stop(client)
        if stack is not None: stack.close()
        h.old.compact(out)
    # No decoding or indexing overlaps workload execution.
    for dest in captures:
        command = ['perf', 'script', '-i', str(dest/'perf.data'), '-F', 'pid,ip,dso,brstack', '--show-lost-events']
        h.c.save(dest/'decode_command.json', command)
        with (dest/'samples.txt').open('w') as output, (dest/'decode.log').open('w') as error:
            subprocess.run(command, stdout=output, stderr=error, check=True)
        counts = collections.Counter()
        with (dest/'quality.log').open('w') as error:
            proc = subprocess.Popen(['perf', 'script', '-D', '-i', str(dest/'perf.data')],
                                    stdout=subprocess.PIPE, stderr=error, text=True)
            for line in proc.stdout:
                match = re.search(r'PERF_RECORD_(\w+)', line)
                if match: counts[match[1]] += 1
            assert proc.wait() == 0
        h.c.save(dest/'record_types.json', dict(counts))
        assert not any(counts[k] for k in ('LOST', 'LOST_SAMPLES', 'THROTTLE', 'UNTHROTTLE'))
        # Raw recording has served its purpose; decoded data remains active
        # only until all frozen placement variants and heldout audits exist.
        path = dest/'perf.data'
        h.c.save(dest/'raw_cleanup.json', dict(path=str(path), bytes=path.stat().st_size,
                                             sha256=h.c.sha(path), record_types=dict(counts)))
        path.unlink()
    h.c.save(out/'complete.json', dict(captures=[str(p) for p in captures]))


def campaign(spec):
    """Same-seed pairs, fresh stacks, no PMU recorder in latency trials."""
    from fullset_study import summarize
    out = Path(spec['out']); out.mkdir(parents=True, exist_ok=False)
    h.c.save(out/'protocol.json', dict(**spec, primary='external request planned-arrival to completion mean/p99',
        capacity='Qualified offered rate with zero steady errors/drops and p99 <= 20 ms; fixed-rate achieved RPS alone is not capacity',
        analysis='Paired log cost ratios; individual two-sided 95% t intervals',
        invalid='Retain operating failures; never retry a slow run based on its latency'))
    rows = []; names = list(spec['arms'])
    for block in range(spec['blocks']):
        order = names[block % len(names):] + names[:block % len(names)]
        if block // len(names) % 2: order.reverse()
        for arm in order:
            dest = out/f'{block:02d}_{arm}'
            setting = spec['arms'][arm]
            trial = dict(out=str(dest), family=spec['family'], pool=spec['pool'], rate=spec['rate'],
                seed=spec['seedbase']+block, overrides=setting.get('overrides', {}), pmu=[])
            if 'kernel' in setting: trial['kernel'] = setting['kernel']
            manifest = dest.with_suffix('.json'); h.c.save(manifest, trial)
            h.platform(dest, ['python3', Path(h.__file__), 'trial', manifest])
            r = json.loads((dest/'result.json').read_text()); p = r['pool']
            metrics = {k:p[k] for k in ('mean_ms', 'p50_ms', 'p95_ms', 'p99_ms')}
            metrics['stack_cpu'] = r['whole_stack_cpu_us_per_request']
            row = dict(block=block, arm=arm, valid=r['valid'], metrics=metrics,
                qualified_20ms=r['valid'] and p['p99_ms'] <= 20,
                achieved_rps=p['achieved_rps'], pool_util_pct=r['pool_util_pct'], output=str(dest))
            rows.append(row); h.c.save(out/'rows.json', rows)
            h.c.save(out/'summary.json', summarize(rows, spec['arms']))
            print(json.dumps(row), flush=True)
    h.c.save(out/'complete.json', dict(rows=len(rows), summary=summarize(rows, spec['arms'])))


def remove_generated(paths, record, reason):
    """Only caller-enumerated experiment files; never follow a symlink."""
    rows = []
    for path in paths:
        assert path.is_file() and not path.is_symlink() and path.resolve() == path
        rows.append(dict(path=str(path), bytes=path.stat().st_size, sha256=h.c.sha(path)))
    result = dict(reason=reason, files=rows, bytes_removed=0,
                  free_before=shutil.disk_usage(record.parent).free, status='prepared')
    h.c.save(record, result)
    for row in rows:
        Path(row['path']).unlink(); result['bytes_removed'] += row['bytes']
    result.update(status='complete', free_after=shutil.disk_usage(record.parent).free)
    h.c.save(record, result)


def prepare(spec):
    out = Path(spec['out']); root = Path(spec['capture'])
    assert (root/'complete.json').exists(), 'training must finish before disassembly'
    out.mkdir(parents=True, exist_ok=False); h.c.space()
    variants = spec['variants']; arms = {'base':{}}
    tools = h.REPO/'llvm_prefetchit/tools'
    obsolete = []
    for key, (_, exe, _) in h.TARGETS[spec['family']].items():
        source = h.baseline(spec['family'], key)
        index = out/(key+'_index.json')
        h.c.run(['taskset', '-c', '84-85', 'python3', tools/'index_executable_padding.py', source, index],
                out/(key+'_index.log'))
        obsolete.append(index)
        for v in variants:
            h.c.space()
            dest = out/v['name']/exe; dest.parent.mkdir(exist_ok=True)
            command = ['taskset', '-c', '84-85', 'python3', tools/'lbr_padding_prefetch.py',
                source, index, root/key/'train/samples.txt', dest, '--dso', exe,
                '--maps', root/key/'train/maps.txt', '--min-lead', str(v['lead'][0]),
                '--max-lead', str(v['lead'][1]), '--budget', str(v['budget']),
                '--min-site-distance', '64', '--hint', v['hint'],
                '--heldout', root/key/'heldout/samples.txt', '--heldout-maps', root/key/'heldout/maps.txt']
            h.c.run(command, out/(key+'_'+v['name']+'.log'))
            arms.setdefault(v['name'], dict(overrides={}, controls=['base']))['overrides'][key] = str(dest)
        obsolete.extend(root/key/phase/'samples.txt' for phase in ('train', 'heldout'))
    h.c.save(out/'arms.json', arms)
    h.c.save(out/'protocol.json', spec)
    remove_generated(obsolete, out/'training_cleanup.json',
        'All frozen variants and independent heldout counts extracted; indexes regenerate from retained baseline, patch records retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'campaign', 'prepare'))
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    def interrupt(signum, frame): raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM, interrupt)
    globals()[args.action](json.loads(args.manifest.read_text()))


if __name__ == '__main__': main()
