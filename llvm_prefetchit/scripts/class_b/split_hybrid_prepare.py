#!/usr/bin/env python3
"""Add independently selected switch-age gates to the completed split75 plan."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import dense_build as b
from dense_cause_analysis import Code
from e2e_lbr import remove_generated
from hybrid_prepare import opcode_control, sparse, stubs


def full(parent, root):
    root.mkdir(parents=True, exist_ok=False); b.space(root)
    source = parent/'split_coverage/prepared/prepared.json'
    base = json.loads(source.read_text())
    assert (parent/'split_coverage/complete.json').exists()
    assert b.sha(base['binary']) == base['sha256']
    audit = json.loads(Path(base['binary']+'.json').read_text())
    code = Code(base['reference'])
    sites = {c['site'] for c in audit['plan']['calls']}
    scores = collections.defaultdict(collections.Counter); anchors = {}
    inputs = sorted((parent/'callpath/observations').glob('train_*.json.gz'))
    assert len(inputs) == 3
    for path in inputs:
        with gzip.open(path, 'rt') as stream: rows = json.load(stream)
        for row in rows:
            length, _, _ = code.get(row['ip']); assert length
            target = row['target']
            if row['ip']//64 != (row['ip']+length-1)//64:
                target = row['ip']+length
                assert target in code.instructions
            line = target//64; anchors.setdefault(line, target)
            for site in set(row['sites']) & sites: scores[site][line] += 1
    plan = dict(audit['plan'], calls=[])
    for old in audit['plan']['calls']:
        targets = list(old['targets']); lines = {v//64 for v in targets}
        for line, count in sorted(scores[old['site']].items(), key=lambda v: (-v[1], v[0])):
            if len(targets) >= 8: break
            if line not in lines: targets.append(anchors[line]); lines.add(line)
        plan['calls'].append(dict(old, burst_targets=targets))
    del code
    b.save(root/'plan.json', plan)
    b.save(root/'protocol.json', dict(base_record=str(source), base_record_sha256=b.sha(source),
        base=base, inputs={str(p): b.sha(p) for p in inputs}, source_sha256=b.sha(__file__),
        builder_sha256=b.sha(stubs.__file__), burst_cap=8,
        rule='Preserve all 849 split75 calls and ordinary T1 targets. Extend first-epoch burst targets using training observations only. Full diagnostic selects gates; an independent sparse diagnostic validates them. No E2E-driven gate selection.'))
    output = root/'full_diagnostic/mongod'
    try:
        record = stubs.build(base['reference'], plan, output, hybrid=dict(diagnostic=True))
        prepared = dict(reference=base['reference'], hybrid=str(output), diagnostic=str(output), base=base)
        b.save(root/'prepared.json', prepared)
        remove_generated([Path(str(output)+'.nop')], root/'full_diagnostic_nop_cleanup.json',
            'Unused diagnostic NOP; retain its source, plan, native patch record and hashes.')
        return prepared
    except BaseException as error:
        b.save(root/'failure.json', dict(error=repr(error)))
        remove_generated([p for p in [output, Path(str(output)+'.nop')] if p.exists()],
            root/'failed_cleanup.json', 'Rejected full diagnostic build; preserve compact records.')
        raise


def reduced(prepared, diagnostic, root):
    result = sparse(prepared, diagnostic, root)
    binary = Path(result['sparse']['binary'])
    t1 = opcode_control(binary, root/'builds/early_t1/mongod', early='t1')
    t1_record = json.loads(Path(t1+'.json').read_text())
    result['early_t1'] = dict(binary=t1, sha256=t1_record['sha256'],
        nop_sha256=t1_record['nop_sha256'])
    assert result['early_t1']['nop_sha256'] == result['sparse']['nop_sha256']
    b.save(root/'prepared.json', result)
    remove_generated([Path(prepared['diagnostic'])], root/'full_diagnostic_cleanup.json',
        'Full diagnostic gate counts extracted and frozen; sparse independent verification follows. Preserve full plan and patch record.')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('parent', type=Path); parser.add_argument('out', type=Path)
    args = parser.parse_args(); full(args.parent, args.out)
