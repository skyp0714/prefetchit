#!/usr/bin/env python3
"""Fresh-process SocialNetwork Class-B trials, qualification, and paired controls.

Reuses the archived September 26 full-stack harness; output is always a new tree.
Run as root through its run_platform.py wrapper (fixed 2 GHz, restored on exit).
"""
import argparse
import fcntl
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[3]
LEGACY = REPO / 'llvm_prefetchit/results/class_b_extension_20260926'
sys.path.insert(0, str(LEGACY))
import common as c
import social
import trace_media

spec = importlib.util.spec_from_file_location('kernel_control', REPO/'llvm_prefetchit/kernel/wake_prefetch/control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
OUT = Path('/storage/prefetchit/class_b_headroom_20260926')
TRACE = Path('/trace/prefetchit/class_b_headroom_20260926')
SERVICE = 'usertimeline'
NAME = 'user-timeline-service'
EXE = 'UserTimelineService'


def pool_cpu(cpus):
    ticks = {}
    for line in Path('/proc/stat').read_text().splitlines():
        fields = line.split()
        if fields and fields[0].startswith('cpu') and fields[0][3:].isdigit():
            cpu = int(fields[0][3:])
            if cpu in cpus:
                v = list(map(int, fields[1:]))
                ticks[cpu] = sum(v[i] for i in (0, 1, 2, 5, 6, 7))
    assert set(ticks) == set(cpus)
    return dict(epoch=time.time(), monotonic=time.monotonic(), ticks=ticks,
                clock_ticks=os.sysconf('SC_CLK_TCK'))


def attach(cost, samples):
    lat = sorted((end-start)*1000 for start, end in samples if cost['start'] <= end < cost['end'])
    assert lat
    cost.update(completed=len(lat), achieved_rps=len(lat)/cost['wall_s'],
                cpu_us_per_request=cost['cpu_us']/len(lat),
                mean_ms=math.fsum(lat)/len(lat), p50_ms=lat[int(.50*(len(lat)-1))],
                p95_ms=lat[int(.95*(len(lat)-1))], p99_ms=lat[int(.99*(len(lat)-1))])
    if 'user_us' in cost:
        cost['user_us_per_request'] = cost['user_us']/len(lat)
    return cost


def compact(out):
    removed = []
    for p in out.rglob('*'):
        if p.is_file() and not p.is_symlink() and p.name in {
            'requests.json.gz', 'up.log', 'backends_up.log', 'jaeger_up.log', 'down.log'}:
            removed.append(dict(path=str(p), bytes=p.stat().st_size, sha256=c.sha(p)))
    record=dict(removed=removed,bytes_removed=0,status='prepared',
                free_before=shutil.disk_usage(out).free,root_free_before=shutil.disk_usage('/').free)
    c.save(out/'compact_cleanup.json',record)
    for row in removed:
        Path(row['path']).unlink();record['bytes_removed']+=row['bytes']
    record.update(status='complete',free_after=shutil.disk_usage(out).free,
                  root_free_after=shutil.disk_usage('/').free)
    c.save(out/'compact_cleanup.json',record)


def start_stack(out, binary, pool, alone):
    stack = social.Stack(out, {SERVICE: binary})
    stack.project = 'codex-b-headroom-20260926'
    stack.dc = ['docker', 'compose', '-p', stack.project, '-f', str(out/'compose.json')]
    try:
        stack.start()
        for name in stack.states:
            cpus = '42-43' if alone and name == NAME else f'32-{31+pool}'
            subprocess.run(['docker', 'update', '--cpuset-cpus', cpus, stack.cid(name)],
                           check=True, stdout=subprocess.DEVNULL)
        stack.check()
    except BaseException:
        stack.close()
        raise
    return stack


def load(out, rate, seed, seconds):
    out.mkdir()
    command = ['python3', str(LEGACY/'load.py'), '--out', str(out), '--rate', str(rate),
               '--seconds', str(seconds), '--seed', str(seed), '--workload', 'social', '--port', '18082']
    c.save(out/'command.json', command)
    with (out/'client.log').open('w') as f:
        child = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(100):
        if (out/'started.json').exists():
            return child
        assert child.poll() is None
        time.sleep(.1)
    raise RuntimeError('load client did not start')


def trial(out, binary, pool, rate, seed, alone=False, kernel_plan=None, mode='off', pmu=True):
    c.space()
    out.mkdir(parents=True, exist_ok=False)
    binary = c.ensure_local(binary)
    c.save(out/'protocol.json', dict(binary=str(binary), binary_sha256=c.sha(binary), pool=pool,
        rate=rate, seed=seed, alone=alone, kernel_plan=str(kernel_plan), kernel_mode=mode,
        warmup_s=50, primary_s=30, pmu_s=20 if pmu else 0,
        primary='target user+kernel CPU/request; kernel requires additional pool/stack net savings',
        legacy_source_hashes={p.name:c.sha(p) for p in LEGACY.glob('*.py')}, harness_sha256=c.sha(__file__)))
    stack = None
    client = None
    fd = None
    module_loaded = False
    try:
        stack = start_stack(out, binary, pool, alone)
        target_pid = stack.states[NAME]['State']['Pid']
        if mode != 'off':
            assert not Path('/sys/module/wake_prefetch').exists()
            subprocess.run(['insmod', str(REPO/'llvm_prefetchit/kernel/wake_prefetch/wake_prefetch.ko')], check=True)
            module_loaded = True
            if mode != 'empty':
                plan = json.loads(kernel_plan.read_text())
                profiles, audit = control.resolve(plan, target_pid)
                c.save(out/'kernel_registration.json', dict(profiles=profiles, audit=audit,
                                                           plan_sha256=c.sha(kernel_plan)))
                fd = os.open('/dev/wake_prefetch', os.O_RDWR | os.O_CLOEXEC)
                fcntl.ioctl(fd, control.CONFIG_IOCTL,
                            control.pack_config(target_pid, int(mode == 't1'), profiles), True)
        client = load(out/'load', rate, seed, 110 if pmu else 95)
        time.sleep(50)
        assert client.poll() is None
        measured_cpus = set(range(32,32+pool)) | ({42,43} if alone else set())
        before = stack.accounts()
        pool_before = pool_cpu(measured_cpus)
        kernel_before = control.stats(fd) if fd is not None else None
        time.sleep(30)
        kernel_after = control.stats(fd) if fd is not None else None
        pool_after = pool_cpu(measured_cpus)
        after = stack.accounts()
        costs = {k:c.diff_cpu(before[k], after[k]) for k in before}
        pmu_cost = perf_result = None
        if pmu:
            begin = c.cpu(target_pid)
            group = str(Path(begin['path']).parent.relative_to('/sys/fs/cgroup'))
            command = ['perf','stat','-x,','-o',str(out/'pmu.csv'),'-e',c.EVENTS,
                       '-a','-C','32-43','-G',group,'--','sleep','20']
            c.run(command, out/'pmu.log')
            pmu_cost = c.diff_cpu(begin,c.cpu(target_pid))
            perf_result = c.counters(out/'pmu.csv')
        rc = client.wait(timeout=90)
        client = None
        stack.check()
        info = json.loads((out/'load/load.json').read_text())
        with gzip.open(out/'load/requests.json.gz','rt') as f:
            samples = json.load(f)
        target = attach(costs[NAME],samples)
        total_cpu = sum(x['cpu_us'] for x in costs.values())
        pool = attach(dict(start=pool_before['epoch'],end=pool_after['epoch'],
            wall_s=pool_after['monotonic']-pool_before['monotonic'],
            cpu_us=sum(pool_after['ticks'][k]-v for k,v in pool_before['ticks'].items())*1e6/pool_before['clock_ticks']),samples)
        result = dict(target=target, whole_stack_cpu_us_per_request=total_cpu/target['completed'],
            pool=pool, pool_util_pct=100*pool['cpu_us']/(pool['wall_s']*1e6*len(measured_cpus)),
            load=info, kernel_before=kernel_before, kernel_after=kernel_after,
            binary=str(binary), binary_sha256=c.sha(binary), mode=mode, pmu=None)
        valid = rc == 0 and info['steady_errors'] == 0 and not info['steady_drops']
        valid &= abs(target['achieved_rps']/rate-1)<.04 and target['p99_ms']<100
        if pmu:
            pmu_cost = attach(pmu_cost,samples)
            co = perf_result['counters']
            result['pmu'] = dict(**perf_result, window=pmu_cost,
                user_cycles_per_request=co['cycles:u']/pmu_cost['completed'],
                code_misses_per_request=co['L2I']/pmu_cost['completed'])
            valid &= perf_result['fully_scheduled'] and abs(pmu_cost['achieved_rps']/rate-1)<.04
        if kernel_after is not None:
            valid &= kernel_after['matched_switches']>kernel_before['matched_switches']
        result['valid'] = bool(valid)
        c.save(out/'result.json',result)
        print(json.dumps(dict(output=str(out),valid=result['valid'],cpu=target['cpu_us_per_request'],
            pool_cpu=pool['cpu_us_per_request'],mpki=perf_result['mpki'] if pmu else None,p99=target['p99_ms'])),flush=True)
        return result
    except BaseException as error:
        c.save(out/'failure.json', dict(error=repr(error)))
        raise
    finally:
        c.stop(client)
        if fd is not None:
            os.close(fd)
        if module_loaded:
            subprocess.run(['rmmod','wake_prefetch'],check=True)
        if stack is not None:
            stack.close()
        if (out/'result.json').exists():
            compact(out)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--pool',type=int,choices=(4,6,8),default=8)
    p.add_argument('--rate',type=int,default=600)
    p.add_argument('--seed',type=int,default=5001)
    p.add_argument('--alone',action='store_true')
    p.add_argument('--binary',type=Path,default=c.S/'social_build/usertimeline/base'/EXE)
    p.add_argument('--kernel-plan',type=Path)
    p.add_argument('--kernel-mode',choices=('off','empty','nop','t1'),default='off')
    p.add_argument('--no-pmu',action='store_true')
    a=p.parse_args()
    if os.geteuid(): p.error('root and the fixed-platform wrapper are required')
    if a.kernel_mode in ('nop','t1') and not a.kernel_plan: p.error('kernel plan required')
    def interrupt(signum,frame): raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupt)
    trial(a.out,a.binary,a.pool,a.rate,a.seed,a.alone,a.kernel_plan,a.kernel_mode,not a.no_pmu)


if __name__=='__main__':main()
