#!/usr/bin/env python3
"""Same reply targets/layout: first two hints at each site use PREFETCHIT0."""
import argparse
import copy
from pathlib import Path
import time

import dense_build as b
from rpc_route_study import load


def prepare(root):
    assert (root/'reply_it0_predeclared.json').exists()
    prepared=load(root/'prepared_candidates.json');arms=load(root/'arms.json');base=prepared['reply']
    arm=copy.deepcopy(arms['reply']);nop=copy.deepcopy(arms['reply_nop']);builds={}
    for service,entry in base['builds'].items():
        b.space(root);source=Path(entry['binary']);record=load(Path(str(source)+'.json'));data=bytearray(source.read_bytes())
        wanted={p['stub']+7*rank for p in record['patches'] for rank in range(min(2,len(p['targets'])))}
        changes=[]
        for hint in record['hints']:
            if hint['va'] not in wanted:continue
            offset=hint['offset'];old=bytes.fromhex(hint['original'])
            assert old[:3]==bytes.fromhex('0f1815') and data[offset:offset+7]==old
            new=bytes.fromhex('0f183d')+old[3:];data[offset:offset+7]=new
            changes.append(dict(offset=offset,old=old.hex(),new=new.hex(),va=hint['va'],target=hint['target']))
            hint.update(original=new.hex(),kind='it0')
        assert len(changes)==len(wanted)
        original=source.read_bytes();actual={i for i,(a,c) in enumerate(zip(original,data)) if a!=c}
        assert actual=={v['offset']+2 for v in changes}
        output=root/'builds'/'reply_it0'/service/source.name;output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(data);output.chmod(0o755)
        record.update(sha256=b.sha(output),variant='reply_it0',opcode_changes=changes,
            opcode_source=str(source),opcode_source_sha256=b.sha(source),nop_path=entry['nop'])
        b.save(Path(str(output)+'.json'),record);arm['overrides'][service]=str(output)
        builds[service]=dict(entry,binary=str(output),sha256=b.sha(output),it0_hints=len(changes))
    arms.update(reply_it0=arm,reply_it0_nop=nop);b.save(root/'arms.json',arms)
    prepared['reply_it0']=dict(arm=arm,nop=nop,builds=builds);b.save(root/'prepared_candidates.json',prepared)
    b.save(root/'reply_it0_prepared.json',dict(valid=True,builds=builds,epoch=time.time(),source_sha256=b.sha(__file__),
        note='Only ModRM of up to two new reply hints/site changes; all addresses and other bytes match reply T1. Remaining reply hints and incoming-RPC hints remain T1. NOP twin is shared with reply T1 and disables only added reply hints.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);prepare(parser.parse_args().root)
