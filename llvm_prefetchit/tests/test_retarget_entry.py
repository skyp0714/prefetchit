import json
from pathlib import Path
import subprocess
import sys


def test_entry_retarget_preserves_non_prefetch_bytes_and_rejects_overflow(tmp_path):
    src=tmp_path/'sample.c'
    src.write_text('''
__attribute__((noinline)) int b(void) { return 1; }
__attribute__((noinline)) int c(void) { return 2; }
__attribute__((noinline)) int d(void) { return 3; }
__attribute__((noinline)) int a(void) {
 __asm__ volatile("prefetcht1 b(%%rip); prefetcht1 c(%%rip); prefetcht0 b(%%rip)":::"memory");
 return b()+c();
}
int main(void) { return a()!=3; }
''')
    binary=tmp_path/'input'
    subprocess.run(['clang-19',str(src),'-o',str(binary)],check=True)
    old=tmp_path/'old.json'; new=tmp_path/'new.json'
    old.write_text(json.dumps({'sites':{'a':{'t':[['b',0,0],['c',0,0]],'k':14}}}))
    new.write_text(json.dumps({'sites':{'a':{'t':[['d',0,0]],'k':7}}}))
    tool=Path(__file__).resolve().parents[1]/'tools/retarget_entry_prefetch.py'
    result=tmp_path/'result'
    subprocess.run([sys.executable,str(tool),str(binary),str(old),str(new),str(result)],check=True)
    assert len(binary.read_bytes())==len(result.read_bytes())
    dis=subprocess.check_output(['objdump','-d',str(result)],text=True)
    hints=[line for line in dis.splitlines() if 'prefetcht1' in line]
    assert len(hints)==1 and '<d>' in hints[0]
    assert 'prefetcht0' in dis
    subprocess.run([str(result)],check=True)
    new.write_text(json.dumps({'sites':{'a':{'t':[['d',0,0]]*3,'k':21}}}))
    failed=subprocess.run([sys.executable,str(tool),str(binary),str(old),str(new),str(tmp_path/'bad')],capture_output=True)
    assert failed.returncode and not (tmp_path/'bad').exists()
    new.write_text(json.dumps({'sites':{'a':{'t':[['d',0,0]]*3,'k':21},'unavailable':{'t':[['d',0,0]],'k':7}}}))
    fitted=tmp_path/'fitted'
    subprocess.run([sys.executable,str(tool),str(binary),str(old),str(new),str(fitted),'--fit-to-slots'],check=True)
    audit=json.loads((tmp_path/'fitted.retarget.json').read_text())
    assert audit['requested']==4 and audit['emitted']==2
    assert audit['capped_sites']=={'a':{'requested':3,'available':2},'unavailable':{'requested':1,'available':0}}
    assert json.loads((tmp_path/'fitted.applied-plan.json').read_text())['sites']=={'a':{'k':14,'t':[['d',0,0],['d',0,0]]}}
