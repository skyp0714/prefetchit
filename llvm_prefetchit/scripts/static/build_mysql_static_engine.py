#!/usr/bin/env python3
"""Pinned InnoDB prediction at existing reachable SQL UPDATE NOPs.

Closed-workload target choice, not proof that all handler objects are InnoDB.
No runtime virtual-address lookup, appended hook, or extra instruction slot.
"""
import argparse,hashlib,json,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from make_nop_control_binary import executable_sections
from append_dispatch_hooks import instructions

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('out',type=Path);p.add_argument('--mode',choices=['entry','body','staged'],required=True);a=p.parse_args()
 original=a.binary.read_bytes();sha=hashlib.sha256(original).hexdigest()
 assert sha=='b7fbad1d47baa9ed9ecaf4574d87a1f3c38ec279867502a3e5c9f9edf4ec3399'
 target=0xc9a3b0;assert instructions(a.binary,target,target+4)[0][1]==bytes.fromhex('f30f1efa')
 # d79e89 follows a store (fallthrough); d7a1e1 follows conditional JE.
 # Adjacent unreachable NOPs after JMP/RET in other candidate functions were
 # explicitly excluded. Audited handler call is d7a2e7 -> c9a120.
 assert instructions(a.binary,0xd79e82,0xd79e90)[-1][0]==0xd79e89
 assert instructions(a.binary,0xd7a1db,0xd7a1e8)[0][2].startswith('je')
 call=instructions(a.binary,0xd7a2e7,0xd7a2ec);assert len(call)==1 and 'c9a120' in call[0][2]
 targets=[(0xd79e89,target+(128 if a.mode=='body' else 0))]
 if a.mode=='staged':targets.append((0xd7a1e1,target+128))
 sections=executable_sections(str(a.binary));data=bytearray(original);patches=[]
 for site,dest in targets:
  matches=[off+site-va for va,off,size in sections if va<=site and site+7<=va+size];assert len(matches)==1;off=matches[0]
  before=bytes.fromhex('0f1f8000000000');assert original[off:off+7]==before
  after=bytes.fromhex('0f1815')+struct.pack('<i',dest-site-7);data[off:off+7]=after
  patches.append({'site':site,'offset':off,'target':dest,'before':before.hex(),'after':after.hex(),'linear_bytes_to_handler_call':0xd7a2e7-site-7})
 reversed_data=bytearray(data)
 for x in patches:reversed_data[x['offset']:x['offset']+7]=bytes.fromhex(x['before'])
 assert reversed_data==original and not a.out.exists()
 a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_bytes(data);a.out.chmod(0o755)
 meta={'source_sha256':sha,'sha256':hashlib.sha256(data).hexdigest(),'mode':a.mode,'patches':patches,'nop_control':str(a.binary),'reversal_verified':True,
       'scope':'Sql_cmd_update::update_single_table -> handler::ha_update_row -> predicted ha_innobase::update_row, 16-table normal InnoDB OLTP workload',
       'lead_caveat':'Physical instruction bytes, not measured execution cycles; conditional paths may bypass hint or target'}
 a.out.with_suffix('.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta))
if __name__=='__main__':main()
