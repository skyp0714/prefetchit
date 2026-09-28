"""Compile and execute real CFG/call cases; verify layout-independent operands."""
import os
from pathlib import Path
import subprocess
import re
import pytest

PLUGIN = os.environ.get('DOMINATOR_TEST_PLUGIN')
pytestmark = pytest.mark.skipif(not PLUGIN, reason='Set DOMINATOR_TEST_PLUGIN to the built plugin')

def test_cfg_calls_and_exceptions(tmp_path):
    source = tmp_path/'probe.cpp'
    source.write_text(r'''
#include <cstdio>
__attribute__((noinline)) int leaf(int n) { if(n==19)throw n; volatile int x=n; return x&1?x*3:x+9; }
__attribute__((noinline)) int run(int n,int(*fn)(int)) {
  volatile int x=n; for(int i=0;i<8;i++)x+=i;
  switch(n%3) { case 0:x+=leaf(n);break;case 1:x+=fn(n+1);break;default:x-=leaf(n+2); }
  try { x+=leaf(n+3); } catch(int e) { x-=e; }
  return x;
}
int main(){for(int i=0;i<17;i++)std::printf("%d\n",run(i,leaf));}
''')
    env=dict(os.environ, PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAD='8')
    outputs=[]
    for name,flags in [('base',[]),('gate',['-fpass-plugin='+PLUGIN]),('flat',['-fpass-plugin='+PLUGIN])]:
        local=dict(env,PREFETCHIT_DOM_SCHED_GATE='0' if name=='flat' else '1')
        exe=tmp_path/name
        proc=subprocess.run(['clang++-19','-O2','-g',*flags,str(source),'-o',str(exe)],env=local,capture_output=True,text=True)
        assert proc.returncode==0,proc.stderr
        outputs.append(subprocess.check_output([exe]))
    assert outputs[0]==outputs[1]==outputs[2]
    ir=tmp_path/'probe.ll'
    subprocess.run(['clang++-19','-O2','-S','-emit-llvm','-fpass-plugin='+PLUGIN,str(source),'-o',str(ir)],env=env,check=True)
    subprocess.run(['opt-19','-passes=verify','-disable-output',str(ir)],check=True)
    text=ir.read_text()
    assert 'blockaddress(' in text and 'rdtscp' in text
    assert 'prefetcht1 ($' in text  # Existing indirect SSA target, not a new load.
    assert all(f'cmpq {offset}(' in text for offset in (0,8,16,24))
    assert 'call void asm sideeffect' in text

def test_no_runtime_and_invalid_settings(tmp_path):
    source=tmp_path/'probe.c';source.write_text('int f(int x){volatile int v=x;return v?x*3:x+1;} int main(){return f(0)!=1;}')
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_BATCH='0')
    bad=subprocess.run(['clang-19','-O2','-fpass-plugin='+PLUGIN,str(source),'-o',str(tmp_path/'bad')],env=env,capture_output=True,text=True)
    assert bad.returncode and 'invalid dominator placement limits' in bad.stderr
    env['PREFETCHIT_DOM_BATCH']='4'
    subprocess.run(['clang-19','-O2','-fPIC','-shared','-fpass-plugin='+PLUGIN,str(source),'-o',str(tmp_path/'libprobe.so')],env=env,check=True)

@pytest.mark.parametrize('window', [False, True])
def test_gate_executes_monotonically_fewer_groups(tmp_path, window):
    # Replace ONLY the hint mnemonic in emitted IR with an observable counter.
    # Exercise the actual inline gate, register clobbers and target operands.
    source=tmp_path/'phase.c'
    source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
void *__prefetchit_sched_slots;
volatile unsigned long gate_count;
static uint64_t slots[4096][8];
__attribute__((noinline)) int leaf(int x){volatile int v=x;return v*3;}
__attribute__((noinline)) int probe(int x){
 volatile int v=x;for(int i=0;i<10;i++){if(v&1)v+=leaf(i);else v-=leaf(i);}
 return v;
}
int main(void){
 __prefetchit_sched_slots=slots;
 for(int phase=0;phase<4;phase++){
  for(int cpu=0;cpu<4096;cpu++)for(int tier=0;tier<3;tier++)slots[cpu][tier]=tier>=phase?UINT64_MAX:0;
  gate_count=0;probe(3);printf("%lu\n",gate_count);
 }
}
''')
    ir=tmp_path/'phase.ll'
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAD='8',PREFETCHIT_SEQ_FUNCTIONS='^probe$',
             PREFETCHIT_DOM_WINDOW=str(int(window)))
    if window:
        source.write_text(source.read_text().replace('phase<4','phase<7').replace(
            'slots[cpu][tier]=tier>=phase?UINT64_MAX:0;',
            '{slots[cpu][tier]=phase<=3 || tier>=phase-3?UINT64_MAX:0; '
            'slots[cpu][tier+4]=phase>=3 || tier>=3-phase?0:UINT64_MAX;}'))
    subprocess.run(['clang-19','-O2','-S','-emit-llvm','-fpass-plugin='+PLUGIN,str(source),'-o',str(ir)],env=env,check=True)
    text,n=re.subn(r'prefetcht1 \$\{\d+:c\}\(%rip\)',r'incq gate_count(%rip)',ir.read_text())
    assert n>4
    ir.write_text(text)
    exe=tmp_path/'phase'
    subprocess.run(['clang-19',str(ir),'-o',str(exe)],check=True)
    counts=list(map(int,subprocess.check_output([exe],text=True).split()))
    if window:
        assert counts[0]==counts[6]==0,counts
        assert counts[0]<counts[1]<counts[2]<counts[3]>counts[4]>counts[5]>counts[6],counts
    else:
        assert counts[0]>counts[1]>counts[2]>counts[3]==0,counts

def test_lean_limits_and_semantics(tmp_path):
    source=tmp_path/'lean.c'
    source.write_text('''#include <stdio.h>
__attribute__((noinline)) int leaf(int x){volatile int y=x;return y*3;}
__attribute__((noinline)) int probe(int x){volatile int v=x;
for(int i=0;i<20;i++){v+=i;v^=31;v+=leaf(i);if(v&1)v+=leaf(v);else v-=leaf(i+4);}return v;}
int main(){for(int i=0;i<8;i++)printf("%d\\n",probe(i));}
''')
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAN='1',PREFETCHIT_DOM_WINDOW='1',
        PREFETCHIT_DOM_LEAD='8',PREFETCHIT_DOM_MIN_FUNCTION='0',PREFETCHIT_DOM_MAX_SITES='2',
        PREFETCHIT_DOM_BATCH='8',PREFETCHIT_DOM_CALLER_TARGETS='0',PREFETCHIT_SEQ_FUNCTIONS='^probe$')
    outputs=[]
    for name,flags in [('base',[]),('lean',['-fpass-plugin='+PLUGIN])]:
        exe=tmp_path/name
        subprocess.run(['clang-19','-O2',*flags,str(source),'-o',str(exe)],env=env,check=True)
        outputs.append(subprocess.check_output([exe]))
    assert outputs[0]==outputs[1]
    ir=tmp_path/'lean.ll'
    proc=subprocess.run(['clang-19','-O2','-S','-emit-llvm','-fpass-plugin='+PLUGIN,str(source),'-o',str(ir)],env=env,capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    assert 'continuations=0' in proc.stderr
    assert 0<int(re.search(r'groups=(\d+)',proc.stderr)[1])<=2
    assert int(re.search(r'hints=(\d+)',proc.stderr)[1])<=16
    subprocess.run(['opt-19','-passes=verify','-disable-output',str(ir)],check=True)
