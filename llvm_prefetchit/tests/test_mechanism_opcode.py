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
