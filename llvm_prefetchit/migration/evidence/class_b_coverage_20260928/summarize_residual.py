"""Classify retained exact-IP aggregates; never decode during timing."""
from pathlib import Path
from collections import Counter
import bisect, gzip, hashlib, json
r = Path('/storage/prefetchit/class_b_coverage_20260928')
read = lambda p: json.loads(p.read_text())
def compressed(p):
    with gzip.open(p, 'rt') as f: return json.load(f)

def lookup(ranges):
    ranges = sorted(ranges, key=lambda v: (v['start'], v['end']))
    starts = [v['start'] for v in ranges]
    ends = []
    for v in ranges: ends.append(max(v['end'], ends[-1] if ends else 0))
    def owner(va):
        i = bisect.bisect_right(starts, va)-1
        if i < 0 or va >= ranges[i]['end'] or (i and ends[i-1] > va):
            return None
        return ranges[i]
    return owner

def classify(ips, ranges, targets):
    owner = lookup(ranges)
    counts = Counter(); functions = Counter(); groups = {}
    for row in ips:
        va = int(row['va'], 16); n = row['samples']; symbol = owner(va)
        if symbol is None: category = 'unknown_or_overlapping_symbol'
        else:
            entry = va//64 == symbol['start']//64
            category = ('targeted_' if va//64 in targets else 'untargeted_')+('entry' if entry else 'interior')
            names = tuple(sorted(symbol['names']))
            functions[names] += n
            groups.setdefault(names, Counter())[category] += n
        counts[category] += n
    total = sum(counts.values())
    return dict(samples=total, counts=dict(counts),
        pct={k:100*v/total for k,v in counts.items()},
        functions=[dict(names=list(names), samples=n, main_share_pct=100*n/total,
                        categories=dict(groups[names]))
                   for names,n in functions.most_common()])

# Exact boundaries, aliases represented once, and overlapping symbol ranges.
fixture=[dict(start=65,end=145,names=['a','alias_a']),
         dict(start=160,end=240,names=['b']),dict(start=200,end=220,names=['nested'])]
check=classify([dict(va=hex(x),samples=1) for x in (65,127,128,160,205,300)],fixture,{1})
assert check['counts']==dict(targeted_entry=2,untargeted_interior=1,
                             untargeted_entry=1,unknown_or_overlapping_symbol=2)
assert sum(x['samples'] for x in check['functions'])==4

assert (r/'selected_diagnostic_summary.json').exists()
selection=read(r/'confirmation_selection.json')['selected']
base=compressed(r/'indirect_profile/aggregates.json.gz')
tag={'coverage_full_it0':'coverage_callees','indirect_it0':'coverage_indirect',
     'lift_it0':'coverage_indirect_lift','paths_it0':'coverage_paths'}
result={}
for service,choice in selection.items():
    current=compressed(r/'selected_diagnostic'/service/'all_main_ips.json.gz')
    rows=compressed(r/(tag[choice['name']]+'_metadata.json.gz'))
    audit=read(r/(tag[choice['name']]+'_build.json'))['audits'][service]
    # Metadata was recorded before the byte-preserving T1 -> IT0 opcode patch.
    # Tie both images by the saved audited hash chain, never by filename alone.
    assert audit['path']==choice['binary'] and audit['sha256']==current['binary_sha256']
    assert audit['same_layout'] and audit['all_targets_instruction_boundaries']
    metadata=next(row for row in rows if row['path']==audit['source'])
    assert metadata['sha256']==audit['source_sha256']
    targets={row['target']//64 for row in metadata['records'] if row['active']}
    owner=lookup(current['symbol_ranges']); names=set()
    for row in metadata['records']:
        if row['active']:
            symbol=owner(row['target'])
            if symbol and row['target']//64==symbol['start']//64:
                names.update(symbol['names'])
    old_targets={s['start']//64 for s in base[service]['symbol_ranges'] if names.intersection(s['names'])}
    current_summary=classify(current['counts'],current['symbol_ranges'],targets)
    original_summary=classify(base[service]['phases']['heldout']['main_ips'],base[service]['symbol_ranges'],old_targets)
    for summary,folder in [(current_summary,r/'selected_diagnostic'/service/'l2'),
                           (original_summary,r/'indirect_capture'/service/'heldout')]:
        window=read(folder/'window.json')
        summary.update(requests=window['completed'],
            sampled_main_misses_per_request=summary['samples']/window['completed'],
            period_scaled_main_events_per_request=257*summary['samples']/window['completed'])
    result[service]=dict(selected_policy=choice['name'],selected=current_summary,
        original_heldout_with_selected_target_names=original_summary,
        target_names=len(names),target_lines=len(targets),
        metadata_source_sha256=metadata['sha256'],selected_sha256=current['binary_sha256'],
        same_layout_opcode_patch_audit=audit)
out=dict(services=result,fixture_checks_passed=True,
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    interpretation='Separate one-window PEBS diagnostics, not paired performance evidence. '
    'All percentages use main-image samples. Entry is the 64B line containing symbol start; '
    'ambiguous overlaps remain in denominator. Aliases counted once. Original heldout target '
    'addresses are reconstructed by selected linked target names; no cross-binary VA matching. '
    'Period-scaled sample counts are diagnostic estimates, not the independent PMU result. '
    'Residual target overlap is neither prefetch execution coverage nor fill success.')
(r/'residual_location_summary.json').write_text(json.dumps(out,indent=2)+'\n')
for service,v in result.items(): print(service,json.dumps(v['selected']['pct']))
