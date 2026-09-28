from pathlib import Path
import os
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from lean_profile import attribute


def test_line_boundary_and_aliases_do_not_duplicate_sample_weight():
    ranges=[dict(start=32,end=96,names=['a','a_alias']),
            dict(start=96,end=128,names=['b'])]
    lines=[dict(dso='main',va='0x40',samples=10),
           dict(dso='main',va='0x100',samples=3),
           dict(dso='other',va='0x40',samples=20)]
    result=attribute(lines,ranges,'main')
    assert result['total_main_samples']==13
    assert result['unmapped_samples']==3
    assert result['ambiguous_line_samples']==10
    assert sum(x['score'] for x in result['ranked'])==pytest.approx(10)
    assert [x['score'] for x in result['ranked']]==[5,5]


def test_profile_file_restricts_actual_injection_functions(tmp_path):
    plugin=os.environ.get('DOMINATOR_TEST_PLUGIN')
    if not plugin:
        pytest.skip('Set DOMINATOR_TEST_PLUGIN to the built plugin')
    import lean_plan
    source=tmp_path/'selected.c'
    body='volatile int v=x;if(x&1)v+=3;else v-=4;if(x&2)v+=7;else v-=9;return v;'
    source.write_text('__attribute__((noinline)) int f(int x){'+body+'}\n'
                      '__attribute__((noinline)) int g(int x){'+body+'}\n'
                      'int main(){return f(3)+g(3)!=26;}\n')
    functions=tmp_path/'functions.txt';functions.write_text('f\n')
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAN='1',
        PREFETCHIT_DOM_METADATA='1',PREFETCHIT_DOM_SCHED_GATE='0',
        PREFETCHIT_DOM_LEAD='0',PREFETCHIT_DOM_MIN_FUNCTION='0',
        PREFETCHIT_DOM_SKIP_SHORT='0',PREFETCHIT_DOM_BATCH='8',
        PREFETCHIT_DOM_CALLER_TARGETS='0',PREFETCHIT_SEQ_FUNCTIONS_FILE=str(functions))
    exe=tmp_path/'selected'
    subprocess.run(['clang-19','-O2','-fpass-plugin='+plugin,str(source),'-o',str(exe)],env=env,check=True)
    subprocess.run([exe],check=True)
    metadata=lean_plan.read_image(exe)
    table=subprocess.check_output(['nm','-S','--defined-only',str(exe)],text=True)
    f=next(line.split() for line in table.splitlines() if line.split()[-1:] == ['f'])
    start,size=int(f[0],16),int(f[1],16)
    assert metadata['records']
    assert all(start<=r['site']<start+size for r in metadata['records'])
