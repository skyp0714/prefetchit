#!/usr/bin/env python3
"""Version-pinned Scylla 6.2.3 Seastar queue lookahead research prototype."""
from pathlib import Path
import argparse,hashlib,json,sys,re
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from append_dispatch_hooks import build
SITE=0x5c85db3
# This USDT NOP followed by current_task assignment precedes run_and_dispose.
EXPECTED='904989be281b0000'
def queue_hint(depth):
 return f'''
 mov 0x50(%rbx), %rax
 mov 0x58(%rbx), %rcx
 sub %rax, %rcx
 cmp ${depth}, %rcx
 jb 90f
 add ${depth-1}, %rax
 mov 0x60(%rbx), %rdx
 dec %rdx
 and %rdx, %rax
 mov 0x48(%rbx), %rcx
 mov (%rcx,%rax,8), %rcx
 mov (%rcx), %rcx
 mov (%rcx), %rcx
 prefetcht1 (%rcx)
90:
'''
def diagnostic():
 # 256 owner-tagged, cacheline-isolated shard slots. Contention cannot alter work.
 return '''
 mov %r14, %r8
 movabs $0x9e3779b97f4a7c15, %rax
 imul %rax, %r8
 shr $56, %r8
 shl $8, %r8
 lea a3_data(%rip), %r9
 add %r9, %r8
 mov (%r8), %rax
 cmp %r14, %rax
 je 10f
 test %rax, %rax
 jne 80f
 lock cmpxchg %r14, (%r8)
 test %rax, %rax
 je 10f
 cmp %r14, %rax
 jne 80f
10:
 incq 8(%r8)
 mov (%rdi), %r11
 mov (%r11), %r11
 cmpq $0, 56(%r8)
 je 20f
 incq 88(%r8)
 cmp 56(%r8), %r11
 jne 20f
 incq 80(%r8)
 lfence
 rdtsc
 shl $32, %rdx
 or %rdx, %rax
 sub 64(%r8), %rax
 add %rax, 40(%r8)
 incq 48(%r8)
20:
 movq $0, 56(%r8)
 mov 0x50(%rbx), %rax
 mov 0x58(%rbx), %rcx
 sub %rax, %rcx
 test %rcx, %rcx
 je 90f
 incq 16(%r8)
 cmp $2, %rcx
 jb 30f
 incq 24(%r8)
 cmp $4, %rcx
 jb 30f
 incq 32(%r8)
30:
 mov 0x60(%rbx), %rdx
 dec %rdx
 and %rdx, %rax
 mov 0x48(%rbx), %rcx
 mov (%rcx,%rax,8), %rcx
 mov (%rcx), %rcx
 mov (%rcx), %rcx
 mov %rcx, 56(%r8)
 prefetcht1 (%rcx)
 lfence
 rdtsc
 shl $32, %rdx
 or %rdx, %rax
 mov %rax, 64(%r8)
 jmp 90f
80:
 lock incq a3_data+65536(%rip)
90:
'''
def aggressive(diagnostic=False, freeze_after=0):
 code = r"""
 mov %r14, %r8
 movabs $0x9e3779b97f4a7c15, %rax
 imul %rax, %r8
 shr $56, %r8
 shl $14, %r8
 lea a3_data(%rip), %r9
 add %r9, %r8
 mov (%r8), %rax
 cmp %r14, %rax
 je 10f
 test %rax, %rax
 jne 80f
 lock cmpxchg %r14, (%r8)
 test %rax, %rax
 je 10f
 cmp %r14, %rax
 jne 80f
10:
 mov (%rdi), %r11
 mov (%r11), %r11
@OBSERVE@
 mov 96(%r8), %rcx
 test %rcx, %rcx
 je 30f
 mov %rcx, %r9
 shr $4, %r9
 mov %rcx, %rax
 shr $12, %rax
 xor %rax, %r9
 and $255, %r9
 shl $5, %r9
 lea 256(%r8,%r9), %r9
 cmp (%r9), %rcx
 jne 20f
 cmp 8(%r9), %r11
 jne 20f
 cmpq $3, 16(%r9)
 jae 30f
 incq 16(%r9)
 jmp 30f
20:
 mov %rcx, (%r9)
 mov %r11, 8(%r9)
 movq $1, 16(%r9)
30:
 mov %r11, 96(%r8)
 mov 0x50(%rbx), %rax
 mov 0x58(%rbx), %rcx
 sub %rax, %rcx
 test %rcx, %rcx
 je 40f
@QUEUE_COUNT@
 mov 0x60(%rbx), %rdx
 dec %rdx
 and %rdx, %rax
 mov 0x48(%rbx), %rcx
 mov (%rcx,%rax,8), %rcx
 mov (%rcx), %rcx
 mov (%rcx), %rcx
 prefetcht1 (%rcx)
 jmp 99f
40:
 mov %r11, %r9
 shr $4, %r9
 mov %r11, %rax
 shr $12, %rax
 xor %rax, %r9
 and $255, %r9
 shl $5, %r9
 lea 256(%r8,%r9), %r9
 cmp (%r9), %r11
 jne 99f
 cmpq $2, 16(%r9)
 jb 99f
 mov 8(%r9), %r10
 cmp %r11, %r10
 je 99f
@EMIT@
 prefetcht1 (%r10)
 jmp 99f
80:
@COLLISION@
@FALLBACK@
99:
"""
 observe = r"""
 cmp 96(%r8), %r11
 jne 12f
 incq 168(%r8)
12:
 incq 8(%r8)
 cmpq $0, 104(%r8)
 je 11f
 incq 120(%r8)
 cmp 104(%r8), %r11
 jne 11f
 incq 112(%r8)
 lfence
 rdtsc
 shl $32, %rdx
 or %rdx, %rax
 sub 144(%r8), %rax
 add %rax, 152(%r8)
 incq 160(%r8)
11:
 movq $0, 104(%r8)
"""
 emit = r"""
 incq 128(%r8)
 mov %r10, 104(%r8)
 lfence
 rdtsc
 shl $32, %rdx
 or %rdx, %rax
 mov %rax, 144(%r8)
"""
 if freeze_after:
  code=code.replace('lock cmpxchg %r14, (%r8)\n test %rax, %rax\n je 10f\n cmp %r14, %rax\n jne 80f\n10:', f'lock cmpxchg %r14, (%r8)\n test %rax, %rax\n je 9f\n cmp %r14, %rax\n jne 80f\n jmp 10f\n9:\n movq ${freeze_after}, 176(%r8)\n10:')
  code=code.replace('@OBSERVE@\n mov 96(%r8), %rcx', '@OBSERVE@\n cmpq $0, 176(%r8)\n je 35f\n decq 176(%r8)\n mov 96(%r8), %rcx')
  code=code.replace('mov %r11, 96(%r8)\n mov 0x50', 'mov %r11, 96(%r8)\n35:\n mov 0x50')
  observe=observe.replace('cmp 96(%r8), %r11','cmp 208(%r8), %r11').replace('12:\n incq','12:\n mov %r11, 208(%r8)\n incq')
 return code.replace('@OBSERVE@',observe if diagnostic else '').replace('@QUEUE_COUNT@','incq 16(%r8)' if diagnostic else '').replace('@EMIT@',emit if diagnostic else '').replace('@COLLISION@','lock incq a3_data+4194304(%rip)' if diagnostic else '').replace('@FALLBACK@',queue_hint(1))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('out',type=Path);p.add_argument('--mode',choices=['late','queue1','queue2','queue4','diagnostic','aggressive','aggressive_diagnostic','aggressive_frozen','aggressive_frozen_diagnostic'],required=True);p.add_argument('--gate',type=Path);p.add_argument('--lines',type=int,choices=[1,4],default=1);a=p.parse_args()
 assert hashlib.sha256(a.binary.read_bytes()).hexdigest()=='81a6d6c9c35181d5dbd202f72b9bb90f36eae9f3f92047148e4f803023bc8c36','uninspected package; re-audit ABI and addresses first'
 asm={'late':'mov (%rdi), %rax\nmov (%rax), %rax\nprefetcht1 (%rax)','diagnostic':diagnostic()}.get(a.mode)
 if a.mode.startswith('aggressive'):
  assert a.gate is not None,'prediction requires measured gate evidence'
  gate=json.loads(a.gate.read_text());assert gate['met'] and gate['dispatches']>1000 and gate['queued_next_fraction']<.8 and gate['owner_collisions']==0 and gate['diagnostic_mpki']>=1
  asm=aggressive(a.mode.endswith('diagnostic'),1000000 if 'frozen' in a.mode else 0)
 elif asm is None:asm=queue_hint(int(a.mode[-1]))
 if a.lines==4:
  asm=re.sub(r'prefetcht1 \((%\w+)\)',lambda m:'\n'.join(f'prefetcht1 {offset}({m[1]})' for offset in [0,64,128,192]),asm)
 plan={'hint_lines':a.lines,'sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'version':'6.2.3-0.20250119.bff9ddde1283','data_bytes':4198400 if a.mode.startswith('aggressive') else 69632 if a.mode=='diagnostic' else 0,'mode':a.mode,'hooks':[{'site':SITE,'expected':EXPECTED,'assembly':asm,'label':'reactor_run_tasks_single_start'}],'ABI':'RDI current task, RBX owner-thread task_queue, R14 reactor; RAX/RCX/RDX/R8-R11 and flags dead before virtual call. No calls, stack changes or writes to application objects. Queue live under reactor ownership; urgent tasks can change eventual order.'}
 if a.mode.startswith('aggressive'):plan['freeze_after_dispatches_per_reactor']=1000000 if 'frozen' in a.mode else 0;plan['gate']=gate;plan['predictor']='Per-reactor256entrytaggedlast-successor;two matching transitions;only when queue empty;skipself;collision falls back to queue lookahead. No predicted target dereference or invocation.'
 a.out.parent.mkdir(parents=True,exist_ok=True);a.out.with_suffix('.plan.json').write_text(json.dumps(plan,indent=2));build(a.binary,plan,a.out)
if __name__=='__main__':main()
