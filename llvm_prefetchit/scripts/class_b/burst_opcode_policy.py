#!/usr/bin/env python3
"""Keep the first IT0 of each existing burst; change its other slots to T1."""
import ast
import json
from pathlib import Path
import sys
import dense_build as b
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
from call_stub_prefetch import NOP7,sha


def build(source,dest):
    source,dest=Path(source),Path(dest);assert not dest.exists()
    audit=json.loads(Path(str(source)+'.json').read_text());raw=source.read_bytes()
    assert sha(raw)==audit['sha256'],'Source fingerprint mismatch'
    data=bytearray(raw);hints=[];changes=[];previous=None;bursts=0
    for hint in sorted(audit['hints'],key=lambda row:row['va']):
        offset=hint['offset'];before=bytes(data[offset:offset+7]);assert before.hex()==hint['original']
        kind=hint['kind'];after=before
        if kind=='it0':
            assert before[:3]==b'\x0f\x18\x3d'
            if previous is not None and hint['va']==previous+7:
                after=before[:2]+b'\x15'+before[3:];kind='t1'
                changes.append(dict(offset=offset,before=before.hex(),after=after.hex()))
            else:bursts+=1
            previous=hint['va']
        else:previous=None
        data[offset:offset+7]=after;hints.append(dict(hint,original=after.hex(),kind=kind))
    assert bursts==sum(group['gated'] for group in audit['hybrid']['site_groups'])
    assert changes,'No multi-target burst to transform'
    reversed_data=bytearray(data);nop=bytearray(data)
    for change in changes:reversed_data[change['offset']:change['offset']+7]=bytes.fromhex(change['before'])
    for hint in hints:nop[hint['offset']:hint['offset']+7]=NOP7
    assert sha(reversed_data)==audit['sha256'] and sha(nop)==audit['nop_sha256']
    dest.parent.mkdir(parents=True,exist_ok=True);b.space(dest.parent)
    result=dict(audit,sha256=sha(data),hints=hints,mixed_burst=dict(source=str(source),
        source_sha256=audit['sha256'],builder_sha256=b.sha(__file__),changes=changes,bursts=bursts,
        rule='First contiguous IT0 slot per gated stub remains IT0; remaining early slots become T1. Later T1 slots, gates, timing, targets, addresses and bytes outside these ModRM bytes remain unchanged. Same exact NOP twin.'))
    b.save(Path(str(dest)+'.json'),result);dest.write_bytes(data);dest.chmod(0o755)
    assert b.sha(dest)==result['sha256'];return result


def verify_campaign_compatibility(preflight,campaign,certificate):
    """Reuse measured mapping/gates only when their source AST is unchanged."""
    certificate=Path(certificate);record=json.loads(certificate.read_text())
    assert record['preflight_source_hashes']==preflight['source_hashes']
    old=Path(record['original_campaign_source']);campaign=Path(campaign)
    assert b.sha(old)==preflight['source_hashes'][str(campaign)]
    assert b.sha(campaign)==record['current_campaign_sha256']
    def outside_runner(path):
        module=ast.parse(path.read_text())
        module.body=[node for node in module.body if not isinstance(node,ast.FunctionDef) or node.name!='campaign']
        return ast.dump(module,include_attributes=False)
    assert outside_runner(old)==outside_runner(campaign),'Mapping, trial, diagnostic or test code changed'
    assert all(b.sha(path)==digest for path,digest in preflight['source_hashes'].items() if path!=str(campaign))
    assert record['amendment_before_hybrid_timing'] and not Path(record['hybrid_screen']).exists()
    return dict(certificate=str(certificate),sha256=b.sha(certificate),
        rule='Only outer campaign orchestration changed. All prior module/mapping/trial/diagnostic/test functions are AST-identical; all other measured source hashes remain exact. Original preflight record is immutable.')
