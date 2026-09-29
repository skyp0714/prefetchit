"""Backend binding must preserve page-sharing topology and exact NOP spans."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
import backend_prefetch as m

def test_all_mongodb_bindings_restore_the_adapter(tmp_path):
    binary=tmp_path/'binary';binary.write_bytes(b'test')
    original=m.h.media.save
    config={'services':{name:{'image':'mongo:test','volumes':['/input:/input:ro']} for name in [*m.BACKENDS,'other-mongodb']}}
    config['services']['native-service']={'image':'native:test'}
    with m.bind_mongodb(tmp_path,binary):
        m.h.media.save(tmp_path/'compose.json',config)
    assert m.h.media.save is original
    stored=json.loads((tmp_path/'compose.json').read_text())
    for name in [*m.BACKENDS,'other-mongodb']:
        assert stored['services'][name]['volumes']==['/input:/input:ro',str(binary)+':/usr/bin/mongod:ro']
    assert stored['services']['native-service']=={'image':'native:test'}
    with pytest.raises(RuntimeError):
        with m.bind_mongodb(tmp_path,binary):raise RuntimeError('Injected startup error')
    assert m.h.media.save is original

def test_native_padding_patch_keeps_boundaries_and_behavior(tmp_path):
    c=tmp_path/'probe.c';c.write_text(r'''
__attribute__((noinline)) int leaf(int x){volatile int y=x;return y+7;}
int main(void){__asm__ volatile(".globl hint_site\nhint_site:\n.byte 0x66,0x0f,0x1f,0x80,0,0,0,0":::"memory");return leaf(3)!=10;}
''')
    source=tmp_path/'base';subprocess.run(['gcc','-O2','-fno-pie','-no-pie',str(c),'-o',str(source)],check=True)
    syms={p[2]:int(p[0],16) for line in subprocess.check_output(['nm','-n',str(source)],text=True).splitlines() if len(p:=line.split())==3}
    code=m.Code(source);site=syms['hint_site'];length=code.instructions[site][0]
    section=next(s for s in code.sections if s[0]<=site<s[0]+s[2]);off=section[1]+site-section[0]
    assert length==8 and m.is_padding_nop(source.read_bytes()[off:off+length])
    dest=tmp_path/'prefetch';m.padding_variant(source,dest,code,{site:(off,length)},[dict(site=site,target=syms['leaf'])])
    for path in [source,dest]:subprocess.run([str(path)],check=True)
    record=json.loads(dest.with_suffix('.patches.json').read_text())
    assert record['instruction_boundaries_unchanged'] and record['fully_reversible']
    a=source.read_bytes();z=dest.read_bytes();assert len(a)==len(z)
    assert all(off<=i<off+length for i,(x,y) in enumerate(zip(a,z)) if x!=y)
