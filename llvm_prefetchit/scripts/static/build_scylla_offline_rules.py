#!/usr/bin/env python3
"""Pinned Scylla task-successor rules trained offline; no runtime model updates.

The normal hot path checks readable queued work first, then a bounded cascade of
RIP-relative current-handler comparisons. Diagnostic counters live only in a
separate binary. This is profile-guided code prefetch, not devirtualization.
"""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_scylla_future_targets import build, SITE, EXPECTED, queue_hint

def assembly(rules, lines=1, diagnostic=False):
    symbols = {}
    code = []
    if diagnostic:
        code.append('''
 mov %r14, %r8
 movabs $0x9e3779b97f4a7c15, %rax
 imul %rax, %r8
 shr $56, %r8
 shl $8, %r8
 lea a3_data(%rip), %r9
 add %r9, %r8
 mov (%r8), %rax
 cmp %r14, %rax
 je .Lowned
 test %rax, %rax
 jne .Lcollision
 lock cmpxchg %r14, (%r8)
 test %rax, %rax
 je .Lowned
 cmp %r14, %rax
 jne .Lcollision
.Lowned:
 incq 8(%r8)
 mov (%rdi), %r11
 mov (%r11), %r11
 cmpq $0, 56(%r8)
 je .Lobserved
 incq 88(%r8)
 cmpq $0, 104(%r8)
 je .Lresolved_queue
 incq 120(%r8)
 jmp .Lresolved_kind
.Lresolved_queue:
 incq 200(%r8)
.Lresolved_kind:
 cmp 56(%r8), %r11
 jne .Lobserved
 incq 80(%r8)
 lfence
 rdtsc
 shl $32, %rdx
 or %rdx, %rax
 sub 64(%r8), %rax
 add %rax, 40(%r8)
 incq 48(%r8)
 cmpq $0, 104(%r8)
 je .Lcorrect_queue
 incq 112(%r8)
 add %rax, 208(%r8)
 incq 216(%r8)
 jmp .Lobserved
.Lcorrect_queue:
 incq 192(%r8)
 add %rax, 224(%r8)
 incq 232(%r8)
.Lobserved:
 movq $0, 56(%r8)
''')
    code.append('''
 mov 0x50(%rbx), %rax
 mov 0x58(%rbx), %rcx
 sub %rax, %rcx
 test %rcx, %rcx
 je .Lrules
 mov 0x60(%rbx), %rdx
 dec %rdx
 and %rdx, %rax
 mov 0x48(%rbx), %rcx
 mov (%rcx,%rax,8), %rcx
 mov (%rcx), %rcx
 mov (%rcx), %r10
''')
    if diagnostic: code.append('incq 16(%r8)\nmovq $0, 104(%r8)')
    code.extend(f'prefetcht1 {n*64}(%r10)' for n in range(lines))
    code.append('jmp .Lemit' if diagnostic else 'jmp .Ldone')
    code.append('.Lrules:\nmov (%rdi), %r11\nmov (%r11), %r11')
    for i, rule in enumerate(rules):
        current, target = rule['current'], rule['target']
        symbols[f'a3_current_{i}'] = current
        symbols[f'a3_target_{i}'] = target
        symbols[f'a3_hint_{i}'] = rule.get('hint_target',target)
        code.append(f'lea a3_current_{i}(%rip), %r10\ncmp %r10, %r11\njne .Lrule_{i+1}')
        if diagnostic:
            code.append(f'incq {128+8*i}(%r8)\nincq 96(%r8)\nmovq $1, 104(%r8)\nlea a3_target_{i}(%rip), %r10')
        code.extend(f'prefetcht1 a3_hint_{i}+{n*64}(%rip)' for n in range(lines))
        code.append('jmp .Lemit' if diagnostic else 'jmp .Ldone')
        code.append(f'.Lrule_{i+1}:')
    code.append('jmp .Ldone')
    if diagnostic:
        code.append('''
.Lemit:
 mov %r10, 56(%r8)
 lfence
 rdtsc
 shl $32, %rdx
 or %rdx, %rax
 mov %rax, 64(%r8)
 jmp .Ldone
.Lcollision:
 lock incq a3_data+65536(%rip)
''')
        code.append(queue_hint(1))
    code.append('.Ldone:')
    return '\n'.join(code), symbols

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary',type=Path);p.add_argument('rules',type=Path);p.add_argument('out',type=Path)
    p.add_argument('--lines',type=int,choices=[1,4],default=1)
    p.add_argument('--limit',type=int,default=8);p.add_argument('--diagnostic',action='store_true')
    a=p.parse_args();sha=hashlib.sha256(a.binary.read_bytes()).hexdigest()
    assert sha=='81a6d6c9c35181d5dbd202f72b9bb90f36eae9f3f92047148e4f803023bc8c36'
    evidence=json.loads(a.rules.read_text());rules=evidence['rules'][:a.limit]
    assert evidence['source_sha256']==sha and evidence['all_training_frozen']
    assert 0<len(rules)<=8 and len({x['current'] for x in rules})==len(rules)
    assert all(x['current']!=x['target'] for x in rules)
    asm,symbols=assembly(rules,a.lines,a.diagnostic)
    plan={'sha256':sha,'symbols':symbols,'rules':rules,'rules_evidence':str(a.rules),
          'data_bytes':69632 if a.diagnostic else 0,'mode':'offline_rules',
          'lines':a.lines,'diagnostic':a.diagnostic,
          'ABI':'Same pinned reactor site and dead scratch registers as queue/frozen prototype; no application writes or calls.',
          'hooks':[{'site':SITE,'expected':EXPECTED,'assembly':asm,'label':'offline_successor_rules'}]}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.with_suffix('.plan.json').write_text(json.dumps(plan,indent=2));build(a.binary,plan,a.out)

if __name__=='__main__':main()
