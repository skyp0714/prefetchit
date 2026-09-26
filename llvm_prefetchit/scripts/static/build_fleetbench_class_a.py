#!/usr/bin/env python3
"""Build comparable FleetBench proto variants using the existing LLVM pass.

No workload or source changes. Bazel's opt configuration and clang-19 are shared
by every arm; only the pass and its explicit action environment vary. Preserve
each result before the next Bazel build replaces its outputs.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
CONFIGS = {
    'base': {},
    'seq4k80': {'PREFETCHIT_SEQ_DISTANCE': '4096', 'PREFETCHIT_SEQ_STRIDE_INSNS': '80',
                'PREFETCHIT_SEQ_MIN_INSNS': '512'},
    'burst2lead32': {'PREFETCHIT_CALLEE_BURST_LINES': '2',
                      'PREFETCHIT_CALLEE_BURST_LEAD': '32',
                      'PREFETCHIT_CALLEE_BURST_MIN_CALLEE_INSNS': '64'},
    'cold_static': {'PREFETCHIT_COLD_DIRECT_IN_PIC': '1'},
    'cold_trace': {'PREFETCHIT_COLD_DIRECT_IN_PIC': '1'},
    'cold_trace_cost': {'PREFETCHIT_COLD_DIRECT_IN_PIC': '1'},
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--jobs', type=int, default=24)
    ap.add_argument('--plan', type=Path)
    ap.add_argument('--config', type=Path, help='explicit PREFETCHIT_* environment JSON for a new policy')
    ap.add_argument('arm')
    a = ap.parse_args(); out = a.out.resolve()
    if not re.fullmatch(r'[a-zA-Z0-9_]+', a.arm): ap.error('arm must be an alphanumeric identifier')
    if a.arm not in CONFIGS and not a.config: ap.error('unknown arm requires --config')
    for d in ('bin', 'build'): (out/d).mkdir(parents=True, exist_ok=True)
    binary = out/'bin'/a.arm
    if binary.exists(): ap.error('arm already exists; use a fresh result directory')
    plugin=ROOT/'llvm_prefetchit/build/PrefetchITPass.so'
    config=json.loads(a.config.read_text()) if a.config else dict(CONFIGS[a.arm])
    if not isinstance(config,dict) or any(not k.startswith('PREFETCHIT_') or not isinstance(v,str) for k,v in config.items()):
        ap.error('config must map PREFETCHIT_* names to strings')
    if a.plan or a.arm.startswith('cold_'):
        if not a.plan or not a.plan.is_file(): ap.error('cold arms require --plan')
        if not json.loads(a.plan.read_text()).get('sites'): ap.error('plan is empty')
        config['PREFETCHIT_COLD_PLAN'] = str(a.plan.resolve())
    cmd=['bazel','build','-c','opt','--repo_env=CC=/usr/bin/clang',
         '--repo_env=CXX=/usr/bin/clang++',f'--jobs={a.jobs}','--copt=-gline-tables-only']
    if config:
        cmd += [f'--copt=-fpass-plugin={plugin}']
        # Bazel does not otherwise track the plugin referenced by a compiler flag.
        cmd += [f'--action_env=PREFETCHIT_PLUGIN_SHA256={hashlib.sha256(plugin.read_bytes()).hexdigest()}']
        cmd += [f'--action_env={k}={v}' for k,v in config.items()]
    cmd += ['//fleetbench/proto:proto_benchmark']
    (out/'build'/f'{a.arm}.command.json').write_text(json.dumps(cmd,indent=2))
    with (out/'build'/f'{a.arm}.log').open('w') as log:
        subprocess.run(cmd,cwd=ROOT/'benchmarks/fleetbench',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
    shutil.copy2(ROOT/'benchmarks/fleetbench/bazel-bin/fleetbench/proto/proto_benchmark',binary)
    dis=subprocess.check_output(['objdump','-d','--no-show-raw-insn',str(binary)],text=True)
    counts={m:sum(f'\t{m} ' in line for line in dis.splitlines()) for m in ('prefetcht0','prefetcht1','prefetcht2','prefetchnta')}
    meta={'config':config,'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
          'prefetch_counts':counts,'pass_sha256':hashlib.sha256(plugin.read_bytes()).hexdigest()}
    (out/'build'/f'{a.arm}.json').write_text(json.dumps(meta,indent=2))
    print(a.arm,meta,flush=True)
    if config:
        # The upstream protobuf runtime has pre-existing data PREFETCHT0s.
        # Remove only PREFETCHT1 (verified absent in base) for the code-PF twin.
        subprocess.run(['python3',str(ROOT/'llvm_prefetchit/tools/make_nop_control_binary.py'),
                        '--input',str(binary),'--output',str(binary)+'_nop',
                        '--mnemonics','prefetcht1'],check=True)


if __name__ == '__main__': main()
