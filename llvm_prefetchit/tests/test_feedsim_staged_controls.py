"""Exact partial controls execute unchanged work and reject unrelated differences."""
import subprocess,sys,re
from pathlib import Path
import pytest
TOOLS=Path(__file__).resolve().parents[1]/'tools';sys.path.insert(0,str(TOOLS))
from split_feedsim_staged_hints import build

@pytest.mark.parametrize('entry_reg,body_reg,prologue,epilogue',[
    ('rdi','rsi','',''),
    ('r8','rsi','mov %rdi,%r8\n',''),
    ('r8','rbp','push %rbp\nmov %rsi,%rbp\nmov %rdi,%r8\n','pop %rbp\n'),
    ('r13','r12','push %r12\npush %r13\nmov %rdi,%r13\nmov %rsi,%r12\n','pop %r13\npop %r12\n'),
])
def test_staged_component_control(tmp_path,entry_reg,body_reg,prologue,epilogue):
    c=tmp_path/'test.c';s=tmp_path/'test.s';binary=tmp_path/'test';nop=tmp_path/'nop'
    c.write_text('extern int probe(char*,char*);int main(){char a[256]={4};return probe(a,a)!=11;}\n')
    s.write_text('.text\n.globl probe\n.type probe,@function\nprobe:\n'+prologue+
                 (f'prefetcht1 (%{entry_reg})\nprefetcht1 64(%{body_reg})\nprefetcht1 128(%{body_reg})\n')*3+
                 'movzbl (%rdi),%eax\naddl $7,%eax\n'+epilogue+'ret\n.size probe,.-probe\n.section .note.GNU-stack,"",@progbits\n')
    subprocess.run(['clang-19',str(c),str(s),'-o',str(binary)],check=True)
    subprocess.run(['python3',str(TOOLS/'make_nop_control_binary.py'),'--input',str(binary),'--output',str(nop),'--symbol','probe','--mnemonics','prefetcht1'],check=True)
    for name,keep,count in [('entry',{0},3),('body',{64,128},6)]:
        out=tmp_path/name;meta=build(binary,nop,out,'probe',keep)
        assert sum(x['kept'] for x in meta['sites'])==count
        subprocess.run([str(out)],check=True)
    near=tmp_path/'near';meta=build(binary,nop,near,'probe',{0,64,128},near_entry=True)
    assert sum('near_base_register' in x for x in meta['sites'])==3
    assert all(len(x['after'])==len(x['before']) for x in meta['sites'] if 'after' in x)
    decoded=subprocess.check_output(['objdump','-d','--disassemble=probe',str(near)],text=True)
    assert len(re.findall(r'prefetcht1\s+(?:0x0)?\(%'+body_reg+r'\)',decoded))==3
    subprocess.run([str(near)],check=True)
    wrong=tmp_path/'wrong';raw=bytearray(nop.read_bytes());raw[-1]^=1;wrong.write_bytes(raw)
    with pytest.raises(AssertionError,match='outside selected staged hint sites'):
        build(binary,wrong,tmp_path/'rejected','probe',{0})
