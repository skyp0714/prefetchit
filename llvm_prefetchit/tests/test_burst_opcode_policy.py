"""Mixed bursts preserve native behavior and the exact existing NOP twin."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
import burst_opcode_policy as policy
from call_stub_prefetch import Elf,NOP7,sha


def test_mixed_burst_native_and_byte_scope(tmp_path,monkeypatch):
    monkeypatch.setattr(policy.b,'space',lambda path:None)
    c=tmp_path/'main.c';asm=tmp_path/'hints.S';binary=tmp_path/'original'
    c.write_text('extern int first(int),second(int); __attribute__((noinline)) int target(int x){return x+19;} int main(){__asm__ volatile("prefetcht1 target(%%rip)":::"memory");return first(23)!=42 || second(23)!=42;}\n')
    lines=['.text'];labels=[]
    for name in ['first','second']:
        lines += [f'.global {name}',name+':']
        for index,kind in enumerate(['it0','it0','it0','t1']):
            label=f'{name}_{index}';labels.append((label,kind))
            lines += [f'.global {label}',label+':',f'prefetch{kind} target(%rip)']
        lines += ['jmp target']
    lines += ['.section .note.GNU-stack,"",@progbits'];asm.write_text('\n'.join(lines)+'\n')
    subprocess.run(['gcc','-O2','-fno-pie','-no-pie','-Wl,--build-id=none',str(c),str(asm),'-o',str(binary)],check=True)
    symbols={parts[2]:int(parts[0],16) for line in subprocess.check_output(['nm',str(binary)],text=True).splitlines() if len(parts:=line.split())==3}
    raw=binary.read_bytes();elf=Elf(raw);nop=bytearray(raw);hints=[]
    for label,kind in labels:
        va=symbols[label];offset=elf.offset(va,7,True)
        hints.append(dict(va=va,offset=offset,target=symbols['target'],original=raw[offset:offset+7].hex(),kind=kind))
        nop[offset:offset+7]=NOP7
    Path(str(binary)+'.json').write_text(json.dumps(dict(sha256=sha(raw),nop_sha256=sha(nop),hints=hints,
        hybrid=dict(site_groups=[dict(index=0,gated=True),dict(index=1,gated=True)]))))
    dest=tmp_path/'mixed';result=policy.build(binary,dest)
    for path in [binary,dest]:subprocess.run([str(path)],check=True)
    assert result['mixed_burst']['bursts']==2 and len(result['mixed_burst']['changes'])==4
    assert [h['kind'] for h in result['hints']]==['it0','t1','t1','t1']*2
    expected={hints[i]['offset']+2 for i in [1,2,5,6]}
    assert {i for i,(old,new) in enumerate(zip(raw,dest.read_bytes())) if old!=new}==expected
    assert sha(nop)==result['nop_sha256']
    binary.write_bytes(raw+b'changed')
    with pytest.raises(AssertionError,match='fingerprint'):policy.build(binary,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()
