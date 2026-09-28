#!/usr/bin/env python3
"""Train small static target sets from entry misses following indirect calls.

LBR association identifies retired paths, not a BTB/FDIP cause. The compiler
matches caller function names, not individual machine call-site offsets.
"""
import argparse
import bisect
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import subprocess

import dense_build as b
from dense_cause_analysis import Code, EDGE, category
from lean_profile import symbol_ranges
from lbr_padding_prefetch import HEADER, mapping_bias


def select(call_counts, limit=3, minimum=3):
    if not 1 <= limit <= 8 or minimum < 1:
        raise ValueError('Invalid profile budget')
    grouped = defaultdict(Counter)
    for (caller, target), count in call_counts.items():
        if count >= minimum:
            grouped[caller][target] = count
    return {caller: sorted(counts, key=lambda name: (-counts[name], name))[:limit]
            for caller, counts in sorted(grouped.items())}


def aggregate(folder, binary, code, ranges, globals_only, phase):
    metadata = json.loads((folder/'dsos.json').read_text())
    main = next(name for name in metadata if name.startswith('/custom/'))
    assert metadata[main]['sha256'] == b.sha(binary)
    bias = mapping_bias((folder/'maps.txt').read_text(), re.compile('^'+re.escape(main)+'$'), code.sections)
    assert bias is not None
    starts = [row['start'] for row in ranges]
    max_ends = []
    for row in ranges:
        max_ends.append(max(row['end'], max_ends[-1] if max_ends else 0))

    def owner(va):
        i = bisect.bisect_right(starts, va)-1
        if i < 0 or va >= ranges[i]['end']:
            return None
        # Reject overlapping symbol ranges instead of silently choosing one.
        if i and max_ends[i-1] > va:
            return None
        return ranges[i]

    def is_main(dso):
        return dso[1:-1] in (main, Path(main).name)

    stats = Counter(); pairs = Counter(); edges = Counter(); entry_ips = Counter(); main_ips = Counter()
    path = folder/phase/'samples.txt'
    for text in path.open():
        header = HEADER.match(text)
        if not header:
            continue
        stats['samples'] += 1
        if not is_main(header[3]):
            continue
        ip = int(header[2], 16); va = ip-bias
        main_ips[va] += 1
        if not code.get(va)[0]:
            stats['ip_not_instruction_boundary'] += 1
            continue
        target = owner(va)
        if not target or va//64 != target['start']//64:
            continue
        stats['entry_line_samples'] += 1
        entry_ips[va] += 1
        history = EDGE.findall(text)
        if history and is_main(history[0][1]) and int(history[0][0], 16) == ip:
            history = history[1:]
        if not history:
            continue
        source, source_dso, dest, dest_dso, predicted, cycles, kind = history[0]
        if not is_main(source_dso) or not is_main(dest_dso):
            continue
        source, dest = int(source, 16)-bias, int(dest, 16)-bias
        if not (target['start'] <= dest <= va and code.straight(dest, va)):
            continue
        if category(code.get(source)[1]) not in ('indirect_call', 'indirect_jump'):
            continue
        stats['indirect_entry_samples'] += 1
        caller = owner(source)
        names = sorted(set(target['names']) & globals_only)
        if caller is None or not names:
            stats['unavailable_global_target_or_caller'] += 1
            continue
        # One representative global symbol is sufficient for alias entries.
        name = names[0]
        for caller_name in caller['names']:
            pairs[(caller_name, name)] += 1
        edges[(source, dest, va, name, tuple(caller['names']))] += 1
    recorded = json.loads((folder/phase/'record_types.json').read_text())
    assert stats['samples'] == recorded['SAMPLE'] and stats['samples'] > 100
    assert not any(recorded.get(key, 0) for key in ('LOST', 'LOST_SAMPLES', 'THROTTLE', 'UNTHROTTLE'))
    result = dict(stats=dict(stats), pairs=[dict(caller=a, target=z, samples=n) for (a,z),n in pairs.most_common()],
                  edges=[dict(source=hex(a), dest=hex(z), ip=hex(ip), target=name, caller_names=list(callers), samples=n)
                         for (a,z,ip,name,callers),n in edges.most_common()],
                  entry_ips=[dict(va=hex(ip), samples=n) for ip,n in entry_ips.most_common()],
                  main_ips=[dict(va=hex(ip), samples=n) for ip,n in main_ips.most_common()],
                  source_sha256=b.sha(path), binary_sha256=b.sha(binary), phase=phase)
    return result, pairs


