#!/usr/bin/env python3
"""Audit linked dominator hints and remove redundant injections conservatively.

The compiler emits non-allocated records for active AND removed targets. Each
rebuild can therefore verify coverage using its own final layout, then restore
any target which moved to an otherwise uncovered cache line.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct


SECTION = '.debug_prefetchit_v2'
RECORD = struct.Struct('<QQQQQIHH')
PLACEMENT = '24,600,8,0,1,1,1,1,2,64,1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sections(data):
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64')
    kind, machine = struct.unpack_from('<HH', data, 16)
    if kind not in (2, 3) or machine != 62:
        raise ValueError('Expected linked x86-64 ELF, not a relocatable object')
    shoff = struct.unpack_from('<Q', data, 40)[0]
    size, count, strings = struct.unpack_from('<HHH', data, 58)
    if size != 64 or not count or strings >= count:
        raise ValueError('Unsupported section header table')
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * size)
               for i in range(count)]
    names = data[headers[strings][4]:headers[strings][4]+headers[strings][5]]
    result = []
    for h in headers:
        end = names.index(0, h[0])
        result.append(dict(name=names[h[0]:end].decode(), type=h[1], flags=h[2],
                           va=h[3], offset=h[4], size=h[5]))
    return result


def hint_key(module, function, group, argument):
    return f'{module:X}:{function:X}:{group}:{argument}'


def read_image(path):
    path = Path(path)
    data = path.read_bytes()
    table = sections(data)
    metadata = [s for s in table if s['name'] == SECTION]
    if not metadata:
        raise ValueError(f'No dominator metadata in {path}')
    executable = [s for s in table if s['flags'] & 4 and s['type'] == 1]

    def bytes_at(va, length):
        candidates = [s for s in executable if s['va'] <= va and
                      va+length <= s['va']+s['size']]
        if len(candidates) != 1:
            raise ValueError(f'Non-executable or ambiguous target/site {va:x}')
        off = candidates[0]['offset'] + va-candidates[0]['va']
        return data[off:off+length]

    rows = []
    seen = set()
    for section in metadata:
        if section['flags'] & 2 or section['size'] % RECORD.size:
            raise ValueError('Metadata must be non-allocated 48-byte records')
        raw = data[section['offset']:section['offset']+section['size']]
        for site, target, module, function, instance, group, argument, flags in RECORD.iter_unpack(raw):
            if flags & ~3:
                raise ValueError('Unknown record flags')
            active, direct = bool(flags & 1), bool(flags & 2)
            key = hint_key(module, function, group, argument)
            physical = (key, instance)
            if physical in seen:
                raise ValueError(f'Duplicate physical key {physical}; COMDAT audit failed')
            seen.add(physical)
            if active:
                opcode = bytes_at(site, 3)
                if direct:
                    instruction = bytes_at(site, 7)
                    if opcode not in (b'\x0f\x18\x15', b'\x0f\x18\x3d', b'\x0f\x18\x35'):
                        raise ValueError(f'Expected direct T1/IT0/IT1 at {site:x}')
                    actual = site+7+struct.unpack_from('<i', instruction, 3)[0]
                    if actual != target:
                        raise ValueError(f'Target relocation mismatch {key}')
                else:
                    # Register forms may begin with one REX prefix.
                    body = bytes_at(site, 4)
                    if 0x40 <= body[0] <= 0x4f:
                        body = body[1:]
                    if body[:2] != b'\x0f\x18' or (body[2] >> 3) & 7 != 2:
                        raise ValueError(f'Expected register T1 at {site:x}')
            elif site:
                raise ValueError('Removed hint has a nonzero site')
            if direct:
                bytes_at(target, 1)
            elif target or not active:
                raise ValueError('Indirect targets must remain active and have target=0')
            rows.append(dict(key=key, module=f'{module:X}', function=f'{function:X}',
                             group=group, instance=instance, argument=argument, active=active, direct=direct,
                             site=site, target=target))
    return dict(path=str(path.resolve()), sha256=sha(path), records=rows,
                executable_bytes=sum(s['size'] for s in executable),
                metadata_bytes=sum(s['size'] for s in metadata), metadata_allocated=False)


def groups(image):
    result = defaultdict(list)
    for row in image['records']:
        result[(row['module'], row['function'], row['group'], row.get('instance',0))].append(row)
    return [sorted(rows, key=lambda r: r['argument']) for rows in result.values()]


def plan(images, placement=PLACEMENT):
    # A dependency key may occur in several service ELFs at different layouts.
    # It is safe to propose removal only when redundant in EVERY occurrence.
    redundant = defaultdict(list)
    for image in images:
        for batch in groups(image):
            lines = set()
            for row in batch:
                if not row['active']:
                    raise ValueError('Initial planning requires an undropped build')
                line = row['target'] // 64
                redundant[row['key']].append(row['direct'] and line in lines)
                if row['direct']:
                    lines.add(line)
    return dict(schema='prefetchit.dom_drop.v1', placement=placement,
                drop=sorted(k for k, values in redundant.items() if all(values)),
                inputs=[{k: im[k] for k in ('path', 'sha256', 'executable_bytes', 'metadata_bytes')}
                        for im in images],
                rule='Drop a direct hint only if an earlier group target shares its 64B line in every image; re-audit after relinking')


def refine(current, images):
    """Restore uncovered targets; this operation never introduces new drops."""
    dropped = set(current['drop'])
    seen, restore = set(), set()
    missing = []
    for image in images:
        for batch in groups(image):
            covered = {r['target']//64 for r in batch if r['active'] and r['direct']}
            for row in batch:
                seen.add(row['key'])
                if row['active'] == (row['key'] in dropped):
                    raise ValueError(f'Image/plan active-state mismatch: {row["key"]}')
                if row['direct'] and row['target']//64 not in covered:
                    restore.add(row['key'])
                    missing.append(dict(path=image['path'], key=row['key'], target=row['target']))
    unknown = dropped-seen
    if unknown:
        raise ValueError(f'{len(unknown)} drop keys missing from final images')
    result = dict(current, drop=sorted(dropped-restore))
    audit = dict(coverage_verified=not missing, restored=sorted(restore), missing=missing,
                 retained_drop_count=len(result['drop']),
                 inputs=[{k: im[k] for k in ('path', 'sha256', 'executable_bytes', 'metadata_bytes')}
                         for im in images],
                 counts=[dict(path=im['path'], active=sum(r['active'] for r in im['records']),
                              removed=sum(not r['active'] for r in im['records'])) for im in images])
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'refine', 'audit'])
    parser.add_argument('binaries', nargs='+', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--placement', default=PLACEMENT)
    args = parser.parse_args()
    images = [read_image(p) for p in args.binaries]
    if args.mode == 'plan':
        result = plan(images, args.placement)
    else:
        if not args.plan:
            parser.error('--plan is required for refine/audit')
        result, audit = refine(json.loads(args.plan.read_text()), images)
        args.output.with_suffix('.audit.json').write_text(json.dumps(audit, indent=2)+'\n')
        if args.mode == 'audit':
            result = audit
    args.output.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
