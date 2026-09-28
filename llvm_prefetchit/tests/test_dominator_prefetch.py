"""Compile and execute real CFG/call cases; verify layout-independent operands."""
import os
from pathlib import Path
import subprocess
import re
import pytest

PLUGIN = os.environ.get('DOMINATOR_TEST_PLUGIN')
RUNTIME = Path(__file__).resolve().parents[1]/'kernel/sched_clock/runtime.c'
pytestmark = pytest.mark.skipif(not PLUGIN, reason='Set DOMINATOR_TEST_PLUGIN to the built plugin')

@pytest.mark.parametrize('outline', [False, True])
def test_cfg_calls_and_exceptions(tmp_path, outline):
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
        local=dict(env,PREFETCHIT_DOM_SCHED_GATE='0' if name=='flat' else '1',
            PREFETCHIT_DOM_OUTLINE=str(int(outline and name!='flat')),PREFETCHIT_DOM_WINDOW=str(int(outline)))
        exe=tmp_path/name
        proc=subprocess.run(['clang++-19','-O2','-g',*flags,str(source),'-o',str(exe)],env=local,capture_output=True,text=True)
        assert proc.returncode==0,proc.stderr
        outputs.append(subprocess.check_output([exe]))
    assert outputs[0]==outputs[1]==outputs[2]
    ir=tmp_path/'probe.ll'
    env.update(PREFETCHIT_DOM_OUTLINE=str(int(outline)),PREFETCHIT_DOM_WINDOW=str(int(outline)))
    subprocess.run(['clang++-19','-O2','-S','-emit-llvm','-fpass-plugin='+PLUGIN,str(source),'-o',str(ir)],env=env,check=True)
    subprocess.run(['opt-19','-passes=verify','-disable-output',str(ir)],check=True)
    text=ir.read_text()
    assert 'blockaddress(' in text
    assert ('preserve_allcc' if outline else 'rdtscp') in text
    assert 'prefetcht1 ($' in text  # Existing indirect SSA target, not a new load.
    if not outline:assert all(f'cmpq {offset}(' in text for offset in (0,8,16,24))
    assert 'call void asm sideeffect' in text

def test_no_runtime_and_invalid_settings(tmp_path):
    source=tmp_path/'probe.c';source.write_text('int f(int x){volatile int v=x;return v?x*3:x+1;} int main(){return f(0)!=1;}')
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_BATCH='0')
    bad=subprocess.run(['clang-19','-O2','-fpass-plugin='+PLUGIN,str(source),'-o',str(tmp_path/'bad')],env=env,capture_output=True,text=True)
    assert bad.returncode and 'invalid dominator placement limits' in bad.stderr
    env['PREFETCHIT_DOM_BATCH']='4'
    subprocess.run(['clang-19','-O2','-fPIC','-shared','-fpass-plugin='+PLUGIN,str(source),'-o',str(tmp_path/'libprobe.so')],env=env,check=True)

@pytest.mark.parametrize('window,outline,relaxed', [(False,False,False),(True,False,False),(True,True,False),(True,True,True)])
def test_gate_executes_monotonically_fewer_groups(tmp_path, window, outline, relaxed):
    if relaxed and 'rdpid' not in Path('/proc/cpuinfo').read_text().split():
        pytest.skip('RDPID hardware required')
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
  gate_count=0;int value=probe(3);printf("%lu %d\n",gate_count,value);
 }
}
''')
    ir=tmp_path/'phase.ll'
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAD='8',PREFETCHIT_SEQ_FUNCTIONS='^probe$',
             PREFETCHIT_DOM_WINDOW=str(int(window)),PREFETCHIT_DOM_OUTLINE=str(int(outline)))
    if window:
        source.write_text(source.read_text().replace('phase<4','phase<7').replace(
            'slots[cpu][tier]=tier>=phase?UINT64_MAX:0;',
            '{slots[cpu][tier]=phase<=3 || tier>=phase-3?UINT64_MAX:0; '
            'slots[cpu][tier+4]=phase>=3 || tier>=3-phase?0:UINT64_MAX;}'))
    extra=[]
    if outline:
        source.write_text(source.read_text().replace('void *__prefetchit_sched_slots;',
                                                   'extern void *__prefetchit_sched_slots;'))
        runtime=tmp_path/'runtime.o'
        subprocess.run(['clang-19','-O2','-DPREFETCHIT_RELAXED_CLOCK='+str(int(relaxed)),
                        '-c',str(RUNTIME),'-o',str(runtime)],check=True)
        extra=[str(runtime)]
    baseline=tmp_path/'phase_expected'
    subprocess.run(['clang-19','-O2',str(source),*extra,'-o',str(baseline)],check=True)
    expected=[line.split()[1] for line in subprocess.check_output([baseline],text=True).splitlines()]
    subprocess.run(['clang-19','-O2','-S','-emit-llvm','-fpass-plugin='+PLUGIN,str(source),'-o',str(ir)],env=env,check=True)
    text,n=re.subn(r'prefetcht1 \$\{\d+:c\}\(%rip\)',r'incq gate_count(%rip)',ir.read_text())
    assert n>4
    ir.write_text(text)
    exe=tmp_path/'phase'
    subprocess.run(['clang-19',str(ir),*extra,'-o',str(exe)],check=True)
    rows=[line.split() for line in subprocess.check_output([exe],text=True).splitlines()]
    assert [row[1] for row in rows]==expected,'Gate clobbered live application values'
    counts=[int(row[0]) for row in rows]
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


def test_outlined_targets_follow_application_blocks_and_keep_static_allocas(tmp_path):
    # A target BB also contains a hoisted gate. Its prefetch must follow the
    # original application instruction after splitting, not the injected gate.
    source=tmp_path/'anchors.ll'
    loads='\n'.join(f'  %l{i} = load volatile i32, ptr %p' for i in range(24))
    source.write_text('''target triple = "x86_64-unknown-linux-gnu"
