"""An actual ELF checks code layout, flag effects, loop exclusion and reversal."""
import importlib.util
from pathlib import Path
import subprocess

spec=importlib.util.spec_from_file_location('wake_padding',Path(__file__).resolve().parents[1]/'scripts/class_b/padding_stream.py')
padding=importlib.util.module_from_spec(spec);spec.loader.exec_module(padding)


def test_actual_elf_preserves_flags_layout_and_native_hint(tmp_path):
    source=tmp_path/'source.s'
    source.write_text('''
.text
.globl main
.type main,@function
main:
 mov $5,%eax
 stc
 .byte 0x0f,0x1f,0x80,0,0,0,0
 adc $0,%eax
 mov $2,%ecx
.Lloop:
 .byte 0x0f,0x1f,0x84,0,0,0,0,0
 dec %ecx
 jne .Lloop
 prefetcht1 helper(%rip)
 ret
.size main,.-main
.p2align 6
.globl helper
.type helper,@function
helper:
 ret
.size helper,.-helper
.section .note.GNU-stack,"",@progbits
''')
    binary=tmp_path/'base';output=tmp_path/'prefetched'
    subprocess.run(['cc',str(source),'-o',str(binary)],check=True)
    try:
        data=binary.read_bytes();slots,meta=padding.inventory(binary,data)
        slots=[s for s in slots if s['function']=='main']
        assert len(slots)==1 # the NOP reached through a backward branch is excluded
        symbols=subprocess.check_output(['nm',str(binary)],text=True).splitlines()
        target=next(int(s.split()[0],16) for s in symbols if s.split()[-1]=='helper')
        assert target%64==0
        types={'run':(20,[dict(p=1,dso='base',line=slots[0]['va']&~63),
                         dict(p=1,dso='base',line=target)])}
        chosen=padding.choose(slots,types,'base',1,4,10,2)
        assert len(chosen)==1 and chosen[0]['target']==target
        result,patches=padding.patch(data,chosen)
        assert len(result)==len(data)
        output.write_bytes(result);output.chmod(0o755)
        assert subprocess.run([str(binary)]).returncode==6
        assert subprocess.run([str(output)]).returncode==6
        dis=subprocess.check_output(['objdump','-d',str(output)],text=True)
        assert dis.count('prefetcht1')==2 # preexisting native hint retained
        restored=bytearray(result)
        for p in patches:
            restored[p['offset']:p['offset']+p['size']]=bytes.fromhex(p['before'])
        assert restored==data
        all_slots,_=padding.inventory(binary,data,allow_loops=True)
        loop_slots=[dict(s,target=target) for s in all_slots if s['function']=='main']
        assert len(loop_slots)==2
        repeated,_=padding.patch(data,loop_slots)
        output.write_bytes(repeated)
        assert subprocess.run([str(output)]).returncode==6
    finally:
        binary.unlink(missing_ok=True);output.unlink(missing_ok=True)
