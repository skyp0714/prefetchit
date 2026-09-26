import importlib.util
from pathlib import Path
import sys

tools=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(tools))
spec=importlib.util.spec_from_file_location('exec_padding',tools/'index_executable_padding.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_internal_code_needs_no_function_symbol_but_must_be_executable():
    disassembly=('0000000000001000 <exported>:\n'
                 ' 1010:\t0f 1f 80 00 00 00 00\tnopl 0x0(%rax)\n'
                 ' 3010:\t0f 1f 80 00 00 00 00\tnopl 0x0(%rax)\n')
    assert module.parse_slots(disassembly,[(0x1000,0x200,0x100)])==[[0x1010,0x210,7,0x1100,'0f1f8000000000']]

def test_noncanonical_and_section_crossing_nops_are_excluded():
    disassembly=(' 1010:\t0f 1f 80 01 00 00 00\tnopl 0x1(%rax)\n'
                 ' 10fc:\t0f 1f 80 00 00 00 00\tnopl 0x0(%rax)\n')
    assert module.parse_slots(disassembly,[(0x1000,0x200,0x100)])==[]


def test_long_single_nops_are_allowed_but_arbitrary_prefixes_are_not():
    body=bytes.fromhex('0f1f840000000000')
    assert module.is_padding_nop(b'\x66\x2e'+body)
    assert module.is_padding_nop(b'\x66'*7+body)
    assert not module.is_padding_nop(b'\x66'*8+body)
    assert not module.is_padding_nop(b'\xf0'+body)

def test_long_replacement_decodes_as_one_prefetch(tmp_path):
    import subprocess,struct
    for length in [9,10,15]:
        raw=b'\x66'*(length-7)+bytes.fromhex('0f1815')+struct.pack('<i',0x200-length)
        binary=tmp_path/f'prefetch{length}.bin';binary.write_bytes(raw)
        assembly=subprocess.check_output(['objdump','-D','-b','binary','-m','i386:x86-64','--insn-width=16',str(binary)],text=True)
        assert assembly.count('prefetcht1')==1
        assert '(bad)' not in assembly
        assert '0x200' in assembly
