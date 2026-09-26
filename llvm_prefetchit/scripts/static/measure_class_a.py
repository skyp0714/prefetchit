#!/usr/bin/env python3
"""Bounded Class-A measurements; run with sudo. Restore every changed sysfs value.

Examples:
  sudo python3 measure_class_a.py --out RESULTS/profile --profile BIN
  sudo python3 measure_class_a.py --out RESULTS/ab --reps 5 base=BIN seq=BIN twin=BIN
FleetBench uses its upstream Arena workload and fixed operation counts. Profiling
and timing are separate processes. No system-wide perf permission changes.
"""
import argparse
import contextlib
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import time


def write(p, value):
    Path(p).write_text(str(value) + '\n')


@contextlib.contextmanager
def platform(cpu, out):
    policy = Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq')
    uncore = Path('/sys/devices/system/cpu/intel_uncore_frequency')
    nodes = [policy / x for x in ('scaling_governor', 'scaling_min_freq',
             'scaling_max_freq', 'energy_performance_preference') if (policy / x).exists()]
    turbo = Path('/sys/devices/system/cpu/intel_pstate/no_turbo')
    nodes += [turbo] if turbo.exists() else []
    domains = sorted(uncore.glob('uncore*'))
    for d in domains:
        nodes += [d / 'min_freq_khz', d / 'max_freq_khz']
    states = [s / 'disable' for s in Path(f'/sys/devices/system/cpu/cpu{cpu}/cpuidle').glob('state*')
              if (s / 'name').read_text().strip().startswith('C6')]
    nodes += states
    saved = {str(p): p.read_text().strip() for p in nodes}
    msr_path = Path(f'/dev/cpu/{cpu}/msr')
    with msr_path.open('rb', buffering=0) as f:
        hwp_before = os.pread(f.fileno(), 8, 0x774)
    (out / 'hwp_before.json').write_text(json.dumps({'cpu': cpu, 'msr_0x774': hwp_before.hex()}))
    (out / 'platform_before.json').write_text(json.dumps(saved, indent=2))
    try:
        if turbo.exists(): write(turbo, 1)
        write(policy / 'scaling_governor', 'performance')
        if (policy / 'energy_performance_preference').exists():
            write(policy / 'energy_performance_preference', 'performance')
        write(policy / 'scaling_min_freq', 800000)
        write(policy / 'scaling_max_freq', 2000000)
        write(policy / 'scaling_min_freq', 2000000)
        subprocess.run(['x86_energy_perf_policy','--cpu',str(cpu),'--hwp-min','20',
                        '--hwp-max','20','--hwp-desired','20','--hwp-epp','0'],check=True,
                       stdout=subprocess.DEVNULL)
        for d in domains: write(d / 'min_freq_khz', saved[str(d / 'max_freq_khz')])
        for p in states: write(p, 1)
        (out / 'platform_frozen.json').write_text(json.dumps({str(p): p.read_text().strip() for p in nodes}, indent=2))
        yield
    finally:
        # Restore global turbo first, then the measured core's original bounds.
        if turbo.exists(): write(turbo, saved[str(turbo)])
        write(policy / 'scaling_min_freq', 800000)
        write(policy / 'scaling_max_freq', saved[str(policy / 'scaling_max_freq')])
        write(policy / 'scaling_min_freq', saved[str(policy / 'scaling_min_freq')])
        write(policy / 'scaling_governor', saved[str(policy / 'scaling_governor')])
        for p in nodes:
            if p in [turbo, policy / 'scaling_min_freq', policy / 'scaling_max_freq', policy / 'scaling_governor']: continue
            write(p, saved[str(p)])
        with msr_path.open('r+b', buffering=0) as f:
            os.pwrite(f.fileno(), hwp_before, 0x774)
            hwp_after = os.pread(f.fileno(), 8, 0x774)
        (out / 'hwp_restored.json').write_text(json.dumps({'cpu': cpu, 'msr_0x774': hwp_after.hex()}))
        after = {str(p): p.read_text().strip() for p in nodes}
        (out / 'platform_restored.json').write_text(json.dumps(after, indent=2))
        if 'SUDO_UID' in os.environ:
            uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
            for p in [out, *out.rglob('*')]: os.chown(p, uid, gid, follow_symlinks=False)
        if after != saved or hwp_after != hwp_before:
            raise RuntimeError('platform restore mismatch')


