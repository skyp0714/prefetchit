from pathlib import Path
import hashlib,json,subprocess,sys


def test_padding_prefetch_is_reversible_and_preserves_native_hint(tmp_path):
    asm=tmp_path/'sample.s'
    asm.write_text('''
.text
.globl main
.type main,@function
main:
 prefetcht1 main(%rip)
 .byte 0x0f,0x1f,0x80,0,0,0,0
 .rept 40
 nop
 .endr
 call helper
 xor %eax,%eax
 ret
.size main,.-main
.globl helper
.type helper,@function
helper:
 ret
.size helper,.-helper
.section .note.GNU-stack,"",@progbits
''')
    base=tmp_path/'base'
    subprocess.run(['clang-19',str(asm),'-o',str(base)],check=True)
    tool=Path(__file__).resolve().parents[1]/'tools/prefetch_in_padding.py'
    out=tmp_path/'pf'
    subprocess.run([sys.executable,str(tool),str(base),str(out),'--distance','128','--next-call','--functions','main|helper','--index',str(tmp_path/'index.json')],check=True)
    meta=json.loads(out.with_suffix('.json').read_text());assert meta['sites']==1
    original=base.read_bytes();patched=bytearray(out.read_bytes());assert len(original)==len(patched)
    for entry in meta['patches']:
        off=entry['offset'];raw=bytes.fromhex(entry['before'])
        assert original[off:off+len(raw)]==raw
        patched[off:off+len(raw)]=raw
    assert patched==original
    assert meta['reversed_patches_sha256']==hashlib.sha256(original).hexdigest()
    dis=subprocess.check_output(['objdump','-d',str(out)],text=True)
    assert dis.count('prefetcht1')==2
    subprocess.run([str(out)],check=True)


def test_symbol_scoped_nop_preserves_hints_in_other_functions(tmp_path):
    source=tmp_path/'scope.c'
    source.write_text('__attribute__((noinline)) void helper(void) { __asm__ volatile("prefetcht1 (%rax)"); }\nint main(void) { __asm__ volatile("prefetcht1 (%rax)"); return 0; }')
    base=tmp_path/'base';out=tmp_path/'control'
    subprocess.run(['clang-19',str(source),'-o',str(base)],check=True)
    tool=Path(__file__).resolve().parents[1]/'tools/make_nop_control_binary.py'
    subprocess.run([sys.executable,str(tool),'--input',str(base),'--output',str(out),'--mnemonics','prefetcht1','--symbol','main'],check=True)
    dis=subprocess.check_output(['objdump','-d',str(out)],text=True)
    main=subprocess.check_output(['objdump','-d','--disassemble=main',str(out)],text=True)
    assert dis.count('prefetcht1')==1 and 'prefetcht1' not in main
    assert len(out.read_bytes())==len(base.read_bytes())
