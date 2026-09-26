"""Reject conditional and indirect paths when selecting forwarding wrappers."""
from pathlib import Path
import subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from entry_callee_map import entry_callees,bounded_entry_callee

def test_first_transfer_is_required(tmp_path):
    assembly=tmp_path/'test.s';binary=tmp_path/'test'
    bodies={'leaf':'ret','forward':'nop\ncall leaf\nret','tail':'endbr64\njmp leaf',
            'conditional':'test %edi,%edi\nje 1f\ncall leaf\n1: ret',
            'indirect':'call *%rdi\ncall leaf\nret','return_first':'ret\ncall leaf\nret',
            'trap_first':'ud2\ncall leaf\nret','syscall_first':'syscall\ncall leaf\nret'}
    assembly.write_text('.text\n'+'\n'.join(f'.globl {name}\n.type {name},@function\n{name}:\n{body}\n.size {name},.-{name}' for name,body in bodies.items())+'\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['clang-19','-nostdlib','-Wl,-e,forward',str(assembly),'-o',str(binary)],check=True)
    symbols={}
    for line in subprocess.check_output(['nm','-S','--defined-only',str(binary)],text=True).splitlines():
        f=line.split()
        if len(f)==4 and f[2] in 'Tt':symbols[f[3]]=(int(f[0],16),int(f[1],16))
    result=entry_callees(binary,{addr:size for addr,size in symbols.values()})
    assert result=={symbols['forward'][0]:symbols['leaf'][0],symbols['tail'][0]:symbols['leaf'][0]}
    stripped=tmp_path/'stripped'
    subprocess.run(['objcopy','--strip-all',str(binary),str(stripped)],check=True)
    bounds={addr:size for addr,size in symbols.values()}
    for name,(address,size) in symbols.items():
        assert bounded_entry_callee(stripped,address,size,bounds)==result.get(address)

def test_bounded_rejects_notrack_indirect(tmp_path):
    source=tmp_path/'indirect.s';binary=tmp_path/'indirect'
    source.write_text('.text\n.globl probe,leaf\n.type probe,@function\nprobe:\nnotrack jmp *%rdi\ncall leaf\nret\n.size probe,.-probe\n.type leaf,@function\nleaf:\nret\n.size leaf,.-leaf\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['clang-19','-nostdlib','-Wl,-e,probe',str(source),'-o',str(binary)],check=True)
    symbols={}
    for line in subprocess.check_output(['nm','-S','--defined-only',str(binary)],text=True).splitlines():
        f=line.split()
        if len(f)==4 and f[2] in 'Tt':symbols[f[3]]=(int(f[0],16),int(f[1],16))
    address,size=symbols['probe']
    assert bounded_entry_callee(binary,address,size,{a:s for a,s in symbols.values()}) is None
    assert entry_callees(binary,{a:s for a,s in symbols.values()})=={}
