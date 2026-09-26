from pathlib import Path
import subprocess
import sys


def test_hint_retune_preserves_native_hints_and_layout(tmp_path):
    source=tmp_path/'a.c'
    source.write_text('int main(void) { __asm__ volatile("prefetcht0 (%rax); prefetcht1 64(%rax); prefetcht2 (%rax)"); return 0; }')
    binary=tmp_path/'a'
    subprocess.run(['clang-19',str(source),'-o',str(binary)],check=True)
    tool=Path(__file__).resolve().parents[1]/'tools/retune_prefetch_hint.py'
    for hint in ['t0','t2','nta']:
        result=tmp_path/hint
        subprocess.run([sys.executable,str(tool),str(binary),str(result),'--hint',hint],check=True)
        before,after=binary.read_bytes(),result.read_bytes()
        assert len(before)==len(after)
        assert sum(a!=b for a,b in zip(before,after))==1
        dis=subprocess.check_output(['objdump','-d',str(result)],text=True)
        assert 'prefetcht1' not in dis
        assert 'prefetcht0' in dis and 'prefetcht2' in dis
