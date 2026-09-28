#!/usr/bin/env python3
"""Miss-weighted thinning of audited dominator hints, at identical ELF layout.

The retained profile ranks targets, not dynamic call-edge frequencies. Metadata
in a thinned ELF describes the original placements; its active flags are stale.
The separate patch manifest is authoritative for enabled instructions.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

import dense_build as b
import lean_plan
from lean_profile import symbol_ranges


def choose_keys(records, address_weights, budget):
    if budget <= 0:
        raise ValueError('Positive per-caller target budget required')
    callers = defaultdict(dict)
    for row in records:
        if not row['active'] or not row['direct']:
            raise ValueError('Expected active direct-only metadata')
        caller = (row['module'], row['function'])
        score = address_weights.get(row['target'], 0)
        if score <= 0:
            raise ValueError('Unranked target')
        callers[caller][row['key']] = max(score, callers[caller].get(row['key'], 0))
    selected = set()
    for weights in callers.values():
        # Keep all physical copies of a selected logical hint. Ties use the
        # stable compiler key; host allocation addresses never enter ranking.
        selected.update(sorted(weights, key=lambda key: (-weights[key], key))[:budget])
    return selected


def thin(source, dest, weights_file, budget):
    b.space(dest.parent)
    if dest.exists() or source.is_symlink():
        raise ValueError('Expected original local ELF and a fresh destination')
    image = lean_plan.read_image(source)
    profile = json.loads(weights_file.read_text())['weights']
    ranges, command = symbol_ranges(source)
    weights = {row['start']: max((profile.get(n, 0) for n in row['names']), default=0)
               for row in ranges}
    keep = choose_keys(image['records'], weights, budget)
    sys.path.insert(0, str(b.REPO/'llvm_prefetchit/tools'))
    from make_nop_control_binary import MULTI_NOP
    original = source.read_bytes()
    patched = bytearray(original)
    sections = lean_plan.sections(original)
    changes = []
    for row in image['records']:
        site = row['site']
        section, = [s for s in sections if s['flags'] & 4 and
                    s['va'] <= site and site + 7 <= s['va'] + s['size']]
        offset = section['offset'] + site - section['va']
        raw = original[offset:offset+7]
        if raw[:3] != b'\x0f\x18\x3d':
            raise ValueError('Expected direct RIP-relative IT0 at an audited site')
        if row['key'] in keep:
            continue
        patched[offset:offset+7] = MULTI_NOP[7]
        changes.append(dict(key=row['key'], site=site, target=row['target'],
                            offset=offset, original=raw.hex(), nop=MULTI_NOP[7].hex()))
    restored = bytearray(patched)
    for row in changes:
        restored[row['offset']:row['offset']+7] = bytes.fromhex(row['original'])
    assert restored == original and len(patched) == len(original)
    dest.write_bytes(patched)
    dest.chmod(source.stat().st_mode)
    with gzip.open(dest.with_suffix('.thinning.json.gz'), 'wt') as f:
        json.dump(dict(keep=sorted(keep), changes=changes), f, separators=(',', ':'))
    result = dict(source=str(source), source_sha256=b.sha(source), path=str(dest),
                  sha256=b.sha(dest), profile_sha256=b.sha(weights_file),
                  per_caller_budget=budget, original_hints=len(image['records']),
                  removed_hints=len(changes), retained_hints=len(image['records'])-len(changes),
                  executable_bytes=image['executable_bytes'], exact_layout=True,
                  symbol_command=command,
                  metadata_active_flags_stale=True,
                  limitation='Target-weight ranking, not edge-frequency or successful-fill measurement. NOP replacement preserves size.')
    b.save(dest.with_suffix('.thinning_audit.json'), result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('dest', type=Path)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--budget', type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(thin(args.source, args.dest, args.profile, args.budget), indent=2))
