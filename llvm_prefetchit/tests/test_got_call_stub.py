"""Cross-DSO hints must preserve ABI/CFI, lazy binding and PIE relocation."""
import importlib.util
from pathlib import Path
import re
import struct
import subprocess
import pytest

PATH=Path(__file__).resolve().parents[1]/'tools/call_stub_prefetch.py'
SPEC=importlib.util.spec_from_file_location('got_call_stub',PATH)
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


@pytest.mark.parametrize('pie',[False,True])
@pytest.mark.parametrize('binding',['lazy','now'])
@pytest.mark.parametrize('alignment',['compact','cache_line'])
def test_external_anchor_preserves_registers_flags_unwind(tmp_path,pie,binding,alignment):
    lib=tmp_path/'target.cc';main=tmp_path/'main.cc';asm=tmp_path/'invoke.s';base=tmp_path/'base'
    lib.write_text('extern "C" long target(long x){if(x<0)throw x;return x+10;}\n')
    main.write_text('''
#include <stdio.h>
extern "C" long invoke(long);
int main(){for(int i=0;i<2;i++){if(invoke(7)!=17)return 1;
bool caught=false;try{invoke(-3);}catch(long x){caught=x==-3;}if(!caught)return 2;}
puts("cross-dso-ok");}
''')
    asm.write_text('''
.text
.global invoke
.type invoke,@function
invoke:
.cfi_startproc
sub $8,%rsp
.cfi_adjust_cfa_offset 8
mov $12345,%r11
stc
.global call_probe
call_probe:
call entry
add $8,%rsp
.cfi_adjust_cfa_offset -8
ret
.cfi_endproc
.size invoke,.-invoke
.type entry,@function
entry:
.cfi_startproc
jnc failed
cmp $12345,%r11
jne failed
jmp target@PLT
failed:
mov $-100,%rax
ret
.cfi_endproc
.size entry,.-entry
.section .note.GNU-stack,"",@progbits
''')
    subprocess.run(['clang++-19','-shared','-fPIC','-O2',str(lib),'-o',str(tmp_path/'libtarget.so')],check=True)
    subprocess.run(['clang++-19','-O2','-pie' if pie else '-no-pie',str(main),str(asm),
        '-L'+str(tmp_path),'-ltarget','-Wl,-rpath,'+str(tmp_path),'-Wl,-z,'+binding,'-o',str(base)],check=True)
    symbols={f[2]:int(f[0],16) for line in subprocess.check_output(['nm',str(base)],text=True).splitlines() if len(f:=line.split())==3}
    relocation=subprocess.check_output(['readelf','-rW',str(base)],text=True)
    got=int(re.search(r'^([0-9a-f]+)\s+\S+\s+R_X86_64_JUMP_SLOT\s+\S+\s+target\s',relocation,re.M)[1],16)
    raw=base.read_bytes();elf=m.Elf(raw);site=symbols['call_probe'];offset=elf.offset(site,5,True)
    call=dict(site=site,callee=site+5+struct.unpack_from('<i',raw,offset+1)[0],expected=raw[offset:offset+5].hex(),
        targets=[],got_targets=[dict(got=got,addend=0),dict(got=got,addend=64)])
    plan=dict(sha256=m.sha(raw),calls=[call],stub_alignment=alignment);out=tmp_path/'prefetch'
    record=m.build(base,plan,out)
    for binary in (base,out,Path(str(out)+'.nop')):
        assert subprocess.check_output([str(binary)],text=True)=='cross-dso-ok\n'
    assert record['registers_and_flags_preserved'] and not record['registers_and_flags_untouched']
    assert len(record['hints'])==2 and all(h['kind']=='t1_got' and h['length']==8 for h in record['hints'])
    candidate=out.read_bytes();nop=Path(str(out)+'.nop').read_bytes()
    jump=record['patches'][0]['terminal_jumps'][0]
    jump_offset=m.Elf(candidate).offset(jump,5,True)
    assert candidate[jump_offset]==0xe9
    assert jump+5+struct.unpack_from('<i',candidate,jump_offset+1)[0]==call['callee']
    if alignment=='cache_line':assert record['patches'][0]['stub']//64==(jump+4)//64
    allowed={i for h in record['hints'] for i in range(h['offset'],h['offset']+8)}
    assert len(candidate)==len(nop) and all(a==b or i in allowed for i,(a,b) in enumerate(zip(candidate,nop)))
    with pytest.raises(AssertionError,match='existing GLOB_DAT'):
        m.build(base,dict(plan,calls=[dict(call,got_targets=[dict(got=site,addend=0)])]),tmp_path/'bad')
