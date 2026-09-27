"""A NOP twin must cover custom executable sections without removing data PFs."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_readonly_binary_custom_text_section(tmp_path):
    cc = shutil.which('clang-19') or shutil.which('cc')
    if not cc:
        pytest.skip('C compiler required')
    source = tmp_path / 'example.c'
    source.write_text('''
__attribute__((noinline, section("google_malloc"))) void custom(void) {
  __asm__ volatile("prefetcht1 0(%%rip)\\n\\tprefetcht0 0(%%rip)" ::: "memory");
}
int main(void) {
  __asm__ volatile("prefetcht1 0(%%rip)\\n\\tdata16 prefetcht1 0(%%rip)" ::: "memory");
  custom(); return 0;
}
''')
    binary, twin = tmp_path/'base', tmp_path/'twin'
    subprocess.run([cc, '-O2', str(source), '-o', str(binary)], check=True)
    original = binary.read_bytes()
    binary.chmod(0o555)
    script = Path(__file__).resolve().parents[1]/'tools/make_nop_control_binary.py'
    cmd = [sys.executable,str(script),'--input',str(binary),'--output',str(twin),'--mnemonics','prefetcht1']
    subprocess.run(cmd, check=True, capture_output=True)
    assert binary.read_bytes() == original
    changed = twin.read_bytes()
    assert len(changed) == len(original)
    assert changed != original
    dis = subprocess.check_output(['objdump','-d',str(twin)],text=True)
    assert 'prefetcht1' not in dis.split()
    assert '\tprefetcht0 ' in dis
    subprocess.run([str(twin)], check=True)
    twin.chmod(0o555)
    subprocess.run(cmd, check=True, capture_output=True)
    assert twin.read_bytes() == changed
    symbol_file=tmp_path/'symbols.txt'
    symbol_file.write_text('main\ncustom\n')
    subprocess.run(cmd+['--symbols-file',str(symbol_file)],check=True,capture_output=True)
    assert twin.read_bytes()==changed


def test_factorial_addressing_controls_commute(tmp_path):
    cc = shutil.which('clang-19') or shutil.which('cc')
    if not cc:
        pytest.skip('C compiler required')
    source = tmp_path/'factorial.c'
    source.write_text('''
int main(void) {
  void *target = (void *)&main;
  __asm__ volatile("prefetcht1 0(%%rip)\\n\\tmov %0, %%r12\\n\\tprefetcht1 128(%%r12)\\n\\tprefetcht0 (%0)"
                   : : "r"(target) : "r12");
  return 0;
}
''')
    binary = tmp_path/'both'
    subprocess.run([cc,'-O2',str(source),'-o',str(binary)],check=True)
    original=binary.read_bytes()
    script=Path(__file__).resolve().parents[1]/'tools/make_nop_control_binary.py'
    def patch(src, dst, form):
        subprocess.run([sys.executable,str(script),'--input',str(src),
                        '--output',str(dst),'--mnemonics','prefetcht1',
                        '--addressing',form],check=True,capture_output=True)
        subprocess.run([str(dst)],check=True)
    register, rip = tmp_path/'register', tmp_path/'rip'
    patch(binary,register,'rip'); patch(binary,rip,'register')
    for survivor, operand in [(register, '0x80(%r12)'), (rip, '(%rip)')]:
        dis=subprocess.check_output(['objdump','-d',str(survivor)],text=True)
        hints=[s for s in dis.splitlines() if '\tprefetcht1 ' in s]
        assert len(hints)==1 and operand in hints[0]
        assert '\tprefetcht0 ' in dis
    a,b,c=[tmp_path/x for x in ('a','b','c')]
    patch(register,a,'register');patch(rip,b,'rip');patch(binary,c,'all')
    assert a.read_bytes()==b.read_bytes()==c.read_bytes()
    assert binary.read_bytes()==original and len(a.read_bytes())==len(original)


def test_relocatable_overlapping_section_addresses_require_explicit_section(tmp_path):
    source = tmp_path/'section.s'
    source.write_text('.text\n.globl emit\n.type emit,@function\nemit:\n'
                      'prefetcht1 (%rax)\nret\n.size emit,.-emit\n'
                      '.section .init.text,"ax"\n.fill 256,1,0x90\n')
    binary, twin = tmp_path/'module.o', tmp_path/'nop.o'
    subprocess.run(['cc','-c',str(source),'-o',str(binary)],check=True)
    original = binary.read_bytes()
    script = Path(__file__).resolve().parents[1]/'tools/make_nop_control_binary.py'
    command = [sys.executable,str(script),'--input',str(binary),'--output',str(twin),'--symbol','emit']
    rejected = subprocess.run(command,capture_output=True,text=True)
    assert rejected.returncode != 0 and 'cannot map executable address' in rejected.stderr
    subprocess.run(command+['--section','.text'],check=True,capture_output=True)
    assert binary.read_bytes() == original and len(twin.read_bytes()) == len(original)
    dis = subprocess.check_output(['objdump','-d','--disassemble=emit',str(twin)],text=True)
    assert 'prefetcht1' not in dis and 'nopl' in dis


def test_explicit_section_limits_disassembly_and_preserves_other_sections(tmp_path):
    source = tmp_path/'sections.s'
    source.write_text('.text\nprefetcht1 (%rax)\nret\n'
                      '.section .init.text,"ax"\nprefetcht1 (%rbx)\nret\n')
    binary, twin = tmp_path/'module.o', tmp_path/'nop.o'
    subprocess.run(['cc','-c',str(source),'-o',str(binary)],check=True)
    script = Path(__file__).resolve().parents[1]/'tools/make_nop_control_binary.py'
    subprocess.run([sys.executable,str(script),'--input',str(binary),'--output',str(twin),
                    '--section','.text'],check=True,capture_output=True)
    text = subprocess.check_output(['objdump','-d','-j','.text',str(twin)],text=True)
    init = subprocess.check_output(['objdump','-d','-j','.init.text',str(twin)],text=True)
    assert 'prefetcht1' not in text and 'nopl' in text
    assert 'prefetcht1' in init and '(%rbx)' in init
    assert sum(a != b for a,b in zip(binary.read_bytes(),twin.read_bytes())) == 2
