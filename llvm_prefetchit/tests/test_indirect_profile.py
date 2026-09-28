from pathlib import Path
import json
import os
import subprocess
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from indirect_profile import select, aggregate


def test_indirect_ranking_filters_rare_edges_and_has_stable_ties():
    counts = {('caller', 'hot'): 20, ('caller', 'rare'): 2,
              ('caller', 'b'): 4, ('caller', 'a'): 4, ('other', 'x'): 3}
    assert select(counts, 2, 3) == {'caller': ['hot', 'a'], 'other': ['x']}
    with pytest.raises(ValueError):
        select(counts, 9, 1)


def test_alias_callers_do_not_duplicate_retained_edge_events(tmp_path, monkeypatch):
    import indirect_profile as module
    binary = tmp_path/'Main';binary.write_bytes(b'identity')
    (tmp_path/'dsos.json').write_text(json.dumps({'/custom/Main':{'sha256':module.b.sha(binary)}}))
    (tmp_path/'maps.txt').write_text('fixture')
    phase = tmp_path/'train';phase.mkdir()
    sample = '123 81 (/custom/Main) 0x40 (/custom/Main)/0x80 (/custom/Main)/P/-/-/20/IND_CALL/\n'
    (phase/'samples.txt').write_text(sample*101)
    (phase/'record_types.json').write_text(json.dumps({'SAMPLE':101}))
    monkeypatch.setattr(module, 'mapping_bias', lambda *args: 0)
    class Code:
        sections = []
        def straight(self, low, high):return True
        def get(self, va):return (2, 'call *%rax', 'caller')
    ranges = [dict(start=0x40,end=0x70,names=['caller','alias']),
              dict(start=0x80,end=0xc0,names=['target'])]
    result, counts = aggregate(tmp_path,binary,Code(),ranges,{'target'},'train')
    assert counts == {('caller','target'):101,('alias','target'):101}
    assert sum(row['samples'] for row in result['edges']) == 101
    assert result['stats']['indirect_entry_samples'] == 101
    # A local-only destination cannot be introduced as an external reference.
    result, counts = aggregate(tmp_path,binary,Code(),ranges,set(),'train')
    assert not counts and result['stats']['unavailable_global_target_or_caller'] == 101


def test_profiled_indirect_static_target_does_not_change_real_call(tmp_path):
    plugin = os.environ.get('DOMINATOR_TEST_PLUGIN')
    if not plugin:
        pytest.skip('Set DOMINATOR_TEST_PLUGIN to the built plugin')
    import lean_plan
    source = tmp_path/'caller.c'
    source.write_text('''#include <stdio.h>
extern int actual(int);
int(*volatile choice)(int)=actual;
__attribute__((noinline)) int caller(int x,int(*fn)(int)){
 volatile int v=x;for(int i=0;i<10;++i)v+=i;return fn(v);}
int main(){for(int i=0;i<8;++i)printf("%d\\n",caller(i,choice));}
''')
    target = tmp_path/'targets.c'
    target.write_text('int predicted(int x){return x+1;}\nint actual(int x){return x+2;}\n')
    obj = tmp_path/'targets.o'
    subprocess.run(['clang-19', '-O2', '-fPIC', '-c', str(target), '-o', str(obj)], check=True)
    profile = tmp_path/'callees.txt';profile.write_text('predicted\n')
    indirect = tmp_path/'indirect.json'
    indirect.write_text(json.dumps(dict(schema='prefetchit.indirect_targets.v1', callers={'caller':['predicted']})))
    env = dict(os.environ, PREFETCHIT_DOMINATOR='1', PREFETCHIT_DOM_LEAN='1',
        PREFETCHIT_DOM_METADATA='1', PREFETCHIT_DOM_SCHED_GATE='0',
        PREFETCHIT_DOM_LEAD='8', PREFETCHIT_DOM_MIN_FUNCTION='0',
        PREFETCHIT_DOM_SKIP_SHORT='0', PREFETCHIT_DOM_BATCH='8',
        PREFETCHIT_DOM_CALLER_TARGETS='0', PREFETCHIT_DOM_CALLEE_ONLY='1',
        PREFETCHIT_COLD_DIRECT_IN_PIC='1', PREFETCHIT_DOM_CALLEE_PROFILE=str(profile),
        PREFETCHIT_DOM_INDIRECT_TARGETS=str(indirect))
    base = tmp_path/'base';exe = tmp_path/'instrumented'
    subprocess.run(['clang-19','-O2','-fPIC',str(source),str(obj),'-o',str(base)],check=True)
    subprocess.run(['clang-19','-O2','-fPIC','-fpass-plugin='+plugin,str(source),str(obj),'-o',str(exe)],env=env,check=True)
    assert subprocess.check_output([base]) == subprocess.check_output([exe])
    rows = lean_plan.read_image(exe)['records']
    symbols = subprocess.check_output(['nm','-S','--defined-only',str(exe)],text=True)
    predicted = next(int(line.split()[0],16) for line in symbols.splitlines() if line.split()[-1:] == ['predicted'])
    assert rows and all(row['direct'] and row['target'] == predicted for row in rows)
    # Reject unknown profile target names before introducing a reference.
    profile.write_text('actual\n')
    rejected = subprocess.run(['clang-19','-O2','-fPIC','-fpass-plugin='+plugin,'-c',str(source),'-o',str(tmp_path/'bad.o')],env=env,capture_output=True,text=True)
    assert rejected.returncode != 0 and 'unlisted or duplicate indirect target' in rejected.stderr
