"""Safety/placement checks for opt-in early-target prefetch modes."""
import os
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def transform(tmp_path, ir, config):
    opt = shutil.which('opt-19')
    plugin = ROOT/'build/PrefetchITPass.so'
    if not opt or not plugin.exists(): pytest.skip('LLVM 19 and built plugin required')
    source = tmp_path/'input.ll'; source.write_text(ir)
    env = {k:v for k,v in os.environ.items() if not k.startswith('PREFETCHIT_')}
    env.update(config)
    return subprocess.check_output([opt,f'-load-pass-plugin={plugin}',
        '-passes=prefetchit-inject,verify','-S',str(source),'-o','-'],env=env,text=True)


def test_indirect_prefetch_hoists_only_available_target(tmp_path):
    ir = '''
define void @invariant(ptr %fp, i32 %n) {
entry:
  br label %loop
loop:
  %i = phi i32 [0, %entry], [%next, %loop]
  call void %fp()
  %next = add i32 %i, 1
  %more = icmp slt i32 %next, %n
  br i1 %more, label %loop, label %exit
exit:
  ret void
}
define void @varying(ptr %table, i32 %n) {
entry:
  br label %loop
loop:
  %i = phi i32 [0, %entry], [%next, %loop]
  %slot = getelementptr ptr, ptr %table, i32 %i
  %fp = load ptr, ptr %slot
  call void %fp()
  %next = add i32 %i, 1
  %more = icmp slt i32 %next, %n
  br i1 %more, label %loop, label %exit
exit:
  ret void
}
'''
    out = transform(tmp_path,ir,{'PREFETCHIT_INDIRECT_EARLY':'1','PREFETCHIT_INDIRECT_MIN_LEAD':'0'})
    invariant, varying = out.split('define void @varying')
    assert invariant.count('prefetcht1') == 1
    assert 'freeze ptr %fp' in invariant
    assert invariant.index('prefetcht1') < invariant.index('br label %loop')
    assert 'prefetcht1' not in varying
    assert out.count('load ptr') == 1  # never speculate the per-iteration pointer load


def test_direct_prefetch_can_cross_dominating_branch(tmp_path):
    ir = '''
define void @target() { ret void }
define void @caller(i1 %condition) {
entry:
  br i1 %condition, label %taken, label %exit
taken:
  call void @target()
  br label %exit
exit:
  ret void
}
'''
    cfg = {'PREFETCHIT_CALLEE_BURST_LINES':'1','PREFETCHIT_CALLEE_BURST_LEAD':'32',
           'PREFETCHIT_CALLEE_BURST_MIN_CALLEE_INSNS':'1'}
    local = transform(tmp_path,ir,cfg)
    assert local.index('prefetcht1') > local.index('taken:')
    early = transform(tmp_path,ir,cfg | {'PREFETCHIT_CALLEE_DOMINATOR':'1'})
    assert early.index('prefetcht1') < early.index('br i1 %condition')
    assert early.count('call void @target()') == 1


def test_external_direct_prefetch_requires_explicit_link_assumption(tmp_path):
    ir = 'declare void @target()\ndefine void @caller() { call void @target()\n ret void }\n'
    cfg = {'PREFETCHIT_CALLEE_BURST_LINES':'1','PREFETCHIT_CALLEE_EXTERNAL':'1'}
    assert 'prefetcht1' not in transform(tmp_path,ir,cfg)
    enabled = transform(tmp_path,ir,cfg | {'PREFETCHIT_COLD_DIRECT_IN_PIC':'1'})
    assert '.weak target' not in enabled
    assert 'prefetcht1 target+0' in enabled


def test_schema_targets_move_to_caller_without_changing_calls(tmp_path):
    ir = '''
declare void @parent()
declare void @unrelated()
define void @caller(i1 %condition) {
entry:
  br i1 %condition, label %taken, label %exit
taken:
  call void @parent()
  call void @unrelated()
  br label %exit
exit:
  ret void
}
'''
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps({'sites':{'parent':{'t':[['child',0,0],['child',64,0]]}}}))
    cfg = {'PREFETCHIT_CALLEE_BURST_LINES':'1','PREFETCHIT_CALLEE_EXTERNAL':'1',
           'PREFETCHIT_CALLEE_DOMINATOR':'1','PREFETCHIT_CALLEE_BURST_LEAD':'128',
           'PREFETCHIT_CALLEE_TARGET_PLAN':str(plan)}
    assert 'prefetcht1' not in transform(tmp_path,ir,cfg)
    out = transform(tmp_path,ir,cfg | {'PREFETCHIT_COLD_DIRECT_IN_PIC':'1'})
    assert out.count('prefetcht1') == 2
    assert out.index('prefetcht1 child+64') < out.index('br i1 %condition')
    assert 'prefetcht1 parent' not in out and 'prefetcht1 unrelated' not in out
    assert out.count('call void @parent()') == 1
    assert out.count('call void @unrelated()') == 1
    assert '.weak' not in out