def run(cmd, log, timeout=180):
    with open(log, 'w') as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True, timeout=timeout)


def perf_values(path):
    values = {}
    for row in csv.reader(open(path)):
        if len(row) < 3 or row[0].startswith('#'): continue
        try: values[row[2]] = float(row[0])
        except ValueError: continue
    return values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--cpu', type=int, default=36)
    ap.add_argument('--iterations', type=int, default=100)
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--benchmark', choices=['BM_PROTO_Arena','BM_PROTO_NoArena'], default='BM_PROTO_Arena')
    ap.add_argument('--profile', type=Path)
    ap.add_argument('--trace', action='store_true')
    ap.add_argument('--instruction-trace', action='store_true',
                    help='with --profile: cache counters then precise instruction sampling for prefetch cost')
    ap.add_argument('--latency-profile', action='store_true',
                    help='with --profile: also measure FE starvation excluding backend stalls')
    ap.add_argument('arms', nargs='*')
    a = ap.parse_args()
    if a.iterations <= 0 or a.reps <= 0: ap.error('iterations and reps must be positive')
    if not a.profile and not a.arms: ap.error('provide --profile or at least one named arm')
    if a.profile and a.arms: ap.error('profiling and timing arms must be separate')
    if a.instruction_trace and (not a.profile or a.trace):
        ap.error('--instruction-trace requires --profile and excludes --trace')
    if a.latency_profile and (not a.profile or a.instruction_trace):
        ap.error('--latency-profile requires --profile and excludes --instruction-trace')
    if os.geteuid() != 0: ap.error('run with sudo (perf and temporary sysfs controls)')
    a.out.mkdir(parents=True, exist_ok=True)
    if (a.out / 'platform_before.json').exists(): ap.error('use a new output directory; runs are immutable')
    def interrupted(signum, frame): raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    def command(binary, iterations=None):
        return ['taskset', '-c', str(a.cpu), str(Path(binary).resolve()),
                f'--benchmark_filter=^{a.benchmark}$',
                f'--benchmark_min_time={iterations or a.iterations}x',
                f'--seed={a.seed}', '--benchmark_format=json']
    arms = dict(s.split('=', 1) for s in a.arms)
    for binary in ([a.profile] if a.profile else list(arms.values())):
        if not Path(binary).is_file(): ap.error(f'binary does not exist: {binary}')
    manifest = {'arguments': vars(a) | {'out': str(a.out), 'profile': str(a.profile)},
                'arms': {k: {'path': str(Path(v).resolve()), 'sha256': hashlib.sha256(Path(v).read_bytes()).hexdigest()} for k, v in arms.items()}}
    if a.profile:
        manifest['profile_sha256'] = hashlib.sha256(a.profile.read_bytes()).hexdigest()
    (a.out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    events = 'instructions:u,cycles:u,ref-cycles:u,cpu/event=0x24,umask=0x24,name=L2_CODE_MISS/u,cpu/event=0x24,umask=0x28,name=SWPF_MISS/u,cpu/event=0x24,umask=0xc8,name=SWPF_HIT/u,task-clock,context-switches,cpu-migrations'
    with platform(a.cpu, a.out):
        if a.profile:
            groups = {
                'cache': events,
                'topdown': '{slots:u,topdown-retiring:u,topdown-bad-spec:u,topdown-fe-bound:u,topdown-be-bound:u,topdown-fetch-lat:u,topdown-br-mispredict:u}',
                'frontend': 'instructions:u,cycles:u,cpu/event=0x80,umask=0x04,name=ICACHE_DATA_STALL/u,cpu/event=0x60,umask=0x01,name=BACLEAR/u,cpu/event=0x11,umask=0x10,cmask=1,name=ITLB_WALK_ACTIVE/u,branch-misses:u',
                'retired_l2': 'cpu/event=0xc6,umask=0x03,config1=0x13,name=FE_RETIRED_L2/u,instructions:u,cycles:u',
            }
            if a.instruction_trace: groups = {'cache': events}
            if a.latency_profile:
                # Intel GNR FRONTEND_RETIRED LATENCY_GE_N: no-uop intervals
                # uninterrupted by a backend stall. Different MSR 0x3f7 values
                # need separate runs, not a multiplexed event group.
                for threshold in (16,32,64,128):
                    config = 0x600006 + (threshold << 8)
                    groups[f'latency{threshold}'] = (
                        f'cpu/event=0xc6,umask=0x03,config1={config:#x},name=FE_LATENCY_GE_{threshold}/u,instructions:u,cycles:u')
                groups['backend'] = ('instructions:u,cycles:u,'
                    'cpu/event=0xa3,umask=0x04,cmask=4,name=EXEC_STALL/u,'
                    'cpu/event=0xa3,umask=0x05,cmask=5,name=STALL_L2_DATA_MISS/u,'
                    'cpu/event=0xa3,umask=0x0c,cmask=12,name=STALL_L1D_MISS/u,'
                    'cpu/event=0x9c,umask=0x01,cmask=6,name=FE_ZERO_UOPS_BE_READY/u')
            for name, ev in groups.items():
                run(['perf','stat','-x,','-o',str(a.out / f'{name}.csv'),'-e',ev,'--'] + command(a.profile), a.out / f'{name}.log')
                print(name, perf_values(a.out / f'{name}.csv'), flush=True)
            if a.instruction_trace:
                run(['perf','record','-o',str(a.out/'instructions.data'),'-e','instructions:upp',
                     '-c','20003','--'] + command(a.profile), a.out/'instructions.log')
                run(['perf','script','-i',str(a.out/'instructions.data'),'--show-mmap-events',
                     '-F','ip,dso'],a.out/'instructions.txt')
            if a.trace:
                # Use the retired frontend event, verified nonzero on this boot.
                run(['perf','record','-o',str(a.out/'lbr.data'),'-e','cpu/event=0xc6,umask=0x03,config1=0x13/upp','-c','1009','-b','--'] + command(a.profile, 30), a.out/'lbr.log')
                run(['perf','script','-i',str(a.out/'lbr.data'),'-F','ip,dso,brstack'],a.out/'samples_lbr.txt')
        else:
            rng = random.Random(20260922)
            fieldnames = ['arm','rep','iterations','cpu_ns_per_op','real_ns_per_op','instructions','cycles','ref_cycles','l2_code_misses','l2_mpki','swpf_miss','swpf_hit','user_ghz','elapsed_s']
            with open(a.out/'runs.csv','w') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader()
                for rep in range(1,a.reps+1):
                    order = list(arms); rng.shuffle(order)
                    for arm in order:
                        stem = f'{rep:02d}_{arm}'
                        pf = a.out/f'{stem}.perf.csv'
                        before=time.monotonic()
                        run(['perf','stat','-x,','-o',str(pf),'-e',events,'--']+command(arms[arm]), a.out/f'{stem}.log')
                        log=(a.out/f'{stem}.log').read_text(); start=log.index('{')
                        data, _=json.JSONDecoder().raw_decode(log[start:]); b=data['benchmarks'][0]
                        if len(data['benchmarks']) != 1 or b['name'] != a.benchmark:
                            raise RuntimeError('benchmark selection differs from requested workload')
                        if b.get('error_occurred'): raise RuntimeError(b)
                        if b['iterations'] != a.iterations: raise RuntimeError('iteration count differs from requested work')
                        multiplier={'ns':1,'us':1000,'ms':1000000,'s':1000000000}[b['time_unit']]
                        p=perf_values(pf); ins=p['instructions:u']; cyc=p['cycles:u']; miss=p['L2_CODE_MISS']
                        if min(ins,cyc)<=0: raise RuntimeError('invalid perf counts')
                        ghz=cyc/(p['task-clock']*1e6)
                        if not 1.90 <= ghz <= 2.05: raise RuntimeError(f'core clock validation failed: {ghz:.3f} GHz')
                        row=dict(arm=arm,rep=rep,iterations=b['iterations'],cpu_ns_per_op=b['cpu_time']*multiplier,real_ns_per_op=b['real_time']*multiplier,instructions=ins,cycles=cyc,ref_cycles=p['ref-cycles:u'],l2_code_misses=miss,l2_mpki=1000*miss/ins,swpf_miss=p['SWPF_MISS'],swpf_hit=p['SWPF_HIT'],user_ghz=ghz,elapsed_s=time.monotonic()-before)
                        writer.writerow(row); f.flush(); print(json.dumps(row),flush=True)


if __name__ == '__main__':
    main()
