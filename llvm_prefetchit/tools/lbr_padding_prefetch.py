#!/usr/bin/env python3
"""Train constant-target prefetches at existing NOPs from retired L2-miss LBRs.

This is a profile-guided placement probe, not a purely static policy or an
achievable-performance upper bound. LBR
cycles are a retirement-time lead proxy, not the time a future fetch starts.
Keep selection traces separate from all timing and confirmation measurements.
"""
import argparse
import bisect
import collections
import hashlib
import json
from pathlib import Path
import re
import struct

from make_nop_control_binary import MULTI_NOP, executable_sections
from index_executable_padding import is_padding_nop

DSO = r'\((?:[^()]|\([^()]*\))*\)'
HEADER = re.compile(r'^\s*(?:(\d+)\s+)?([0-9a-f]+)\s+(' + DSO + ')')
EDGE = re.compile(r'0x([0-9a-f]+) (' + DSO + r')/0x([0-9a-f]+) (' + DSO + r')/[MPX-]/[^/]*/[^/]*/([0-9-]+)/([^/ ]+)/')


def mapping_bias(maps, dso_pattern, sections):
    """Use ELF section VAs as well as file offsets; handles ET_EXEC and PIE."""
    biases = set()
    for line in maps.splitlines():
        fields = line.split(None, 5)
        if len(fields) < 6 or 'x' not in fields[1] or not dso_pattern.search(fields[5]):
            continue
        low, high = (int(x, 16) for x in fields[0].split('-'))
        offset = int(fields[2], 16)
        for va, file_offset, size in sections:
            if file_offset < offset + high - low and offset < file_offset + size:
                biases.add(low + file_offset - offset - va)
    if not biases:
        return None
    if len(biases) != 1:
        raise ValueError('inconsistent executable mapping biases')
    return biases.pop()


def candidate_sites(edges, slots, bias, dso_pattern, minimum, maximum):
    """Find NOPs on observed straight-line portions between taken branches.

    Edges are newest first. Edge i's cycle count belongs to the interval
    between edge i+1 and edge i. The unsampled final partial block contributes
    no estimated cycles, making the proxy explicit rather than inventing them.
    """
    age = 0
    found = set()
    for newer, older in zip(edges, edges[1:]):
        source, source_dso, _, _, cycles = newer
        _, _, start, start_dso, _ = older
        if cycles is None or cycles >= 65535:
            break  # missing/saturated timing cannot support a lead estimate
        if (dso_pattern.search(source_dso) and dso_pattern.search(start_dso)
                and 0 <= source - start <= 65536):
            lo, hi = start - bias, source - bias
            first, last = bisect.bisect_left(slots, lo), bisect.bisect_right(slots, hi)
            for site in slots[first:last]:
                lead = age + cycles * (hi - site) / max(1, hi - lo)
                if minimum <= lead <= maximum:
                    found.add(site)
        age += cycles
        if age > maximum:
            break
    return found


def sample_candidates(samples, slots, sections, pattern, minimum, maximum,
                      maps=None, maps_dir=None, counts=None):
    """Yield one target and its eligible predecessors per sampled miss."""
    if counts is None:
        counts = collections.Counter()
    biases = {None: mapping_bias(maps.read_text(), pattern, sections)} if maps else {}
    for line in samples.open():
        match = HEADER.match(line)
        if not match:
            continue
        counts['all_samples'] += 1
        if not pattern.search(match[3]):
            continue
        counts['target_dso_samples'] += 1
        pid = int(match[1]) if match[1] else None
        if maps_dir and pid not in biases:
            path = maps_dir / f'{pid}.maps'
            biases[pid] = mapping_bias(path.read_text(), pattern, sections) if path.exists() else None
        bias = biases.get(pid) if maps_dir else biases[None]
        if bias is None:
            counts['unmapped_samples'] += 1
            continue
        target = (int(match[2], 16) - bias) & ~63
        if not any(va <= target < va + size for va, _, size in sections):
            counts['outside_executable_sections'] += 1
            continue
        edges = [(int(fr, 16), fr_dso, int(to, 16), to_dso,
                  int(cycles) if cycles.isdigit() else None)
                 for fr, fr_dso, to, to_dso, cycles, _ in EDGE.findall(line)]
        counts['parsed_branch_edges'] += len(edges)
        candidates = candidate_sites(edges, slots, bias, pattern, minimum, maximum)
        candidates = {site for site in candidates if site & ~63 != target}
        if candidates:
            counts['samples_with_candidate'] += 1
        yield target, candidates


