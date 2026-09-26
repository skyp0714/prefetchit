"""Binary experiments must preserve layout and upstream data prefetches."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1]/'tools'


def compile_example(tmp_path,body):
    cc = shutil.which('cc')
    if not cc: pytest.skip('C compiler required')
    source = tmp_path/'example.c'; source.write_text(body)
    binary = tmp_path/'base'
    subprocess.run([cc,'-O2',str(source),'-o',str(binary)],check=True)
    return binary


def test_retuning_changes_only_selected_hint_and_displacement(tmp_path):
    binary = compile_example(tmp_path,'''int main(void) {
      __asm__ volatile("prefetcht1 256(%%rip)\\n\\tprefetcht0 64(%%rip)" ::: "memory");
      return 0;
    }''')
    output, index = tmp_path/'tuned', tmp_path/'index.json'
    subprocess.run([sys.executable,str(TOOLS/'retune_rip_prefetch.py'),str(binary),str(output),
        '--source-distance','256','--distance','512','--hint','t0','--index',str(index)],check=True)
    original, tuned = binary.read_bytes(), output.read_bytes()
    assert len(original) == len(tuned)
    offsets = json.loads(index.read_text())['offsets']; assert len(offsets) == 1
    assert {i for i,(a,b) in enumerate(zip(original,tuned)) if a!=b} <= set(range(offsets[0]+2,offsets[0]+7))
    subprocess.run([str(output)],check=True)


def test_padding_twin_is_exact_original(tmp_path):
    binary = compile_example(tmp_path,'''__attribute__((noinline)) void padding_fixture(void) {
      __asm__ volatile(".byte 0x0f,0x1f,0x80,0,0,0,0\\n\\t"
                       ".byte 0x0f,0x1f,0x84,0,0,0,0,0\\n\\t"
                       ".rept 64\\n\\tnop\\n\\t.endr");
    }
    int main(void) { padding_fixture(); return 0; }''')
    output, twin = tmp_path/'prefetch', tmp_path/'twin'
    subprocess.run([sys.executable,str(TOOLS/'prefetch_in_padding.py'),str(binary),str(output),
        '--distance','16','--functions','padding_fixture','--index',str(tmp_path/'index.json')],check=True)
    assert output.read_bytes() != binary.read_bytes()
    subprocess.run([sys.executable,str(TOOLS/'make_nop_control_binary.py'),'--input',str(output),
        '--output',str(twin),'--mnemonics','prefetcht1'],check=True)
    assert twin.read_bytes() == binary.read_bytes()
    subprocess.run([str(output)],check=True)
