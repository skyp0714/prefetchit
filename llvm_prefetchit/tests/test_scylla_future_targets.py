"""Execute the exact queue assembly on owned queues, with real virtual dispatch."""
import importlib.util,hashlib,subprocess,struct,os
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('scylla',ROOT/'scripts/static/build_scylla_future_targets.py');sc=importlib.util.module_from_spec(s);s.loader.exec_module(sc)
@pytest.mark.parametrize('mode',['queue1','queue2','queue4','diagnostic'])
def test_queue_bounds_order_and_diagnostic(tmp_path,mode):
 c=tmp_path/'test.c';asm=tmp_path/'test.s';base=tmp_path/'base';out=tmp_path/'hook'
 c.write_text('''#include <stdio.h>
#include <stdint.h>
struct task { void(**v)(struct task*); long id; };
struct queue { char pad[72]; struct task **data; uint64_t head,tail,capacity; };
static long expected=0;
static void run(struct task*t){if(t->id!=expected++)__builtin_trap();}
extern void dispatch(struct task*,struct queue*,void*);
int main(){void(*v[])(struct task*)={run};struct task tasks[4];struct task *data[4];char reactor[0x1b30]={0};struct queue q={.data=data,.head=0,.tail=4,.capacity=4};
for(int i=0;i<4;i++){tasks[i]=(struct task){v,i};data[i]=&tasks[i];}
for(int i=0;i<4;i++){q.head=i+1;dispatch(&tasks[i],&q,reactor);}
printf("%ld\\n",expected);fflush(stdout);getchar();return expected!=4;}
''')
 asm.write_text('''.text
.globl dispatch
.type dispatch,@function
dispatch:
endbr64
push %rbx
push %r14
sub $8,%rsp
mov %rsi,%rbx
mov %rdx,%r14
.globl site
site:
nop
mov %rdi,0x1b28(%r14)
mov (%rdi),%rax
call *(%rax)
add $8,%rsp
pop %r14
pop %rbx
ret
.size dispatch,.-dispatch
.section .note.GNU-stack,"",@progbits
''')
 subprocess.run(['clang-19','-O2','-pie',str(c),str(asm),'-o',str(base)],check=True)
 sym=next(int(l.split()[0],16) for l in subprocess.check_output(['nm',str(base)],text=True).splitlines() if l.endswith(' site'))
 plan={'sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'data_bytes':69632 if mode=='diagnostic' else 0,'hooks':[{'site':sym,'expected':sc.EXPECTED,'assembly':sc.diagnostic() if mode=='diagnostic' else sc.queue_hint(int(mode[-1]))}]}
 m=sc.build(base,plan,out)
 for binary in [out,Path(str(out)+'.nop')]:
  proc=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   assert proc.stdout.readline()=='4\n'
   if mode=='diagnostic':
    maps=Path(f'/proc/{proc.pid}/maps').read_text();bias=int(next(l.split()[0].split('-')[0] for l in maps.splitlines() if str(binary) in l and int(l.split()[2],16)==0),16)
    with open(f'/proc/{proc.pid}/mem','rb',buffering=0) as f:raw=os.pread(f.fileno(),69632,bias+m['rw_va'])
    slots=[struct.unpack_from('<32Q',raw,i*256) for i in range(256)];slots=[x for x in slots if x[0]]
    assert len(slots)==1
    x=slots[0];assert x[1:5]==(4,3,2,0) # total, queue>=1, >=2, >=4
    assert x[10:12]==(3,3) # predicted queue target equals actual next target
    assert struct.unpack_from('<Q',raw,65536)[0]==0
   proc.communicate('\n',timeout=5);assert proc.returncode==0
  finally:
   if proc.poll() is None:proc.kill();proc.wait()

@pytest.mark.parametrize('instrumented',[False,True])
@pytest.mark.parametrize('freeze_after',[0,6])
def test_empty_queue_predictor_learns_without_invoking_future_task(tmp_path,instrumented,freeze_after,training_counts=False):
 c=tmp_path/'test.c';asm=tmp_path/'test.s';base=tmp_path/'base';out=tmp_path/'hook'
 c.write_text('''#include <stdio.h>
#include <stdint.h>
struct task { void(**v)(struct task*); long id; };
struct queue { char pad[72]; struct task **data; uint64_t head,tail,capacity; };
static long expected=0;
static void run_a(struct task*t){if(t->id!=expected++)__builtin_trap();asm volatile("nop");}
static void run_b(struct task*t){if(t->id!=expected++)__builtin_trap();asm volatile("nop;nop");}
extern void dispatch(struct task*,struct queue*,void*);
int main(){void(*a[])(struct task*)={run_a},(*b[])(struct task*)={run_b};char reactor[0x1b30]={0};struct queue q={.data=0,.head=0,.tail=0,.capacity=4};
for(int i=0;i<8;i++){struct task t={i%2?b:a,i};dispatch(&t,&q,reactor);}
printf("%ld\\n",expected);fflush(stdout);getchar();return expected!=8;}
''')
 asm.write_text('''.text
.globl dispatch
.type dispatch,@function
dispatch:
endbr64
push %rbx
push %r14
sub $8,%rsp
mov %rsi,%rbx
mov %rdx,%r14
.globl site
site:
nop
mov %rdi,0x1b28(%r14)
mov (%rdi),%rax
call *(%rax)
add $8,%rsp
pop %r14
pop %rbx
ret
.size dispatch,.-dispatch
.section .note.GNU-stack,"",@progbits
''')
 subprocess.run(['clang-19','-O2','-pie',str(c),str(asm),'-o',str(base)],check=True)
 sym=next(int(l.split()[0],16) for l in subprocess.check_output(['nm',str(base)],text=True).splitlines() if l.endswith(' site'))
 code=sc.aggressive(instrumented,freeze_after)
 if training_counts:
  import sys
  sys.path.insert(0,str(ROOT/'scripts/static'))
  from build_scylla_weighted_training import assembly as weighted
  code=weighted(freeze_after)
 plan={'sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'data_bytes':4198400,'hooks':[{'site':sym,'expected':sc.EXPECTED,'assembly':code}]}
 m=sc.build(base,plan,out)
 for binary in [out,Path(str(out)+'.nop')]:
  proc=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   assert proc.stdout.readline()=='8\n'
   maps=Path(f'/proc/{proc.pid}/maps').read_text();bias=int(next(l.split()[0].split('-')[0] for l in maps.splitlines() if str(binary) in l and int(l.split()[2],16)==0),16)
   with open(f'/proc/{proc.pid}/mem','rb',buffering=0) as f:raw=os.pread(f.fileno(),4198400,bias+m['rw_va'])
   slots=[struct.unpack_from('<32Q',raw,i*16384) for i in range(256)];slots=[x for x in slots if x[0]]
   assert len(slots)==1
   if freeze_after:assert slots[0][22]==0
   if instrumented:
    x=slots[0];assert x[1:3]==(8,0)
    assert x[14:17]==(3,3,4) # correct, resolved predictions, emitted including final unresolved
   if training_counts:
    owners=[i for i in range(256) if struct.unpack_from('<Q',raw,i*16384)[0]]
    table=[struct.unpack_from('<4Q',raw,owners[0]*16384+256+j*32) for j in range(256)]
    assert sum(x[3] for x in table)==1,'Eligible emission count must stop at the training boundary'
    assert sum(bool(x[0]) for x in table)==2
   assert struct.unpack_from('<Q',raw,4194304)[0]==0
   proc.communicate('\n',timeout=5);assert proc.returncode==0
  finally:
   if proc.poll() is None:proc.kill();proc.wait()


def test_prediction_frequency_is_training_only(tmp_path):
 test_empty_queue_predictor_learns_without_invoking_future_task(tmp_path,True,6,training_counts=True)
