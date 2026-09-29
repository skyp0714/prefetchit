#!/usr/bin/env python3
"""Test IT0/IT1 at the improved T1 targets without changing hint placement."""
import argparse
from pathlib import Path
import dense_build as b
from dense_cause_analysis import Code
from e2e_lbr import remove_generated
from lean_plan import read_image

def build(source,out):
    source=Path(source);out=Path(out);out.mkdir(parents=True,exist_ok=False);b.space(out)
    original=source.read_bytes();source_hash=b.sha(source);code=Code(source);image=read_image(source)
    direct=[r for r in image['records'] if r['active'] and r['direct']]
    assert direct and len({r['site'] for r in direct})==len(direct)
    sites=[]
    for r in direct:
        site,target=r['site'],r['target']
        assert code.instructions[site][0]==7 and code.raw_targets[site]==target and target in code.instructions
        sections=[s for s in code.sections if s[0]<=site and site+7<=s[0]+s[2]];assert len(sections)==1
        va,offset,_=sections[0];offset+=site-va
        assert original[offset:offset+3]==b'\x0f\x18\x15'
        sites.append(offset+2)
    result={}
    for kind,modrm in [('it0',0x3d),('it1',0x35)]:
        b.space(out);dest=out/kind/source.name;dest.parent.mkdir();data=bytearray(original)
        for offset in sites:data[offset]=modrm
        reverse=bytearray(data)
        for offset in sites:reverse[offset]=0x15
        assert bytes(reverse)==original and sum(a!=z for a,z in zip(data,original))==len(sites)
        dest.write_bytes(data);dest.chmod(source.stat().st_mode)
        record=dict(source=str(source),source_sha256=source_hash,path=str(dest),sha256=b.sha(dest),
            source_script_sha256=b.sha(__file__),kind=kind,byte_offsets=sites,before_byte='15',after_byte=f'{modrm:02x}',
            bytes=len(data),direct_sites=len(sites),target_displacements_unchanged=True,metadata_unchanged=True,
            register_t1_sites_unchanged=True,same_layout=True,fully_reversible=True)
        try:
            verified=Code(dest)
            assert set(verified.instructions)==set(code.instructions)
            assert verified.raw_targets==code.raw_targets
            assert read_image(dest)['records']==image['records']
            assert all(verified.get(r['site'])[1].startswith('prefetch'+kind) for r in direct)
        except BaseException as error:
            b.save(dest.with_suffix('.failure.json'),dict(record,error=repr(error)))
            remove_generated([dest],dest.with_suffix('.cleanup.json'),'Opcode validation rejected; patch/source/hash records retained.')
            raise
        b.save(dest.with_suffix('.opcode.json'),record);result[kind]=record
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    b.save(a.out/'variants.json',build(a.source,a.out))
