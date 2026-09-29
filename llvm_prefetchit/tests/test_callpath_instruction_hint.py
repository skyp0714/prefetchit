"""Audited stub hints change opcode without touching an application's prefetch."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
import dense_build as b
from callpath_instruction_hint import build,Elf


def test_native_opcode_and_fingerprint(tmp_path,monkeypatch):
    monkeypatch.setattr(b,'space',lambda path:None)
    source=tmp_path/'main.c';assembly=tmp_path/'stub.s';binary=tmp_path/'main'
    source.write_text('extern int stub(int); __attribute__((noinline)) int target(int x){return x+19;} int main(){__asm__ volatile("prefetcht1 target(%%rip)":::"memory");return stub(23)!=42;}\n')
    assembly.write_text('''
.section .text.prefetch_calls,"ax",@progbits
.globl stub
.type stub,@function
stub:
.cfi_startproc
prefetcht1 target(%rip)
jmp target
.cfi_endproc
.size stub,.-stub
.section .note.GNU-stack,"",@progbits
''')
    # Keep the dedicated output section rather than letting the default linker
    # merge .text.* into .text; this is the audited production layout.
    script=tmp_path/'sections.ld'
    script.write_text('SECTIONS { .text.prefetch_calls : { *(.text.prefetch_calls) } } INSERT BEFORE .text;\n')
    command=['gcc','-O2','-fno-pie','-no-pie','-Wl,--build-id=none','-Wl,-T,'+str(script),str(source),str(assembly),'-o',str(binary)]
    subprocess.run(command,check=True)
    symbols={parts[2]:int(parts[0],16) for line in subprocess.check_output(['nm',str(binary)],text=True).splitlines() if len(parts:=line.split())==3}
    raw=binary.read_bytes();elf=Elf(raw);offset=elf.offset(symbols['stub'],7,True)
    record=dict(sha256=b.sha(binary),nop_sha256='unused-fixture-nop',hints=[dict(va=symbols['stub'],offset=offset,target=symbols['target'],original=raw[offset:offset+7].hex())])
    Path(str(binary)+'.json').write_text(json.dumps(record))
    subprocess.run([str(binary)],check=True)
    for kind in ['it0','it1']:
        dest=tmp_path/kind;result=build(binary,dest,kind);subprocess.run([str(dest)],check=True)
        changed=dest.read_bytes();assert result['sites']==1
        assert [i for i,(left,right) in enumerate(zip(raw,changed)) if left!=right]==[offset+2]
        disassembly=subprocess.check_output(['objdump','-d',str(dest)],text=True)
        assert 'prefetcht1' in disassembly and 'prefetch'+kind in disassembly
    damaged=bytearray(raw);damaged[-1]^=1;binary.write_bytes(damaged)
    with pytest.raises(AssertionError,match='fingerprint'):build(binary,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()
