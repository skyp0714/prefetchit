"""Validate metadata through real weak/PIC linking and post-layout coverage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
import lean_plan as p


def row(argument, target, active=True):
    return dict(module='1', function='2', group=0, argument=argument,
                key=p.hint_key(1, 2, 0, argument), direct=True,
                target=target, active=active)


def image(rows):
    return dict(path='fixture', sha256='fixture', executable_bytes=100,
                metadata_bytes=40*len(rows), records=rows)


def test_plan_intersection_and_relayout_restoration():
    a=image([row(0,64), row(1,68), row(2,128), row(3,132)])
    b=image([row(0,64), row(1,128), row(2,192), row(3,196)])
    plan=p.plan([a,b])
    assert plan['drop']==['1:2:0:3']  # Hint 1 was redundant in only one image.
    moved=image([row(0,64), row(1,68), row(2,124), row(3,132,False)])
    restored,audit=p.refine(plan,[moved])
    assert not audit['coverage_verified'] and restored['drop']==[]
    covered=image([row(0,64), row(1,68), row(2,128), row(3,132,False)])
    _,audit=p.refine(plan,[covered])
    assert audit['coverage_verified']
    with pytest.raises(ValueError,match='active-state mismatch'):
        p.refine(plan,[a])


@pytest.mark.parametrize('shared', [False, True])
def test_metadata_comdat_and_removed_target_relocations(tmp_path, shared):
    plugin=os.environ.get('DOMINATOR_TEST_PLUGIN')
    if not plugin:
        pytest.skip('Set DOMINATOR_TEST_PLUGIN to the built plugin')
    header=tmp_path/'probe.h'
    header.write_text(r'''
__attribute__((noinline)) inline int probe(int n) {
 volatile int v=n;
 for(int i=0;i<8;i++) { v+=i; v^=17; }
 if(n&1)v+=3;else v-=4;
 if(n&2)v+=7;else v-=9;
 if(n&4)v+=11;else v-=13;
 return v;
}
''')
    one=tmp_path/'one.cpp';two=tmp_path/'two.cpp'
    one.write_text('#include "probe.h"\n#include <cstdio>\nint other(int);\n'
                   'int main(){for(int i=0;i<16;i++)std::printf("%d %d\\n",probe(i),other(i));}\n')
    two.write_text('#include "probe.h"\nint other(int n){return probe(n+1);}\n')
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAN='1',
        PREFETCHIT_DOM_METADATA='1',PREFETCHIT_DOM_SCHED_GATE='0',
        PREFETCHIT_DOM_LEAD='0',PREFETCHIT_DOM_MAX_SITES='2',
        PREFETCHIT_DOM_MIN_FUNCTION='0',PREFETCHIT_DOM_SKIP_SHORT='0',
        PREFETCHIT_DOM_BATCH='8',PREFETCHIT_DOM_CALLER_TARGETS='0',
        PREFETCHIT_SEQ_FUNCTIONS='^_Z5probei$')
    placement='0,600,8,0,0,1,0,0,2,0,0'
    flags=['-fPIC','-shared'] if shared else []

    def build(name, policy=None, instrument=True):
        local=dict(env)
        if policy is not None:
            plan_path=tmp_path/(name+'.json')
            plan_path.write_text(json.dumps(policy))
            local['PREFETCHIT_DOM_DROP_PLAN']=str(plan_path)
        binary=tmp_path/name
        command=['clang++-19','-O2',*flags]
        if instrument:command+=['-fpass-plugin='+plugin]
        command += [str(one),str(two),'-o',str(binary)]
        completed=subprocess.run(command,env=local,capture_output=True,text=True)
        (tmp_path/(name+'.log')).write_text(completed.stdout+completed.stderr)
        assert completed.returncode==0,completed.stderr
        return binary

    baseline=build('baseline',instrument=False)
    full=build('full')
    original=p.read_image(full)
    assert original['records'] and not original['metadata_allocated']
    policy=p.plan([original],placement)
    assert policy['drop'], 'Fixture must exercise actual same-line targets'
    for iteration in range(8):
        candidate=build(f'drop_{iteration}',policy)
        parsed=p.read_image(candidate)
        policy,audit=p.refine(policy,[parsed])
        if audit['coverage_verified']:
            break
    assert audit['coverage_verified']
    assert any(not r['active'] for r in parsed['records'])
    assert sum(r['active'] for r in parsed['records'])<len(original['records'])
    if not shared:
        assert subprocess.check_output([baseline])==subprocess.check_output([full])==subprocess.check_output([candidate])
    bad=dict(policy,placement='wrong')
    with pytest.raises(AssertionError,match='placement mismatch'):
        build('mismatch',bad)
