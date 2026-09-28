"""Do not remove the only hint on an alternative CFG path."""
import os
from pathlib import Path
import subprocess
import pytest


@pytest.mark.parametrize('dominating_hint', [False, True])
def test_duplicate_elimination_requires_dominating_emission(tmp_path, dominating_hint):
    plugin = os.environ.get('DOMINATOR_TEST_PLUGIN')
    if not plugin:
        pytest.skip('Set DOMINATOR_TEST_PLUGIN to the built plugin')
    source = tmp_path/'paths.ll'
    entry = '''%e = load volatile i32, ptr %p
  %e1 = add i32 %e, 1
  store volatile i32 %e1, ptr %p
  call void @target()''' if dominating_hint else ''
    source.write_text('''target triple = "x86_64-unknown-linux-gnu"
declare void @target()
define void @branching(i1 %take, ptr %p) {
entry:
  '''+entry+'''
  br i1 %take, label %left, label %right
left:
  %l = load volatile i32, ptr %p
  %l1 = add i32 %l, 3
  store volatile i32 %l1, ptr %p
  call void @target()
  ret void
right:
  %r = load volatile i32, ptr %p
  %r1 = add i32 %r, 5
  store volatile i32 %r1, ptr %p
  call void @target()
  ret void
}
''')
    profile = tmp_path/'targets.txt';profile.write_text('target\n')
    env = dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAN='1',
        PREFETCHIT_DOM_SCHED_GATE='0',PREFETCHIT_DOM_LEAD='2',
        PREFETCHIT_DOM_MIN_FUNCTION='0',PREFETCHIT_DOM_MAX_SITES='4',
        PREFETCHIT_DOM_BATCH='8',PREFETCHIT_DOM_CALLER_TARGETS='0',
        PREFETCHIT_DOM_CALLEE_ONLY='1',PREFETCHIT_DOM_CALLEE_PROFILE=str(profile),
        PREFETCHIT_COLD_DIRECT_IN_PIC='1')
    counts = []
    for path_aware in (False,True):
        out = tmp_path/('path.ll' if path_aware else 'legacy.ll')
        subprocess.run(['opt-19','-load-pass-plugin='+plugin,
            '-passes=prefetchit-inject,verify','-S',str(source),'-o',str(out)],
            env=dict(env,PREFETCHIT_DOM_PATH_DEDUP=str(int(path_aware))),check=True)
        counts.append(out.read_text().count('prefetcht1'))
    assert counts == ([1,1] if dominating_hint else [1,2])
