#!/usr/bin/env python3
"""Use RPC decoding, handler identity and typed async work to warm future code."""
import argparse
import bisect
import collections
import copy
import json
from pathlib import Path
import re
import struct
import subprocess
import time

import dense_build as b
from dense_cause_analysis import Code, category
import call_stub_prefetch as stubs
from temporal_path_analysis import read

PREVIOUS = Path('/storage/prefetchit/class_b_rpc_future_20261001')
TEMPORAL = Path('/storage/prefetchit/class_b_temporal_20261001')


def load(path):
    return json.loads(path.read_text())


def worker_identity(name):
    handler = re.search(r'media_service::(\w+Handler)::(\w+)\(', name)
    closure = re.search(r'\$_\d+|\{lambda[^}]+\}', name)
    return ':'.join([*handler.groups(), closure[0]]) if handler and closure else None


def prepare(root):
    root.mkdir(parents=True, exist_ok=True)
    b.space(root)
    assert not (root / 'prepared_candidates.json').exists()
    (root / 'source_versions').mkdir(exist_ok=True)
    refs = load(PREVIOUS / 'references.json')
    base = load(PREVIOUS / 'prepared_candidates.json')['no_dso']
    inventory = load(PREVIOUS / 'rpc_inventory.json')
    b.save(root / 'references.json', refs)
    b.save(root / 'rpc_inventory.json', inventory)
    b.save(root / 'protocol.json', dict(start_epoch=time.time(), deadline_utc='2026-10-01T15:00:00Z',
        timezone_assumption='10:00 America/Chicago, pending optional user clarification',
        scope='Full Media compose-review C4, MovieId included, no DSO hints in new policies; kernel unchanged.',
        objective='Exploit RPC-specific decoding/handler and typed asynchronous continuations, increasing useful future-code coverage with modest issuance.',
        training='Earlier full-policy residual PEBS/LBR is new training for this campaign, never current evaluation requests.',
        selection='Two exploratory blocks versus no_dso; highest geometric RPS with CPU <= no_dso+0.5% and p99 <= no_dso+2%. '
                  'Confirm selected RPC refinement against original, existing full policy and no_dso on fresh independent blocks. '
                  'Confirmation block count is time-only: four if it starts by 13:55 UTC, otherwise three. Do not pool phases.',
        retention='Preserve measurements/settings/commands/source/patches/hashes; remove rejected generated bulk immediately after extracting results.',
        no_measurement_overlap='No builds or heavy analysis during timing. Controller84-85, load16-19, servers32-39,2GHz restored per trial.'))
    prepared = {name: dict(arm=copy.deepcopy(base['arm']), nop=copy.deepcopy(base['arm']), builds={})
                for name in ('rpc_route', 'rpc_worker', 'rpc_staged')}
    model = {}
    for service, info in inventory.items():
        b.space(root)
        source = Path(info['source'])
        code = Code(source)
        symbols = [v for line in subprocess.check_output(['nm', '-S', '--defined-only', source], text=True).splitlines()
                   if len(v := line.split()) == 4 and v[2] in 'TtWw']
        names = subprocess.check_output(['c++filt'], input='\n'.join(v[3] for v in symbols)+'\n', text=True).splitlines()
        demangled = {v[3]: name for v, name in zip(symbols, names)}
        function_addresses = collections.defaultdict(list)
        for ip, (_, _, function) in code.instructions.items():
            function_addresses[function].append(ip)
        first_call = lambda function: next((ip for ip in function_addresses[function]
                                            if category(code.get(ip)[1]) == 'direct_call'), None)
        worker_functions = {function: worker_identity(demangled.get(function, function)) for function in function_addresses}
        worker_roots = {}
        for function, identity in worker_functions.items():
            if identity and function.startswith('_ZNSt13__future_base17_Async_state_impl') and function.endswith('6_M_runEv'):
                site = first_call(function)
                assert site is not None
                assert identity not in worker_roots, (service, identity)
                worker_roots[identity] = dict(site=site, function=function, name=demangled[function])
        direct_context, anchors = {}, {}
        for method in info['methods']:
            name = method['method']
            for phase, address in [('decoder', method['args_callee']), ('handler', method['handler']['va'])]:
                function = code.get(address)[2]
                direct_context[function] = (phase, name)
            direct_context[code.get(method['processor']['va'])[2]] = ('decoder', name)
            anchors['decoder:'+name] = dict(site=method['args_site'], method=name, phase='decoder')
            site = first_call(code.get(method['handler']['va'])[2])
            if site is not None:
                anchors['handler:'+name] = dict(site=site, method=name, phase='handler')
        for identity, row in worker_roots.items():
            anchors['worker:'+identity] = dict(row, phase='worker', method=identity)
        old_full = load(Path(refs['previous']['arm']['overrides'][service]+'.json'))
        stub_origins = {jump: patch['site'] for patch in old_full['patches'] for jump in patch['terminal_jumps']}

        def context(ip):
            ip = stub_origins.get(ip, ip)
            function = code.get(ip)[2]
            worker = worker_functions.get(function)
            if worker in worker_roots:
                return 'worker:'+worker
            match = direct_context.get(function)
            return ':'.join(match) if match else None

        path = TEMPORAL / 'profiles/final_native' / service / 'l2/observations.json.gz'
        data = read(path)
        digest = b.sha(refs['previous']['arm']['overrides'][service])
        assert data['digests'].count(digest) == 1
        main = data['digests'].index(digest)
        counts = collections.defaultdict(collections.Counter)
        addresses, all_lines = {}, collections.Counter()
        quality = collections.Counter()
        for sample in data['rows']:
            quality['all'] += 1
            if sample['dso'] != main:
                quality['outside_main'] += 1
                continue
            ip = sample['ip']
            if not code.get(ip)[0]:
                quality['not_original_instruction'] += 1
                continue
            line = ip//64
            all_lines[line] += 1
            addresses[line] = min(addresses.get(line, ip), ip)
            label = context(ip)
            if label is None:
                # Most recent recognizable typed context; bounded history is an
                # association, not a complete stack or a measured fetch lead.
                for sd, fr, td, to, pred, cycles, kind in sample['edges']:
                    label = context(fr) if sd == main else None
                    if label is None and td == main:
                        label = context(to)
                    if label is not None:
                        break
            if label is not None:
                counts[label][line] += 1
                quality['context_'+label.split(':', 1)[0]] += 1
        baseline = Path(base['builds'][service]['binary'])
        old = load(Path(str(baseline)+'.json'))
        prior_sites = {p['site']: p for p in old['patches']}
        raw = baseline.read_bytes()
        elf = stubs.Elf(raw)
        selected = {}
        for variant in prepared:
            choices = []
            for label, anchor in anchors.items():
                phase, method = label.split(':', 1)
                if variant == 'rpc_route' and phase != 'decoder':
                    continue
                if variant == 'rpc_worker' and phase != 'worker':
                    continue
                weights = counts[label].copy()
                if variant == 'rpc_route':
                    weights.update(counts['handler:'+method])
                site = anchor['site']
                existing = prior_sites.get(site, {}).get('targets', [])
                choices_here = [(line, n) for line, n in weights.most_common()
                                if n >= 3 and line != site//64
                                and all(line != target//64 for target in existing)][:8-len(existing)]
                if not choices_here:
                    continue
                targets = [addresses[line] for line, n in choices_here]
                choices.append(dict(anchor=label, site=site, targets=targets, counts=[n for line, n in choices_here],
                    existing_targets=existing, classified_samples=sum(weights.values()),
                    function=code.get(site)[2], callee_asm=code.get(site)[1]))
            assert len({r['site'] for r in choices}) == len(choices)
            selected[variant] = choices
            if not choices:
                continue
            calls = []
            for row in choices:
                site = row['site'];offset = elf.offset(site, 5, True)
                assert raw[offset] == 0xe8
                callee = site+5+struct.unpack_from('<i', raw, offset+1)[0]
                calls.append(dict(site=site, callee=callee, expected=raw[offset:offset+5].hex(), targets=row['targets']))
            plan = dict(sha256=b.sha(baseline), calls=calls)
            output = root / 'builds' / variant / service / source.name
            b.save(root / 'plans' / variant / (service+'.json'), dict(source=str(baseline), plan=plan, choices=choices,
                training=str(path), training_sha256=b.sha(path),
                rule='Main-ELF residual targets associated with known RPC phase or typed async worker. '
                     'No forced handler-entry lines or issuing-callsite cache line. Minimum three training samples, at most eight combined hints/site. '
                     'Worker hint executes inside the typed async worker before its first normal direct call.'))
            built = stubs.build(baseline, plan, output)
            after = stubs.Elf(output.read_bytes())
            for hint in old['hints']:
                instruction = bytes.fromhex(hint['original'])
                offset = after.offset(hint['va'], len(instruction), True)
                assert after.data[offset:offset+len(instruction)] == instruction
            prepared[variant]['arm']['overrides'][service] = str(output)
            prepared[variant]['nop']['overrides'][service] = str(output)+'.nop'
            prepared[variant]['builds'][service] = dict(binary=str(output), nop=str(output)+'.nop',
                sha256=built['sha256'], nop_sha256=b.sha(str(output)+'.nop'), sites=built['call_sites'],
                hints=len(built['hints']), extra_instruction_bytes=built['extra_instruction_bytes'],
                preserved_previous_hints=len(old['hints']), selections=choices)
            b.save(root / 'prepared_candidates.json', prepared)
        model[service] = dict(quality=dict(quality), worker_roots=worker_roots, selected=selected,
            training=str(path), training_sha256=b.sha(path), requests=data['requests'], period=data['period'],
            footprint={name:dict(lines=len(lines := {target//64 for row in choices for target in row['targets']}),
                overlapping_samples=sum(all_lines[line] for line in lines), total_process_samples=quality['all'],
                estimated_overlap_per_request=sum(all_lines[line] for line in lines)*data['period']/data['requests'])
                for name, choices in selected.items()})
        b.save(root / 'model.json', model)
        print(json.dumps(dict(service=service, quality=dict(quality),
            variants={name:dict(sites=len(rows), hints=sum(len(r['targets']) for r in rows)) for name, rows in selected.items()})), flush=True)
    arms = dict(original=refs['original'], full_dso=dict(refs['previous']['arm'], controls=['original']),
                no_dso=dict(base['arm'], controls=['original', 'full_dso']))
    for name, entry in prepared.items():
        assert entry['builds'], name
        entry['arm']['controls'] = ['original', 'full_dso', 'no_dso', name+'_nop']
        entry['nop']['controls'] = ['no_dso']
        arms[name] = entry['arm'];arms[name+'_nop'] = entry['nop']
    b.save(root / 'prepared_candidates.json', prepared)
    b.save(root / 'arms.json', arms)
    b.save(root / 'prepared_summary.json', {name:dict(elf_count=len(entry['builds']),
        sites=sum(v['sites'] for v in entry['builds'].values()), hints=sum(v['hints'] for v in entry['builds'].values()),
        code_bytes=sum(v['extra_instruction_bytes'] for v in entry['builds'].values())) for name, entry in prepared.items()})
    digest = b.sha(__file__)
    (root / 'source_versions' / (digest+'.py')).write_bytes(Path(__file__).read_bytes())


def worker_it0(root, parent):
    """Change only the fresh typed worker's added T1 opcodes to equal-size IT0."""
    b.space(root)
    assert parent in ('rpc_worker', 'rpc_staged')
    prepared = load(root / 'prepared_candidates.json')
    base = prepared[parent]
    name = parent+'_it0'
    assert name not in prepared
    entry = dict(arm=copy.deepcopy(base['arm']), nop=copy.deepcopy(base['nop']), builds={}, parent=parent)
    for service, row in base['builds'].items():
        wanted = {x['site'] for x in row['selections'] if x['anchor'].startswith('worker:')}
        if not wanted:
            continue
        b.space(root)
        source = Path(row['binary'])
        assert b.sha(source) == row['sha256']
        meta = load(Path(str(source)+'.json'))
        ranges = {(p['stub'], p['terminal_jumps'][0]) for p in meta['patches'] if p['site'] in wanted}
        other_ranges = {(p['stub'], p['terminal_jumps'][0]) for p in meta['patches'] if p['site'] not in wanted}
        assert not ranges & other_ranges, 'Do not change a shared stub used by a different phase'
        raw = bytearray(source.read_bytes())
        patches = []
        for hint in meta['hints']:
            if not any(lo <= hint['va'] < hi for lo, hi in ranges):
                continue
            old = bytes.fromhex(hint['original'])
            assert old[:3] == bytes.fromhex('0f1815') and len(old) == 7
            offset = hint['offset']
            assert raw[offset:offset+7] == old
            new = bytes.fromhex('0f183d')+old[3:]
            raw[offset:offset+7] = new
            patches.append(dict(va=hint['va'], offset=offset, old=old.hex(), new=new.hex(), target=hint['target']))
            hint.update(original=new.hex(), kind='it0')
        assert patches
        output = root / 'builds' / name / service / source.name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw);output.chmod(0o755)
        meta.update(sha256=b.sha(output), output=str(output),
            transform=dict(source=str(source), sha256=row['sha256'], patches=patches,
                rule='Change only added typed-async-worker T1 to IT0. Same addresses, displacement, branches, '
                     'registers and CFI; other new RPC hints and all old no-DSO hints stay T1.', source_sha256=b.sha(__file__)))
        b.save(Path(str(output)+'.json'), meta)
        entry['arm']['overrides'][service] = str(output)
        entry['builds'][service] = dict(row, binary=str(output), sha256=meta['sha256'],
                                      changed_to_it0=len(patches), nop=row['nop'])
    assert entry['builds']
    entry['arm']['controls'] = ['original', 'no_dso', 'full_dso', parent, name+'_nop']
    prepared[name] = entry
    b.save(root / 'prepared_candidates.json', prepared)
    arms = load(root / 'arms.json');arms[name] = entry['arm'];arms[name+'_nop'] = entry['nop']
    b.save(root / 'arms.json', arms)
    digest = b.sha(__file__)
    (root / 'source_versions' / (digest+'.py')).write_bytes(Path(__file__).read_bytes())
    b.save(root / (name+'_prepared.json'), dict(name=name, parent=parent,
        changed_hints=sum(v['changed_to_it0'] for v in entry['builds'].values()),
        rationale='Fresh async task knows its callback type after it is placed on a CPU; test L1-oriented '
                  'instruction hint only at that point. Empty fetch queue and accepted fill are hypotheses, not measured conditions.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--worker-it0', choices=['rpc_worker', 'rpc_staged'])
    args = parser.parse_args()
    worker_it0(args.root, args.worker_it0) if args.worker_it0 else prepare(args.root)