declare void @sink(i32)
define void @probe(ptr %p, i1 %take) {
entry:
  %slot = alloca i32, align 4
  store volatile i32 1, ptr %slot
  br i1 %take, label %left, label %right
left:
'''+loads+'''
  call void @sink(i32 %l23)
  ret void
right:
  call void @sink(i32 9)
  ret void
}
''')
    env=dict(os.environ,PREFETCHIT_DOMINATOR='1',PREFETCHIT_DOM_LEAN='1',PREFETCHIT_DOM_WINDOW='1',
        PREFETCHIT_DOM_OUTLINE='1',PREFETCHIT_DOM_LEAD='24',PREFETCHIT_DOM_SKIP_SHORT='0',
        PREFETCHIT_DOM_MIN_FUNCTION='0',PREFETCHIT_DOM_MAX_SITES='0',PREFETCHIT_DOM_BATCH='8',
        PREFETCHIT_DOM_CALLER_TARGETS='0',PREFETCHIT_SEQ_FUNCTIONS='^probe$')
    output=tmp_path/'result.ll'
    subprocess.run(['opt-19','-load-pass-plugin='+PLUGIN,'-passes=prefetchit-inject,verify','-S',str(source),'-o',str(output)],env=env,check=True)
    text=output.read_text()
    body=text.split('define void @probe',1)[1].split('\n}',1)[0]
    blocks=re.split(r'\n(__prefetchit_bb_\d+):[^\n]*\n',body)
    by_name=dict(zip(blocks[1::2],blocks[2::2]))
    assert '%slot = alloca' in next(iter(by_name.values()))
    name=next(k for k,v in by_name.items() if '%l0 = load volatile' in v)
    assert f'blockaddress(@probe, %{name})' in text
    prefix=by_name[name].split('%l0 = load volatile',1)[0]
    assert 'preserve_allcc' not in prefix
    assert sum('%slot = alloca' in v for v in by_name.values())==1


def test_memo_gate_rechecks_early_calls_and_resets_on_schedule_epoch(tmp_path):
    if 'rdpid' not in Path('/proc/cpuinfo').read_text().split():
        pytest.skip('RDPID hardware required')
    source=tmp_path/'memo.c'
    source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
extern void *__prefetchit_sched_slots;
extern __attribute__((preserve_all)) int __prefetchit_gate_0(void);
static uint64_t slots[4096][8];
static void phase(uint64_t epoch,uint64_t begin,uint64_t end){
 for(int cpu=0;cpu<4096;cpu++){slots[cpu][3]=epoch;slots[cpu][4]=begin;slots[cpu][0]=end;}}
__attribute__((noinline)) int sample(unsigned n){int sum=0;
 #pragma clang loop unroll(disable)
 for(unsigned i=0;i<n;i++)sum+=__prefetchit_gate_0();
 return sum;}
int main(void){__prefetchit_sched_slots=slots;
 phase(1,0,UINT64_MAX);printf("%d\n",sample(7));printf("%d\n",sample(7));
 phase(2,0,UINT64_MAX);printf("%d\n",sample(7));
 phase(3,UINT64_MAX,UINT64_MAX);printf("%d\n",sample(7));
 /* Moving synthetic bounds simulates reaching the beginning of a window. */
 phase(3,0,UINT64_MAX);printf("%d\n",sample(7));
 phase(4,0,0);printf("%d\n",sample(7));
 /* Once expired, this epoch stays suppressed until scheduling resets it. */
 phase(4,0,UINT64_MAX);printf("%d\n",sample(7));
 phase(5,0,UINT64_MAX);printf("%d\n",sample(7));
}
''')
    runtime=tmp_path/'runtime.o';exe=tmp_path/'memo'
    subprocess.run(['clang-19','-O2','-DPREFETCHIT_RELAXED_CLOCK=1','-DPREFETCHIT_MEMO_GATE=1',
                    '-c',str(RUNTIME),'-o',str(runtime)],check=True)
    subprocess.run(['clang-19','-O2',str(source),str(runtime),'-o',str(exe)],check=True)
    cpu=min(os.sched_getaffinity(0))
    values=list(map(int,subprocess.check_output(['taskset','-c',str(cpu),str(exe)],text=True).split()))
    assert values==[1,0,1,0,1,0,0,1]