def select_spaced(ranked, budget, distance):
    """Bound static hint density without asserting dynamic queue occupancy."""
    chosen = []
    for row in ranked:
        if any(abs(row[1] - other[1]) < distance for other in chosen):
            continue
        chosen.append(row)
        if len(chosen) == budget:
            break
    return chosen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('index', type=Path)
    ap.add_argument('samples', type=Path, help='perf script -F pid,ip,dso,brstack')
    ap.add_argument('output', type=Path)
    ap.add_argument('--dso', required=True, help='regex identifying the target DSO')
    maps = ap.add_mutually_exclusive_group(required=True)
    maps.add_argument('--maps', type=Path, help='one mapping, also valid for unchanged fork mappings')
    maps.add_argument('--maps-dir', type=Path, help='<pid>.maps snapshots')
    ap.add_argument('--min-lead', type=int, default=32)
    ap.add_argument('--max-lead', type=int, default=256)
    ap.add_argument('--budget', type=int, default=32)
    ap.add_argument('--min-votes', type=int, default=3)
    ap.add_argument('--min-target-share', type=float, default=.2)
    ap.add_argument('--min-site-distance', type=int, default=0,
                    help='minimum code-byte distance between selected hint sites')
    ap.add_argument('--hint', choices=('t1', 't0'), default='t1')
    ap.add_argument('--heldout', type=Path)
    ap.add_argument('--heldout-maps', type=Path)
    a = ap.parse_args()
    if a.output.exists() or a.budget < 1 or a.min_site_distance < 0 or not 0 <= a.min_lead <= a.max_lead:
        ap.error('new output, positive budget and ordered lead bounds required')
    if bool(a.heldout) != bool(a.heldout_maps):
        ap.error('heldout samples require their own mapping snapshot')
    original = a.source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    index = json.loads(a.index.read_text())
    if digest != index['sha256']:
        ap.error('index belongs to another binary')
    sections = executable_sections(str(a.source))
    pattern = re.compile(a.dso)
    slot_info = {row[0]: row for row in index['slots']}
    slots = sorted(slot_info)
    votes = collections.defaultdict(collections.Counter)
    counts = collections.Counter()
    for target, candidates in sample_candidates(a.samples, slots, sections, pattern,
            a.min_lead, a.max_lead, a.maps, a.maps_dir, counts):
        for site in candidates:
            votes[site][target] += 1
    ranked = []
    for site, distribution in votes.items():
        target, count = distribution.most_common(1)[0]
        share = count / distribution.total()
        if count >= a.min_votes and share >= a.min_target_share:
            ranked.append((count, site, target, share, distribution.total()))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    data = bytearray(original)
    patches = []
    for count, site, target, share, total in select_spaced(ranked, a.budget, a.min_site_distance):
        slot = slot_info[site]
        addr, offset, length, _ = slot[:4]
        before = bytes(data[offset:offset + length])
        expected = bytes.fromhex(slot[4]) if len(slot)>4 else MULTI_NOP[length]
        if before != expected or not is_padding_nop(before):
            raise ValueError('selected site is not the indexed canonical NOP')
        opcode = '0f1815' if a.hint == 't1' else '0f180d'
        after = b'\x66' * (length - 7) + bytes.fromhex(opcode) + struct.pack('<i', target - addr - length)
        data[offset:offset + length] = after
        patches.append({'address': addr, 'offset': offset, 'target': target,
                        'before': before.hex(), 'after': after.hex(),
                        'training_votes': count, 'conditional_miss_share': share,
                        'site_miss_sample_votes': total})
    if not patches:
        raise RuntimeError(f'no candidates: {dict(counts)}')
    reversed_data = bytearray(data)
    for patch in patches:
        raw = bytes.fromhex(patch['before'])
        reversed_data[patch['offset']:patch['offset'] + len(raw)] = raw
    assert bytes(reversed_data) == original
    a.output.write_bytes(data)
    a.output.chmod(0o755)
    metadata = {'source_sha256': digest, 'sha256': hashlib.sha256(data).hexdigest(),
                'trace_sha256': hashlib.sha256(a.samples.read_bytes()).hexdigest(),
                'arguments': vars(a), 'counts': dict(counts), 'sites': len(patches),
                'patches': patches, 'twin': str(a.source), 'reversed_patches_sha256': digest,
                'warning': 'Profile-guided; LBR cycles are a lead proxy. Votes are not execution counts or additive coverage.'}
    if a.heldout:
        selected = {p['address']: p['target'] for p in patches}
        quality = collections.Counter()
        for target, candidates in sample_candidates(a.heldout, slots, sections, pattern,
                a.min_lead, a.max_lead, a.heldout_maps, counts=quality):
            seen = candidates & selected.keys()
            if seen:
                quality['samples_with_selected_predecessor'] += 1
            if any(selected[site] == target for site in seen):
                quality['samples_with_correct_selected_target'] += 1
        metadata['heldout'] = dict(quality)
        metadata['heldout_sha256'] = hashlib.sha256(a.heldout.read_bytes()).hexdigest()
    a.output.with_suffix('.json').write_text(json.dumps(metadata, default=str, indent=2))
    print(json.dumps({'sites': len(patches), 'counts': dict(counts)}))


if __name__ == '__main__':
    main()
