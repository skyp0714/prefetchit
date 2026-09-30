#!/usr/bin/env python3
"""Advance observed call-path coverage without extra hint slots or stub bytes."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import struct
import dense_build as b
from dense_cause_analysis import Code
from e2e_lbr import remove_generated


def observations(parent, phase, code, sites):
    rows = collections.defaultdict(list); inputs = []
    for path in sorted((parent/'callpath/observations').glob(phase+'_*.json.gz')):
        with gzip.open(path, 'rt') as stream: values = json.load(stream)
        inputs.append(dict(path=str(path), sha256=b.sha(path), samples=len(values)))
        for row in values:
            length = code.get(row['ip'])[0]; assert length
            line = (row['ip']+length)//64 if row['ip']//64 != (row['ip']+length-1)//64 else row['line']
            ages = {site: [age for age in ages if 64 <= age <= 8192]
                    for site, ages in row['ages'] if site in sites}
            rows[line].append({site: max(ages) for site, ages in ages.items() if ages})
    assert len(inputs) == 3
    return rows, inputs


def masks(rows):
    cover = {}; early = {}
    for line, values in rows.items():
        c = collections.defaultdict(int); e = collections.defaultdict(int)
        for index, observed in enumerate(values):
            bit = 1 << index
            for site, age in observed.items():
                c[site] |= bit
                if age >= 512: e[site] |= bit
        cover[line] = dict(c); early[line] = dict(e)
    return cover, early


def union(table, line, sites):
    value = 0
    for site in sites: value |= table.get(line, {}).get(site, 0)
    return value


def stats(rows, assignments):
    cover, early = masks(rows)
    return dict(samples=sum(map(len, rows.values())),
        covered=sum(union(cover, line, sites).bit_count() for line, sites in assignments.items()),
        early_covered=sum(union(early, line, sites).bit_count() for line, sites in assignments.items()))


def prepare(parent, root):
    root.mkdir(parents=True, exist_ok=False); b.space(root)
    base = json.loads((parent/'split_coverage/prepared/prepared.json').read_text())
    binary = Path(base['binary']); audit = json.loads(Path(str(binary)+'.json').read_text())
    assert b.sha(binary) == audit['sha256']
    slots = {(row['site'], j): target for row in audit['plan']['calls'] for j, target in enumerate(row['targets'])}
    assignments = collections.defaultdict(set)
    for (site, _), target in slots.items(): assignments[target//64].add(site)
    original = {line: set(sites) for line, sites in assignments.items()}
    protocol = dict(source_sha256=b.sha(__file__), base=str(binary), base_sha256=audit['sha256'],
        rule='Training only. Swap two existing target slots at different calls; preserve target multiset, slot counts per call and every previously covered training sample. Neither target may lose any >=512-cycle covered training sample. Accept >=8 newly early-covered samples per swap; deterministic greatest-gain order, at most 512 swaps. Heldout is evaluated only after freezing. Only rel32 hint displacements may change.',
        limitation='LBR accumulated retirement cycles are a proxy, not issue-to-fetch lead. Changing target-to-path assignment can also change prediction quality. Global target multiset and instruction count are fixed; per-target dynamic frequency need not be fixed.')
    b.save(root/'protocol.json', protocol)
    code = Code(Path(base['reference']))
    train, train_inputs = observations(parent, 'train', code, {site for site, _ in slots})
    cover, early = masks(train); swaps = []
    bysite = collections.defaultdict(list)
    for slot in slots: bysite[slot[0]].append(slot)
    for iteration in range(512):
        best = None
        for a, ta in sorted(slots.items()):
            sa = a[0]; la = ta//64
            ca = union(cover, la, assignments[la]); ea = union(early, la, assignments[la])
            for sb in sorted(early.get(la, {})):
                if sb in assignments[la]: continue
                new_a = assignments[la]-{sa}|{sb}
                na = union(cover, la, new_a); ne = union(early, la, new_a)
                if ca & ~na or ea & ~ne: continue
                gain_a = (ne & ~ea).bit_count()
                if not gain_a: continue
                for z in bysite[sb]:
                    tb = slots[z]; lb = tb//64
                    if la == lb or sa in assignments[lb] or sa not in cover.get(lb, {}): continue
                    cb = union(cover, lb, assignments[lb]); eb = union(early, lb, assignments[lb])
                    nb = union(cover, lb, assignments[lb]-{sb}|{sa})
                    en = union(early, lb, assignments[lb]-{sb}|{sa})
                    if cb & ~nb or eb & ~en: continue
                    gain = gain_a+(en & ~eb).bit_count()
                    if gain < 8: continue
                    key = (-gain, min(a, z), max(a, z))
                    if best is None or key < best[0]: best = (key, a, z, ta, tb)
        if best is None: break
        key, a, z, ta, tb = best
        assignments[ta//64].remove(a[0]); assignments[ta//64].add(z[0])
        assignments[tb//64].remove(z[0]); assignments[tb//64].add(a[0])
        slots[a], slots[z] = tb, ta
        swaps.append(dict(a=a, z=z, target_a=ta, target_z=tb, newly_early_covered=-key[0]))
    selection = dict(swaps=swaps, train_before=stats(train, original), train_after=stats(train, assignments), inputs=train_inputs)
    b.save(root/'selection_frozen.json', selection)
    heldout, heldout_inputs = observations(parent, 'heldout', code, {site for site, _ in slots})
    selection.update(heldout_before=stats(heldout, original), heldout_after=stats(heldout, assignments), heldout_inputs=heldout_inputs)
    b.save(root/'selection.json', selection); del train, heldout, code
    if not swaps:
        b.save(root/'complete.json', dict(compiled=False, reason='No train-only coverage-preserving target-slot swap meets the prespecified early-coverage gain. No generated ELF.'))
        print(json.dumps(selection)); return
    data = bytearray(binary.read_bytes()); hints = {h['va']: dict(h) for h in audit['hints']}; changes = []
    calls = []; patches = []; seen = set()
    for old in audit['patches']:
        row = dict(old); row['targets'] = [slots[old['site'], j] for j in range(len(old['targets']))]
        for j, target in enumerate(row['targets']):
            va = old['stub']+7*j; assert va not in seen; seen.add(va)
            hint = hints[va]; offset = hint['offset']; before = bytes(data[offset:offset+7])
            assert before.hex() == hint['original'] and before[:3] == bytes.fromhex('0f1815')
            after = before[:3]+struct.pack('<i', target-va-7)
            data[offset:offset+7] = after
            if before != after: changes.append(dict(offset=offset, before=before.hex(), after=after.hex()))
            hints[va] = dict(hint, target=target, original=after.hex())
        patches.append(row)
        calls.append({key: row[key] for key in audit['plan']['calls'][len(calls)]})
    assert len(seen) == len(hints) == len(slots)
    restored = bytearray(data)
    for change in changes: restored[change['offset']:change['offset']+7] = bytes.fromhex(change['before'])
    assert restored == binary.read_bytes()
    import hashlib
    nop = bytearray(data)
    for hint in hints.values(): nop[hint['offset']:hint['offset']+7] = bytes.fromhex(hint['nop'])
    assert hashlib.sha256(nop).hexdigest() == audit['nop_sha256']
    assert collections.Counter(slots.values()) == collections.Counter(t for r in audit['plan']['calls'] for t in r['targets'])
    output = root/'mongod'; b.space(root); output.write_bytes(data); output.chmod(0o755)
    record = dict(audit, sha256=b.sha(output), plan=dict(audit['plan'], calls=calls), patches=patches, hints=list(hints.values()),
        lead_swap=dict(base=str(binary), base_sha256=audit['sha256'], changes=changes, identical_nop_sha256=audit['nop_sha256']))
    b.save(Path(str(output)+'.json'), record)
    try:
        verified = Code(output)
        assert all(verified.raw_targets[h['va']] == h['target'] for h in hints.values())
    except BaseException as error:
        b.save(root/'failure.json', dict(error=repr(error)))
        remove_generated([output], root/'cleanup.json', 'Decode rejected; retain source, selection, hashes and patch records.'); raise
    b.save(root/'complete.json', dict(compiled=True, binary=str(output), sha256=record['sha256'],
        swapped_pairs=len(swaps), changed_hint_slots=len(changes), extra_instructions=0, identical_nop=True))
    print(json.dumps(selection))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('parent', type=Path); parser.add_argument('root', type=Path)
    args = parser.parse_args(); prepare(args.parent, args.root)
