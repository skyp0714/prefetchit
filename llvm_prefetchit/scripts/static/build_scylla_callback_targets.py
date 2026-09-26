#!/usr/bin/env python3
"""Resolve verified Seastar callback adapters from live queued objects.

Pinned ABI only. Full relative-address membership protects the task-16 read;
unknown handlers keep the original queue-entry hint. No target is invoked.
"""
import argparse, hashlib, json, math, struct, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_scylla_future_targets import build, SITE, EXPECTED
SIGNATURE=bytes.fromhex('504889f84883c7f0ff50f058c3')
def table_for(addresses):
    addresses=sorted(set(addresses));assert addresses
    for bits in range(6,13):
        for multiplier in range(1,20000,2):
            indices=[(((a>>4)*multiplier)&0xffffffff)>>(32-bits) for a in addresses]
            if len(set(indices))==len(indices):
                table=[-1]*(1<<bits)
                for i,a in zip(indices,addresses):table[i]=a
                return bits,multiplier,table
    raise ValueError('No collision-free table')
def assembly(addresses,lines=1,diagnostic=False):
    assert lines in (1,3)
    bits,multiplier,table=table_for(addresses)
    code=[]
    if diagnostic:
        code.append('''mov %r14,%r8
movabs $0x9e3779b97f4a7c15,%rax
imul %rax,%r8
shr $56,%r8
shl $8,%r8
lea a3_data(%rip),%r9
add %r9,%r8
mov (%r8),%rax
cmp %r14,%rax
je .Lowned
test %rax,%rax
jne .Lcollision
lock cmpxchg %r14,(%r8)
test %rax,%rax
je .Lowned
cmp %r14,%rax
jne .Lcollision
.Lowned:
incq 8(%r8)''')
    code.append('''mov 0x50(%rbx),%rax
mov 0x58(%rbx),%rcx
sub %rax,%rcx
test %rcx,%rcx
je .Ldone
mov 0x60(%rbx),%rdx
dec %rdx
and %rdx,%rax
mov 0x48(%rbx),%rcx
mov (%rcx,%rax,8),%r9
mov (%r9),%rcx
mov (%rcx),%r10''')
    if diagnostic:code.append('incq 16(%r8)')
    code.append(f'''lea a3_image_base(%rip),%r11
mov %r10,%rax
sub %r11,%rax
mov %eax,%edx
shr $4,%edx
imul ${multiplier},%edx,%edx
shr ${32-bits},%edx
lea .Ltable(%rip),%rcx
cmp (%rcx,%rdx,8),%rax
jne .Lhint
mov -16(%r9),%r10''')
    if diagnostic:code.append('incq 24(%r8)')
    code.append('.Lhint:')
    code.extend(f'prefetcht1 {64*i}(%r10)' for i in range(lines))
    code.append('jmp .Ldone')
    if diagnostic:code.append('.Lcollision:\nlock incq a3_data+65536(%rip)\njmp .Ldone')
    code.append('.balign 8\n.Ltable:\n'+ '\n'.join(f'.quad {a}' for a in table)+'\n.Ldone:')
    return '\n'.join(code),{'a3_image_base':0},{'bits':bits,'multiplier':multiplier,'entries':len(addresses)}
def discover(binary,training):
    evidence=json.loads(training.read_text())['before'];addresses=set()
    for rows in evidence['transitions'].values():
        for key,target,confidence,_ in rows:
            if confidence>=2:
                addresses.update(a-evidence['bias'] for a in (key,target) if a)
    with binary.open('rb') as f:
        header=f.read(64);off=struct.unpack_from('<Q',header,32)[0];size,n=struct.unpack_from('<HH',header,54);assert size==56
        f.seek(off);loads=[struct.unpack('<IIQQQQQQ',f.read(56)) for _ in range(n)]
        found=[]
        for address in sorted(addresses):
            for p in loads:
                if p[0]==1 and p[1]&1 and p[3]<=address and address+len(SIGNATURE)<=p[3]+p[5]:
                    f.seek(p[2]+address-p[3])
                    if f.read(len(SIGNATURE))==SIGNATURE:found.append(address)
    return found
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('training',type=Path);p.add_argument('out',type=Path);p.add_argument('--lines',type=int,choices=[1,3],default=1);p.add_argument('--diagnostic',action='store_true');a=p.parse_args()
    sha=hashlib.sha256(a.binary.read_bytes()).hexdigest();assert sha=='81a6d6c9c35181d5dbd202f72b9bb90f36eae9f3f92047148e4f803023bc8c36'
    addresses=discover(a.binary,a.training);code,symbols,table=assembly(addresses,a.lines,a.diagnostic)
    plan={'sha256':sha,'symbols':symbols,'data_bytes':69632 if a.diagnostic else 0,'mode':'queue_callback_resolution','lines':a.lines,'diagnostic':a.diagnostic,'adapter_addresses':addresses,'adapter_signature':SIGNATURE.hex(),'membership_table':table,'training_sha256':hashlib.sha256(a.training.read_bytes()).hexdigest(),'hooks':[{'site':SITE,'expected':EXPECTED,'assembly':code}]}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.with_suffix('.plan.json').write_text(json.dumps(plan,indent=2));m=build(a.binary,plan,a.out)
    assert len(m['hint_patches'])==a.lines,'Embedded table must not decode as additional hints'
    normal=a.out.read_bytes();nop=bytearray(Path(str(a.out)+'.nop').read_bytes())
    for x in m['hint_patches']:nop[x['offset']:x['offset']+len(bytes.fromhex(x['original']))]=bytes.fromhex(x['original'])
    assert normal==nop
