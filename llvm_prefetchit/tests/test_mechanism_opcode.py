"""Executable opcode ablation must preserve addresses and exact T1 reversal."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import pytest

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'llvm_prefetchit/scripts/class_b'))
sys.path.insert(0,str(REPO/'llvm_prefetchit/tools'))
import lean_it0
import mechanism_study as m
from make_nop_control_binary import executable_sections

def test_roundtrip_and_it1(tmp_path):
    source=tmp_path/'source.c'
    source.write_text('''
__attribute__((noinline)) int leaf(int x){return x*3;}
int main(void){__asm__ volatile("prefetcht1 leaf(%%rip)":::"memory");return leaf(2)!=6;}
''')
    t1=tmp_path/'original'
    subprocess.run(['clang-19','-O2',str(source),'-o',str(t1)],check=True)
    sections=executable_sections(str(t1));sites=[]
    dis=subprocess.check_output(['objdump','-d','--insn-width=16',str(t1)],text=True)
    for line in dis.splitlines():
        match=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
        if not match or not match[3].startswith('prefetcht1'):continue
        va=int(match[1],16);v,o,size=next(s for s in sections if s[0]<=va<s[0]+s[2])
        sites.append(dict(va=hex(va),offset=o+va-v,original=bytes.fromhex(match[2]).hex(),instruction=match[3]))
    with gzip.open(t1.with_suffix('.patches.json.gz'),'wt') as f:json.dump(sites,f)
    it0=tmp_path/'it0';lean_it0.patch(t1,it0,hashlib.sha256(t1.read_bytes()).hexdigest())
    restored=tmp_path/'restored';m.opcode_variant(it0,restored,'t1')
    assert restored.read_bytes()==t1.read_bytes()
    it1=tmp_path/'it1';record=m.opcode_variant(it0,it1,'it1')
    assert record['sites']==1 and record['same_layout']
    it1dis=subprocess.check_output(['objdump','-d',str(it1)],text=True)
    assert 'prefetchit1' in it1dis
    for binary in [t1,it0,it1,restored]:subprocess.run([binary],check=True)
    with pytest.raises(AssertionError):m.opcode_variant(it0,it1,'it1')
    with pytest.raises(AssertionError):m.opcode_variant(it0,tmp_path/'invalid','t0')
    damaged=bytearray(it0.read_bytes());damaged[-1]^=1;it0.write_bytes(damaged)
    with pytest.raises(AssertionError):m.opcode_variant(it0,tmp_path/'damaged','t1')
    assert not (tmp_path/'damaged').exists()

def test_retargeted_metadata_supports_both_instruction_hints(tmp_path,monkeypatch):
    import dense_build as b
    from lean_plan import RECORD,SECTION,read_image
    from retarget_opcodes import build
    monkeypatch.setattr(b,'space',lambda p:None)  # Tiny fixture, not a benchmark build.
    source=tmp_path/'metadata.c'
    source.write_text(r'''
__attribute__((noinline)) int leaf(int x){volatile int y=x;return y*3;}
__attribute__((noinline)) int future(int x){volatile int y=x;return y*5;}
int main(void){__asm__ volatile(".globl hint_site\nhint_site:\nprefetcht1 future(%%rip)\nlea leaf(%%rip),%%rax\n.globl indirect_site\nindirect_site:\nprefetcht1 (%%rax)":::"rax","memory");return leaf(2)+future(3)!=21;}
''')
    raw=tmp_path/'raw'
    subprocess.run(['gcc','-O2','-fno-pie','-no-pie',str(source),'-o',str(raw)],check=True)
    syms={p[2]:int(p[0],16) for line in subprocess.check_output(['nm','-n',str(raw)],text=True).splitlines() if len(p:=line.split())==3}
    meta=tmp_path/'metadata';meta.write_bytes(
        RECORD.pack(syms['hint_site'],syms['future'],1,2,3,4,5,3)+
        RECORD.pack(syms['indirect_site'],0,1,2,3,4,6,1))
    binary=tmp_path/'retargeted'
    subprocess.run(['objcopy','--add-section',f'{SECTION}={meta}',str(raw),str(binary)],check=True)
    original=read_image(binary);variants=build(binary,tmp_path/'variants')
    for kind,row in variants.items():
        path=Path(row['path']);subprocess.run([str(path)],check=True)
        assert read_image(path)['records']==original['records']
        assert row['direct_sites']==1 and row['fully_reversible'] and row['target_displacements_unchanged']
        before=binary.read_bytes();after=path.read_bytes()
        assert [i for i,(x,y) in enumerate(zip(before,after)) if x!=y]==row['byte_offsets']
