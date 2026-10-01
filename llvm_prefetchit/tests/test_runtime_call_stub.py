"""Live virtual target loads preserve call ABI, flags and exact NOP layout."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import pytest

PATH=Path(__file__).resolve().parents[1]/'tools/call_stub_prefetch.py'
SPEC=importlib.util.spec_from_file_location('runtime_stub',PATH)
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

@pytest.mark.parametrize('pie',[False,True])
@pytest.mark.parametrize('register',['rbx','rbp','r12','r13','r14','r15'])
def test_live_virtual_chain(tmp_path,pie,register):
    cpp=tmp_path/'main.cc';asm=tmp_path/'invoke.s';base=tmp_path/'base'
    cpp.write_text(r"""
#include <cstdio>
struct Iface { virtual ~Iface(){}; virtual long run(long)=0; };
struct A: Iface { long run(long x) override {if(x<0)throw x;return x+5;} };
struct B: Iface { long run(long x) override {if(x<0)throw x;return x+9;} };
struct Processor { long pad[3]; Iface *iface; };
extern "C" long invoke(Processor*,long);
extern "C" long decode(Processor *p,long x){return p->iface->run(x);}
int main(){A a;B b;for(Iface *f:{static_cast<Iface*>(&a),static_cast<Iface*>(&b)}) {
Processor p={{0,0,0},f};if(invoke(&p,7)!=f->run(7))return 1;
bool caught=false;try{invoke(&p,-3);}catch(long x){caught=x==-3;}if(!caught)return 2;}
puts("runtime-target-ok");}
""".replace('#include <cstdio>','#include <cstdio>\n#include <initializer_list>'))
    asm.write_text(r"""
.text
.global invoke
.type invoke,@function
invoke:
.cfi_startproc
push %BASE
.cfi_adjust_cfa_offset 8
.cfi_offset %BASE,-16
mov %rdi,%BASE
mov $12345,%r11
stc
.global call_probe
call_probe:
call verify
pop %BASE
.cfi_adjust_cfa_offset -8
.cfi_restore %BASE
ret
.cfi_endproc
.size invoke,.-invoke
.type verify,@function
verify:
.cfi_startproc
jnc failed
cmp $12345,%r11
jne failed
jmp decode
failed:
mov $-100,%rax
ret
.cfi_endproc
.size verify,.-verify
.section .note.GNU-stack,"",@progbits
""".replace('BASE',register))
    subprocess.run(['clang++-19','-O2','-pie' if pie else '-no-pie',str(cpp),str(asm),'-o',str(base)],check=True)
    symbols={f[2]:int(f[0],16) for line in subprocess.check_output(['nm',str(base)],text=True).splitlines() if len(f:=line.split())==3}
    raw=base.read_bytes();elf=m.Elf(raw);site=symbols['call_probe'];off=elf.offset(site,5,True)
    row=dict(site=site,callee=site+5+struct.unpack_from('<i',raw,off+1)[0],expected=raw[off:off+5].hex(),targets=[],
        runtime_target=dict(base=register,offsets=[24,0,16],addends=[0,64,128,192],live_immutable_chain_proof='Fixture has a live Processor and iface throughout invoke.'))
    output=tmp_path/'pf';record=m.build(base,dict(sha256=m.sha(raw),calls=[row]),output)
    for binary in (base,output,Path(str(output)+'.nop')):
        assert subprocess.check_output([str(binary)],text=True)=='runtime-target-ok\n'
    assert len(record['hints'])==4 and all(h['kind']=='t1_runtime' for h in record['hints'])
    assert record['registers_and_flags_preserved'] and not record['registers_and_flags_untouched']
    pf=output.read_bytes();nop=Path(str(output)+'.nop').read_bytes()
    allowed={i for h in record['hints'] for i in range(h['offset'],h['offset']+8)}
    assert len(pf)==len(nop) and all(a==b or i in allowed for i,(a,b) in enumerate(zip(pf,nop)))
    with pytest.raises(AssertionError,match='live-object proof'):
        row['runtime_target']['live_immutable_chain_proof']=''
        m.build(base,dict(sha256=m.sha(raw),calls=[row]),tmp_path/'bad')
