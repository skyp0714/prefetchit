#!/usr/bin/env python3
"""Fixed-work Class-A transfer tests using the same 2 GHz platform controls.

ARM frontend uses the upstream -l loop argument. Verilator uses its established
fixed-cycle qsort prefix; a timeout is expected and checked, not called a full
qsort completion. Build all variants before starting measurements.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import time

from measure_class_a import platform, perf_values


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--workload', choices=['arm', 'verilator', 'arcilator'], required=True)
    p.add_argument('--work', type=int, required=True, help='loops or simulated cycles')
    p.add_argument('--payload', type=Path)
    p.add_argument('--cpu', type=int, default=36)
    p.add_argument('--reps', type=int, default=3)
    p.add_argument('arms', nargs='+')
    a = p.parse_args()
    if os.geteuid() != 0 or min(a.work, a.reps) <= 0: p.error('root and positive work/reps required')
    if a.workload == 'verilator' and (not a.payload or not a.payload.is_file()): p.error('payload required')
    a.out.mkdir(parents=True, exist_ok=True)
    if (a.out / 'manifest.json').exists(): p.error('output already used')
    arms = dict(x.split('=', 1) for x in a.arms)
    manifest = {'arguments': vars(a), 'binaries': {n: {'path': str(Path(b).resolve()),
                'sha256': hashlib.sha256(Path(b).read_bytes()).hexdigest()} for n,b in arms.items()}}
    if a.payload: manifest['payload_sha256'] = hashlib.sha256(a.payload.read_bytes()).hexdigest()
    (a.out / 'manifest.json').write_text(json.dumps(manifest, default=str, indent=2))
    def interrupted(signum, frame): raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    events = 'instructions:u,cycles:u,ref-cycles:u,cpu/event=0x24,umask=0x24,name=L2_CODE_MISS/u,task-clock,context-switches,cpu-migrations'
    fields = ['arm','rep','work','cpu_s','wall_s','instructions','cycles','l2_code_misses','l2_mpki','user_ghz','returncode','output_sha256']
    with platform(a.cpu, a.out), (a.out / 'runs.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        rng = random.Random(20260922)
        for rep in range(1,a.reps+1):
            order = list(arms); rng.shuffle(order)
            for arm in order:
                stem = a.out / f'{rep:02d}_{arm}'
                args = (['-l',str(a.work)] if a.workload == 'arm' else [str(a.work)] if a.workload == 'arcilator' else [str(a.payload.resolve()),f'+max-cycles={a.work}'])
                cmd = ['perf','stat','-x,','-o',str(stem)+'.perf.csv','-e',events,'--','taskset','-c',str(a.cpu),str(Path(arms[arm]).resolve())] + args
                before = time.monotonic()
                with open(str(stem)+'.log','w') as log:
                    result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=900)
                elapsed = time.monotonic()-before
                output = Path(str(stem)+'.log').read_text()
                if a.workload == 'arm':
                    if result.returncode: raise RuntimeError(output)
                elif a.workload == 'arcilator':
                    if result.returncode or output.strip() != f'cycles={a.work}':
                        raise RuntimeError('arcilator cycle completion mismatch: '+output)
                elif '(timeout)' not in output or not re.search(rf'after\s+{a.work + 1}\s+simulation cycles',output):
                    raise RuntimeError('simulator did not reach requested cycle count: '+output)
                perf = Path(str(stem)+'.perf.csv')
                for row in csv.reader(perf.open()):
                    if len(row)>4 and row[2] in ['instructions:u','cycles:u','L2_CODE_MISS']:
                        if row[0].startswith('<') or float(row[4]) < 99.99: raise RuntimeError('unsupported/multiplexed counter')
                v = perf_values(perf); ins=v['instructions:u']; cyc=v['cycles:u']; miss=v['L2_CODE_MISS']; cpu=v['task-clock']/1000
                ghz=cyc/cpu/1e9
                if not 1.90 <= ghz <= 2.05: raise RuntimeError(f'clock out of range {ghz}')
                row = dict(arm=arm,rep=rep,work=a.work,cpu_s=cpu,wall_s=elapsed,instructions=ins,cycles=cyc,l2_code_misses=miss,l2_mpki=1000*miss/ins,user_ghz=ghz,returncode=result.returncode,output_sha256=hashlib.sha256(output.encode()).hexdigest())
                writer.writerow(row); f.flush(); print(json.dumps(row),flush=True)


if __name__ == '__main__': main()
