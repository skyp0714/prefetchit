"""Instruction-kind changes retain exact code addresses and program behavior."""
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
from make_nop_control_binary import executable_sections


def test_direct_it0_and_register_fallback(tmp_path):
    source=tmp_path/'probe.c'
    source.write_text(r'''
__attribute__((noinline)) int leaf(int x){volatile int v=x;return v+3;}
__attribute__((noinline)) int second(int x){return leaf(x)*2;}
int main(void){void *p=leaf;
 __asm__ volatile("prefetcht1 leaf(%%rip)\n\tprefetcht1 second(%%rip)\n\tprefetcht1 leaf(%%rip)\n\tprefetcht1 (%0)"::"r"(p));
 return second(2)!=10;}
''')
    binary=tmp_path/'probe'
    subprocess.run(['clang-19','-O2',str(source),'-o',str(binary)],check=True)
    sections=executable_sections(str(binary));sites=[]
    dis=subprocess.check_output(['objdump','-d','--insn-width=16',str(binary)],text=True)
    for line in dis.splitlines():
        m=re.match(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*)$',line)
        if not m or not m[3].startswith('prefetcht1'):continue
        va=int(m[1],16);raw=bytes.fromhex(m[2]);v,o,s=next((v,o,s) for v,o,s in sections if v<=va<v+s)
        sites.append(dict(va=hex(va),offset=o+va-v,original=raw.hex(),instruction=m[3]))
    with gzip.open(binary.with_suffix('.patches.json.gz'),'wt') as f:json.dump(sites,f)
    digest=hashlib.sha256(binary.read_bytes()).hexdigest();dest=tmp_path/'it0'
    with pytest.raises(AssertionError):lean_it0.patch(binary,dest,'0'*64)
    assert not dest.exists()
    record=lean_it0.patch(binary,dest,digest)
    assert record['it0_rip_sites']==3 and record['retained_t1_register_sites']==1
    assert record['changed_bytes']==3 and record['same_layout']
    subprocess.run([binary],check=True);subprocess.run([dest],check=True)
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==digest
    with pytest.raises(AssertionError):lean_it0.patch(binary,dest,digest)
    assert hashlib.sha256(dest.read_bytes()).hexdigest()==record['sha256']
    thin=tmp_path/'thin'
    reduced=lean_it0.deduplicate_groups(dest,binary.with_suffix('.patches.json.gz'),thin,record['sha256'])
    assert reduced['removed_hints']>=1 and reduced['direct_line_set_preserved_in_every_group']
    assert reduced['bytes']==record['bytes']
    subprocess.run([thin],check=True)
