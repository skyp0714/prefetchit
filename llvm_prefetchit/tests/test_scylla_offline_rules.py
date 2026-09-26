"""Execute offline rules with PIE relocation, wrapped queues, and unknown handlers."""
import hashlib, importlib.util, os, struct, subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('rules',ROOT/'scripts/static/build_scylla_offline_rules.py')
rules=importlib.util.module_from_spec(s);s.loader.exec_module(rules)

@pytest.mark.parametrize('diagnostic',[False,True])
@pytest.mark.parametrize('lines',[1,4])
@pytest.mark.parametrize('callee_hint',[False,True])
def test_rules_preserve_dispatch_and_diagnostic(tmp_path,diagnostic,lines,callee_hint):
 c=tmp_path/'test.c';asm=tmp_path/'test.s';base=tmp_path/'base';out=tmp_path/'hook'
 c.write_text('''#include <stdio.h>
#include <stdint.h>
struct task { void(**v)(struct task*); long id; };
struct queue { char pad[72]; struct task **data; uint64_t head,tail,capacity; };
static long expected;
void run_a(struct task*t){if(t->id!=expected++)__builtin_trap();asm volatile("nop");}
void run_b(struct task*t){if(t->id!=expected++)__builtin_trap();asm volatile("nop;nop");}
void run_c(struct task*t){if(t->id!=expected++)__builtin_trap();asm volatile("nop;nop;nop");}
extern void dispatch(struct task*,struct queue*,void*);
int main(){void(*a[])(struct task*)={run_a},(*b[])(struct task*)={run_b},(*c[])(struct task*)={run_c};
char reactor[0x1b30]={0};struct task ts[13];struct task *data[4];
struct queue q={.data=0,.head=0,.tail=0,.capacity=4};
for(int i=0;i<13;i++)ts[i]=(struct task){i==12?c:i%2?b:a,i};
data[3]=&ts[9];data[0]=&ts[10];data[1]=&ts[11];
for(int i=0;i<13;i++){if(i>=8){q.data=data;q.head=i<12?i-1:10;q.tail=10;}
dispatch(&ts[i],&q,reactor);}
printf("%ld\\n",expected);fflush(stdout);getchar();return expected!=13;}
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
 syms={x[2]:int(x[0],16) for line in subprocess.check_output(['nm',str(base)],text=True).splitlines() if len(x:=line.split())==3}
 selected=[{'current':syms['run_a'],'target':syms['run_b']},{'current':syms['run_b'],'target':syms['run_a']}]
 if callee_hint:
  for rule in selected:rule['hint_target']=syms['run_c']
 code,symbols=rules.assembly(selected,lines,diagnostic)
 plan={'sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'data_bytes':69632 if diagnostic else 0,'symbols':symbols,'hooks':[{'site':syms['site'],'expected':rules.EXPECTED,'assembly':code}]}
 m=rules.build(base,plan,out)
 for binary in [out,Path(str(out)+'.nop')]:
  proc=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   assert proc.stdout.readline()=='13\n'
   if diagnostic:
    maps=Path(f'/proc/{proc.pid}/maps').read_text();bias=int(next(l.split()[0].split('-')[0] for l in maps.splitlines() if str(binary) in l and int(l.split()[2],16)==0),16)
    with open(f'/proc/{proc.pid}/mem','rb',buffering=0) as f:raw=os.pread(f.fileno(),69632,bias+m['rw_va'])
    slots=[struct.unpack_from('<32Q',raw,i*256) for i in range(256)];slots=[x for x in slots if x[0]]
    assert len(slots)==1
    x=slots[0];assert x[1:3]==(13,3)
    assert x[10:13]==(11,12,9) # correct, resolved, rule-emitted
    assert x[16:18]==(4,5) # individual rule coverage
    assert x[14:16]==(8,9) # rule-correct, rule-resolved (unknown handler mismatch)
    assert x[24:26]==(3,3) # queue-correct, queue-resolved
    assert x[27]==8 and x[29]==3 # matched lead samples by kind
    assert struct.unpack_from('<Q',raw,65536)[0]==0
   proc.communicate('\n',timeout=5);assert proc.returncode==0
  finally:
   if proc.poll() is None:proc.kill();proc.wait()
