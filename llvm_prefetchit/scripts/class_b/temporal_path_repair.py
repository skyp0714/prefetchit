#!/usr/bin/env python3
"""Repair residual path coverage with at most one extra hint per existing call."""
import argparse
import collections
import copy
import json
from pathlib import Path

import dense_build as b
from temporal_path_analysis import load_original_images, files, read, target_for, observed_calls, choose, stubs
from temporal_path_refine import base_arm, deployed_policies
from temporal_path_residual import policies


def description(source_sha, call, target_sha, target, anchors):
    local, external = call['targets'], call.get('got_targets', [])
    if len(local) + len(external) >= 8:
        return None
    existing = {(source_sha, value // 64) for value in local}
    existing.update((value['target_sha'], value['target'] // 64) for value in external)
    if (target_sha, target // 64) in existing:
        return None
    if source_sha == target_sha:
        return dict(kind='local', target=target)
    candidates = anchors.get((source_sha, target_sha), [])
    if not candidates:
        return None
    anchor = min(candidates, key=lambda value: (-value['observations'], value['got']))
    addend = target - anchor['anchor']
    if not -(1 << 31) <= addend < 1 << 31:
        return None
    return dict(kind='cross', target=target, got=anchor['got'], anchor=anchor['anchor'], addend=addend)


def logical_targets(deployed):
    return {(digest, call['site']): (call['callee'], call['expected'],
                tuple(sorted(call['targets'])),
                tuple(sorted((target['target_sha'], target['target']) for target in call.get('got_targets', []))))
            for digest, record in deployed.items() for call in record['plan']['calls']}


def prepare(root, base='pathwide', phase='best1'):
    name = base + '_repair'
    out = root / 'candidates' / name
    out.mkdir(parents=True, exist_ok=False)
    b.space(root)
    known = policies(root)
    original = base_arm(root, base)
    deployed = deployed_policies(original, known)
    deployment = base
    decision = root / 'screen2_decision.json'
    transfer = dict(training_base=base, deployment_base=base, transferred=False)
    if decision.exists():
        incumbent = json.loads(decision.read_text())['selected']
        current_arm = base_arm(root, incumbent)
        current = deployed_policies(current_arm, known)
        same_targets = logical_targets(current) == logical_targets(deployed)
        same_hint_kind = not any(hint.get('kind') == 'it0' for record in current.values() for hint in record['hints'])
        transfer.update(incumbent=incumbent, same_logical_targets=same_targets, all_t1=same_hint_kind)
        if same_targets and same_hint_kind:
            deployment, original, deployed = incumbent, current_arm, current
            transfer.update(deployment_base=deployment, transferred=deployment != base)
    transfer['rule'] = 'Carry forward a selected T1 implementation only after exact call-site/callee/original-byte/target-address equivalence. Residual training remains the recorded pathwide run; instruction addresses in original code are unchanged.'
    b.save(out / 'transfer_validation.json', transfer)
    anchors = {(row['source'], row['target']): row['entries']
               for row in json.loads((root / 'analysis/got_anchors.json').read_text())['anchors']}
    calls = {(digest, call['site']): call for digest, record in deployed.items() for call in record['plan']['calls']}
    images = load_original_images(root)
    rows, inputs = [], []
    quality = collections.Counter()
    paths = files(root, phase, 'l2')
    assert len(paths) == 12
    for path in paths:
        assert json.loads((path.parents[2] / 'protocol.json').read_text())['arm'] == base
        data = read(path)
        digests = [known[d]['source_sha256'] if d in known else d for d in data['digests']]
        inputs.append(dict(path=str(path), sha256=b.sha(path), samples=len(data['rows'])))
        for sample in data['rows']:
            quality['all_samples'] += 1
            if sample['dso'] < 0:
                continue
            target_sha = digests[sample['dso']]
            if target_sha not in images:
                continue
            target = target_for(images[target_sha], sample)
            if target is None:
                quality['outside_original_code'] += 1
                continue
            sites = {}
            for site, age in observed_calls(sample, digests, images, 64, 8192).items():
                if site not in calls:
                    continue
                target_description = description(site[0], calls[site], target_sha, target, anchors)
                if target_description is not None:
                    sites[site] = dict(target_description, age=age)
            quality['eligible_samples'] += bool(sites)
            rows.append(dict(target_sha=target_sha, target=target, line=target // 64, sites=sites,
                             weight=data['period'] / data['requests'], service=data['service'], age_us=sample['age_us']))
    frequency = json.loads((root / 'analysis/call_frequency.json').read_text())
    rates = {(row['sha'], row['site']): row['per_request'] for row in frequency['rates']}
    selected = choose(rows, rates, frequency['floor'], max_sites=768, max_hints=768,
                      per_site=1, min_gain=8, goal=.60, cross_cost=2.5)
    coverage = selected['covered'] / quality['all_samples']
    selected.update(inputs=inputs, quality=dict(quality), base=deployment, residual_training_base=base, phase=phase,
                    covered_all_sample_fraction=coverage,
                    rule='At most one added hint per existing call; eight total hints/site, 768 additions maximum, at least eight supporting residual samples. Earlier call observed at 64..8192 completed-branch cycles. Original training call rates and original audited GOT-anchor identities retained. No new call redirects.',
                    limitation='Residual diagnosis is adaptive training, not independent coverage validation. Existing static targets may be reissued from a different observed caller. Retired-branch cycles do not measure hint-to-fetch lead.')
    b.save(out / 'selection.json', selected)
    eligible = coverage >= .12 and bool(selected['choices'])
    b.save(out / 'model_decision.json', dict(eligible=eligible, coverage=coverage,
        rule='Build only if the residual training model covers at least 12% of all remaining L2 samples within the fixed hint budget. No E2E-based build decision.'))
    if not eligible:
        return None
    del images, rows
    groups = collections.defaultdict(list)
    for choice in selected['choices']:
        groups[choice['source_sha']].append(choice)
    arm, nop, builds, remap, generated = copy.deepcopy(original), copy.deepcopy(original), {}, {}, []
    try:
        for digest, old in deployed.items():
            b.space(root)
            plan = copy.deepcopy(old['plan'])
            by_site = {call['site']: call for call in plan['calls']}
            for choice in groups[digest]:
                call = by_site[choice['site']]
                assert description(digest, call, choice['target_sha'], choice['target'], anchors) is not None
                if choice['kind'] == 'local':
                    call['targets'].append(choice['target'])
                else:
                    call.setdefault('got_targets', []).append({key: choice[key] for key in ('got', 'anchor', 'addend', 'target', 'target_sha')})
                if call.get('got_targets'):
                    call['got_targets'].sort(key=lambda value: (value['got'], value['addend']))
            source = Path(old['source'])
            binary = root / 'builds' / name / digest / source.name
            b.save(root / 'plans' / name / (digest + '.json'), dict(plan=plan, source=str(source),
                base_binary=old['binary'], base_sha256=old['sha256'], kept_choices=groups[digest],
                source_sha256=b.sha(__file__), builder_sha256=b.sha(stubs.__file__)))
            record = stubs.build(source, plan, binary)
            generated += [binary, Path(str(binary) + '.nop')]
            builds[digest] = dict(binary=str(binary), nop=str(binary) + '.nop', sha256=record['sha256'],
                nop_sha256=record['nop_sha256'], extra_instruction_bytes=record['extra_instruction_bytes'],
                sites=len(by_site), new_hints=len(groups[digest]), hints=len(record['hints']))
            remap[old['binary']] = str(binary)
        for destination, suffix in ((arm, ''), (nop, '.nop')):
            destination['overrides'] = {key: remap.get(value, value) + suffix if value in remap else value
                                        for key, value in destination['overrides'].items()}
            value = destination['mongo_binary']
            destination['mongo_binary'] = remap[value] + suffix if value in remap else value
            destination['libraries'] = {key: {path: remap[value] + suffix if value in remap else value
                                              for path, value in values.items()}
                                        for key, values in destination.get('libraries', {}).items()}
        arm['controls'] = ['original', 'mongo', deployment, name + '_nop']
        nop['controls'] = ['original']
        result = dict(arm=arm, nop=nop, builds=builds, excluded=[], base=deployment, residual_training_base=base,
                      selection_sha256=b.sha(out / 'selection.json'))
        prepared = json.loads((root / 'prepared_candidates.json').read_text())
        prepared[name] = result
        b.save(out / 'prepared.json', result)
        b.save(root / 'prepared_candidates.json', prepared)
        return name
    except BaseException as error:
        from e2e_lbr import remove_generated
        b.save(out / 'failure.json', dict(error=repr(error), completed=builds))
        existing = [path for path in generated if path.exists()]
        if existing:
            remove_generated(existing, out / 'failure_cleanup.json', 'Failed residual repair; plans, patches, hashes and failure retained.')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(dict(prepared=prepare(args.root))))
