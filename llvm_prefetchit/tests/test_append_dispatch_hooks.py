"""Execute ELF layout and call ABI tests for the restricted dispatch hooker."""
import importlib.util,hashlib,subprocess,struct
from pathlib import Path
import pytest
P=Path(__file__).resolve().parents[1]/'tools/append_dispatch_hooks.py'
s=importlib.util.spec_from_file_location('hooks',P);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
@pytest.mark.parametrize('pie',[False,True])
def test_preserves_original_addresses_abi_and_native_hint(tmp_path,pie):
 src=tmp_path/'test.c';asm=tmp_path/'test.s';base=tmp_path/'base'
 src.write_text('''#include <stdio.h>
extern long probe(long,long,long,long,long,long);
int main(){long s=0;for(long i=0;i<1000;i++)s+=probe(i,2,3,4,5,6);printf("%ld\\n",s);return s!=519500;}
''')
 asm.write_text('''.text
.globl probe
.type probe,@function
probe:
endbr64
.globl site
site:
.byte 0x0f,0x1f,0x44,0x00,0x00
prefetcht0 (%rsp)
lea (%rdi,%rsi),%rax
add %rdx,%rax
add %rcx,%rax
add %r8,%rax
add %r9,%rax
ret
.size probe,.-probe
.section .note.GNU-stack,"",@progbits
''')
 subprocess.run(['clang-19','-O2','-fcf-protection=full','-pie' if pie else '-no-pie',str(src),str(asm),'-o',str(base)],check=True)
 syms={x[2]:int(x[0],16) for l in subprocess.check_output(['nm',str(base)],text=True).splitlines() if len(x:=l.split())==3}
 plan={'sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'data_bytes':8192,'hooks':[{'site':syms['site'],'expected':'0f1f440000','assembly':'mov %rdi, a3_data(%rip)\nlea probe_unused(%rip), %r11\nprefetcht1 (%r11)\nprobe_unused:'}]}
 out=tmp_path/'hook';m=h.build(base,plan,out)
 for exe in [base,out,Path(str(out)+'.nop')]:assert subprocess.check_output([str(exe)],text=True)=='519500\n'
 b=base.read_bytes();patched=out.read_bytes();allowed=set(range(32,40))|set(range(56,58))
 for x in m['hooks']:allowed.update(range(x['offset'],x['offset']+x['size']))
 assert all(a==c or i in allowed for i,(a,c) in enumerate(zip(b,patched)))
 assert b'\x0f\x18\x0c\x24' in patched # native prefetcht0 is untouched
 twin=Path(str(out)+'.nop').read_bytes();allowed={i for p in m['hint_patches'] for i in range(p['offset'],p['offset']+len(bytes.fromhex(p['original'])))}
 assert all(a==c or i in allowed for i,(a,c) in enumerate(zip(patched,twin)))
 with pytest.raises(AssertionError,match='fingerprint'):
  h.build(base,{**plan,'sha256':'0'*64},tmp_path/'bad')