def prepare(capture, out, limit=3, minimum=3):
    assert (capture/'complete.json').exists(), 'Decode and stop workload before training'
    out.mkdir(parents=True, exist_ok=False)
    overrides = json.loads((capture/'protocol.json').read_text())['overrides']
    combined = Counter(); results = {}
    # Dependencies are built once and shared by all three service ELFs. A
    # speculative reference from common library code must bind in every ELF.
    global_sets = []
    for binary in overrides.values():
        table = subprocess.check_output(['nm', '-g', '--defined-only', str(binary)], text=True)
        global_sets.append({fields[-1] for line in table.splitlines()
                            if len(fields := line.split()) >= 3 and fields[-2] in 'TW'})
    common_globals = set.intersection(*global_sets)
    for service, binary in overrides.items():
        binary = Path(binary); code = Code(binary); ranges, command = symbol_ranges(binary)
        phases = {}
        for phase in ('train', 'heldout'):
            result, counts = aggregate(capture/service, binary, code, ranges, common_globals, phase)
            phases[phase] = result
            if phase == 'train':
                # Normalize service sample totals so Compose's extra code work
                # does not dictate the entire cross-service target ranking.
                denominator = result['stats']['samples']
                for pair, count in counts.items():
                    if count >= minimum:
                        combined[pair] = max(combined[pair], round(count/denominator*1e9))
        results[service] = dict(symbol_command=command, symbol_ranges=ranges, phases=phases)
    callers = select(combined, limit, 1)
    assert callers
    profile = dict(schema='prefetchit.indirect_targets.v1', callers=callers)
    b.save(out/'indirect_targets.json', profile)
    for service, result in results.items():
        for phase, data in result['phases'].items():
            rows = data['edges']
            data['selected_edge_samples'] = sum(row['samples'] for row in rows
                if any(row['target'] in callers.get(name, []) for name in row['caller_names']))
            data['caveat'] = 'Alias caller names can duplicate pair counts; edge/IP rows retain single sample counting. Coverage is association only.'
    with gzip.open(out/'aggregates.json.gz', 'wt') as f:
        json.dump(results, f, separators=(',', ':'))
    names = sorted({name for targets in callers.values() for name in targets})
    b.save(out/'summary.json', dict(callers=len(callers), target_names=names, limit=limit, minimum=minimum,
        target_binding='Only global function names defined in every original service ELF; shared static dependencies must not acquire service-specific unresolved references.',
        capture=str(capture), profile_sha256=b.sha(out/'indirect_targets.json'),
        provenance='Caller/target selection uses train only. Heldout is diagnostic and does not alter selection.',
        stats={s:{phase:data['stats'] for phase,data in r['phases'].items()} for s,r in results.items()}))
    # Raw recordings were removed by decode; all decoded rows needed for the
    # next build are now represented in compact edge/IP/pair aggregates.
    from e2e_lbr import remove_generated
    unused = [capture/service/phase/'samples.txt' for service in overrides for phase in ('train','heldout')]
    unused += [p for service in overrides for p in (capture/service/'dsos').iterdir() if p.is_file()]
    remove_generated(unused, out/'training_cleanup.json', 'Train and heldout compact edge/IP aggregates retained; decoded text and copied DSO snapshots no longer needed')
    return profile


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path); p.add_argument('out', type=Path)
    p.add_argument('--limit', type=int, default=3); p.add_argument('--minimum', type=int, default=3)
    a = p.parse_args(); prepare(a.capture, a.out, a.limit, a.minimum)
