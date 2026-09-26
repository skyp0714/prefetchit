"""PIE execution, wrapped/empty queues and protected unknown-object prefix."""
import hashlib, importlib.util, os, struct, subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('callbacks',ROOT/'scripts/static/build_scylla_callback_targets.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
@pytest.mark.parametrize('lines',[1,3])
@pytest.mark.parametrize('diagnostic',[False,True])
def test_callback_guard_and_dispatch(tmp_path,lines,diagnostic):
 c=tmp_path/'test.c';asm=tmp_path/'test.s';base=tmp_path/'base';out=tmp_path/'hook'
 c.write_text(r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
struct task {void(**v)(struct task*);long id;};
struct object {void(*callback)(struct object*);long pad;struct task task;};
struct queue {char pad[72];struct task**data;uint64_t head,tail,capacity;};
static long calls;
void callback(struct object*o){if(o->task.id!=calls++)abort();}
void unknown(struct task*t){if(t->id!=calls++)abort();}
extern void adapter(struct task*);
extern void dispatch(struct task*,struct queue*,void*);
int main(){void(*a[])(struct task*)={adapter},(*u[])(struct task*)={unknown};
long page=sysconf(_SC_PAGESIZE);char*p=mmap(0,2*page,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);if(p==MAP_FAILED)return 2;
if(mprotect(p+page,page,PROT_READ|PROT_WRITE))return 3;
struct task*guard=(void*)(p+page);*guard=(struct task){u,2};
struct object obj={callback,0,{a,1}};struct task first={u,0};
struct task*data[4]={guard,0,0,&obj.task};struct queue q={.data=data,.head=3,.tail=5,.capacity=4};char reactor[0x1b30]={0};
dispatch(&first,&q,reactor);q.head=4;dispatch(&obj.task,&q,reactor);q.head=5;dispatch(guard,&q,reactor);
printf("%ld\n",calls);fflush(stdout);getchar();return calls!=3;}
''')
 asm.write_text('''.text
.globl adapter
.type adapter,@function
adapter:
push %rax
mov %rdi,%rax
add $-16,%rdi
call *-16(%rax)
pop %rax
ret
.size adapter,.-adapter
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
 bits,multiplier,_=m.table_for([syms['adapter']])
 index=lambda a:(((a>>4)*multiplier)&0xffffffff)>>(32-bits)
 assert syms['adapter']!=syms['unknown'] and index(syms['adapter'])==index(syms['unknown'])
 code,symbols,_=m.assembly([syms['adapter']],lines,diagnostic)
 plan={'sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'data_bytes':69632 if diagnostic else 0,'symbols':symbols,'hooks':[{'site':syms['site'],'expected':m.EXPECTED,'assembly':code}]}
 manifest=m.build(base,plan,out);assert len(manifest['hint_patches'])==lines
 restored=bytearray(Path(str(out)+'.nop').read_bytes())
 for x in manifest['hint_patches']:restored[x['offset']:x['offset']+len(bytes.fromhex(x['original']))]=bytes.fromhex(x['original'])
 assert restored==out.read_bytes()
 for binary in [out,Path(str(out)+'.nop')]:
  proc=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   assert proc.stdout.readline()=='3\n'
   if diagnostic:
    maps=Path(f'/proc/{proc.pid}/maps').read_text();bias=int(next(l.split()[0].split('-')[0] for l in maps.splitlines() if str(binary) in l and int(l.split()[2],16)==0),16)
    with open(f'/proc/{proc.pid}/mem','rb',buffering=0) as f:raw=os.pread(f.fileno(),69632,bias+manifest['rw_va'])
    slots=[struct.unpack_from('<32Q',raw,i*256) for i in range(256)];slots=[x for x in slots if x[0]]
    assert len(slots)==1 and slots[0][1:4]==(3,2,1)
    assert struct.unpack_from('<Q',raw,65536)[0]==0
   proc.communicate('\n',timeout=5);assert proc.returncode==0
  finally:
   if proc.poll() is None:proc.kill();proc.wait()
