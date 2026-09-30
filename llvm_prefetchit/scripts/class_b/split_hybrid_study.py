#!/usr/bin/env python3
"""Fresh split75 hybrid E2E, followed by simultaneous top-down attribution."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import time
import backend_study
import balanced_backend
import dense_build as b
import fullset as h
import hybrid_campaign as hybrid
from backend_prefetch import bind_mongodb
from dense_causes import counters
from e2e_lbr import remove_generated
from fullset_study import summarize
from split_coverage_campaign import trial_orders
from split_hybrid_prepare import full, reduced

MONITORED = {k: v for k, v in backend_study.MONITORED.items() if k.startswith('mongo_')}
TD_NAMES = ['slots', 'topdown-retiring', 'topdown-bad-spec', 'topdown-fe-bound',
            'topdown-be-bound', 'topdown-fetch-lat', 'topdown-mem-bound']
EVENTS = dict(cache=backend_study.EVENTS['cache'],
    topdown='cycles:u,instructions:u,{'+','.join(name+':u' for name in TD_NAMES)+'}',
    memory='cycles:u,instructions:u,cpu/event=0xa3,umask=0x4,cmask=4,name=EXE_STALL/u,cpu/event=0x47,umask=0x3,cmask=3,name=LOAD_L1D_STALL/u,cpu/event=0x47,umask=0x9,cmask=9,name=LOAD_L3_STALL/u,cpu/event=0xa6,umask=0x40,cmask=2,name=STORE_STALL/u',
    front='cycles:u,instructions:u,cpu/event=0x79,umask=0x8,name=DSB_UOPS/u,cpu/event=0x79,umask=0x4,name=MITE_UOPS/u,cpu/event=0x11,umask=0x10,cmask=1,name=ITLB_WALK_ACTIVE/u,cpu/event=0xad,umask=0x40,config1=0x7,name=UNKNOWN_BRANCH_CYCLES/u',
    late=hybrid.LATE_EVENTS, prefetch=backend_study.EVENTS['prefetch'])
LIMIT = ('Top-down level-1 metrics share one slots-led hardware group. Ratios describe slots, not CPU-time fractions or request critical-path bounds. Fetch latency also includes branch/translation effects. Memory stall events overlap and must not be added. Pool user/kernel scopes overlap service attribution and include work outside the target MongoDBs. Raw metric fractions retain up to 2% closure error from 8-bit metric accounting; no normalization is applied. Post-ROI windows are independent of clean endpoint timing.')


def event_string(label, privilege='u'):
    return EVENTS[label].replace(':u', ':'+privilege).replace('/u', '/'+privilege)


def check_td(row, privilege='u'):
    c = row['counters']; slots = c['slots:'+privilege]; assert slots > 0
    get = lambda name: c['topdown-'+name+':'+privilege]
    total = sum(get(n) for n in ['retiring', 'bad-spec', 'fe-bound', 'be-bound'])
    # PERF_METRICS uses 8-bit fractions; kernel clamps negative deltas.
    # Preserve raw closure error; 2% is a diagnostic sanity limit, not precision.
    row['topdown_closure_error_pct'] = 100*(total/slots-1)
    assert abs(total/slots-1) < .02, (slots, total)
    assert get('fetch-lat') <= get('fe-bound')+.02*slots
    assert get('mem-bound') <= get('be-bound')+.02*slots


def preflight(root):
    out = root/'pmu_preflight'; out.mkdir(exist_ok=False); b.space(root)
    b.save(out/'protocol.json', dict(events=EVENTS, source_sha256=b.sha(__file__), limitation=LIMIT))
    for privilege in ['u', 'k']:
        for label in EVENTS if privilege == 'u' else ['topdown', 'memory']:
            stem = out/(privilege+'_'+label)
            b.run(['perf', 'stat', '-x,', '-o', str(stem)+'.csv', '-e', event_string(label, privilege),
                   '-a', '-C', '84', '--', 'taskset', '-c', '84', 'python3', '-c',
                   'import os; sum(i*i for i in range(1000000)); [os.stat("/proc/self/status") for _ in range(10000)]'],
                  Path(str(stem)+'.log'))
            row = counters(Path(str(stem)+'.csv'), privilege=privilege)
            assert row['fully_scheduled']
            if label == 'topdown': check_td(row, privilege)
            b.save(Path(str(stem)+'.json'), row)
    b.save(out/'complete.json', dict(valid=True, windows=8))


def pool_window(before, after):
    return dict(start=before['epoch'], end=after['epoch'], wall_s=after['monotonic']-before['monotonic'],
        cpu_us=sum(after['ticks'][k]-v for k, v in before['ticks'].items())*1e6/before['clock_ticks'])


def trial(spec):
    out = Path(spec['out']); out.mkdir(parents=True, exist_ok=False); b.space(out)
    b.save(out/'protocol.json', dict(spec, events=EVENTS, monitored=MONITORED,
        source_sha256=b.sha(__file__), limitation=LIMIT))
    stack = client = None; pmu = {}; pool_pmu = {}
    order = [(label, name, 'u') for label in EVENTS for name in MONITORED]
    order += [(label, None, privilege) for privilege in ['u', 'k'] for label in ['topdown', 'memory']]
    if spec.get('reverse_pmu'): order.reverse()
    with hybrid.environment(out, spec):
        try:
            with bind_mongodb(out, spec['mongo_binary']): stack = h.start(out, 'media', spec['overrides'], 8)
            hybrid.audit(stack, out, spec['mongo_binary'])
            seconds = 125+len(order)*4
            client = balanced_backend.start_client(out, seconds, spec['seed']); time.sleep(50)
            a = stack.accounts(); pb = h.old.pool_cpu(set(range(32, 40))); time.sleep(60)
            pa = h.old.pool_cpu(set(range(32, 40))); z = stack.accounts()
            for label, name, privilege in order:
                stem = out/(label+'_'+(name or 'pool_'+privilege))
                command = ['perf', 'stat', '-x,', '-o', str(stem)+'.csv', '-e', event_string(label, privilege), '-a', '-C', '32-39']
                if name:
                    pid = stack.states[MONITORED[name]]['State']['Pid']; before = h.c.cpu(pid)
                    command += ['-G', str(Path(before['path']).parent.relative_to('/sys/fs/cgroup'))]
                else: before = h.old.pool_cpu(set(range(32, 40)))
                b.run(command+['--', 'sleep', '3'], Path(str(stem)+'.log'))
                window = h.c.diff_cpu(before, h.c.cpu(pid)) if name else pool_window(before, h.old.pool_cpu(set(range(32, 40))))
                row = dict(**counters(Path(str(stem)+'.csv'), privilege=privilege), window=window)
                assert row['fully_scheduled'] and client.poll() is None
                if label == 'topdown': check_td(row, privilege)
                destination = pmu if name else pool_pmu
                destination.setdefault(label, {})[name or privilege] = row
                b.save(out/'pmu_pending.json', dict(services=pmu, pool=pool_pmu))
            assert client.wait(timeout=seconds+60) == 0; client = None; stack.check()
            info = json.loads((out/'load/load.json').read_text())
            with gzip.open(out/'load/requests.json.gz', 'rt') as stream: samples = json.load(stream)
            for groups in [pmu, pool_pmu]:
                for scopes in groups.values():
                    for row in scopes.values():
                        h.old.attach(row['window'], samples); assert row['window']['completed'] > 0
                        row['per_request'] = {k: v/row['window']['completed'] for k, v in row['counters'].items()}
            pool = h.old.attach(pool_window(pb, pa), samples)
            costs = {k: h.old.attach(h.c.diff_cpu(a[k], z[k]), samples) for k in a}
            errors = sum(pool['start'] <= t < pool['end'] for t in info['error_times'])
            result = dict(valid=not info['steady_errors'] and info['mapping_preserved'] and info['client_cpu_cores'] < .8,
                pmu={}, pmu_extra=pmu, pool_pmu=pool_pmu, pool=pool, load=info, roi_errors=errors,
                whole_stack_cpu_us_per_request=sum(v['cpu_us'] for v in costs.values())/pool['completed'],
                completed_before_roi=sum(finished < pool['start'] for _, finished in samples),
                pool_util_pct=100*pool['cpu_us']/pool['wall_s']/8e6, all_services=costs,
                services={k: costs[name] for k, name in MONITORED.items()})
            b.save(out/'result.json', result); assert result['valid'] and errors == 0
        except BaseException as error:
            b.save(out/'failure.json', dict(error=repr(error))); raise
        finally:
            h.c.stop(client)
            if stack is not None: stack.close()
            h.old.compact(out)


def prepare(parent, root):
    b.space(root); preflight(root)
    hybrid.tests(root)
    prepared = full(parent, root/'prepared')
    shim_record = json.loads((parent/'hybrid_mapping_debug/shim_build.json').read_text())
    shim = Path(shim_record['binary']); assert b.sha(shim) == shim_record['sha256']
    assert b.sha(b.REPO/'llvm_prefetchit/kernel/sched_clock/hybrid_map.c') == shim_record['source_sha256']
    overrides = json.loads((parent/'confirmation_spec.json').read_text())['arms']['base']['overrides']
    common = dict(overrides=overrides, hybrid=True, shim=str(shim), module=str(hybrid.MODULE))
    def diagnostic(binary, name, seed):
        out = root/name; manifest = root/(name+'_spec.json')
        b.save(manifest, dict(common, out=str(out), mongo_binary=binary, seed=seed))
        h.platform(out, ['python3', Path(hybrid.__file__).resolve(), 'diagnostic', manifest])
        result = out/'result.json'; assert json.loads(result.read_text())['valid']; return result
    full_result = diagnostic(prepared['diagnostic'], 'full_diagnostic', 87001)
    reduced_result = reduced(prepared, full_result, root/'sparse')
    sparse_result = diagnostic(reduced_result['sparse_diag']['binary'], 'sparse_diagnostic', 87002)
    remove_generated([Path(reduced_result['sparse_diag']['binary'])], root/'sparse_diagnostic_cleanup.json',
        'Independent gate/mapping verification complete. Keep measurements, source and hashes; instrumented ELF is excluded from E2E.')
    arms = dict(original=dict(mongo_binary=prepared['reference']),
        split75=dict(mongo_binary=prepared['base']['binary'], controls=['original']),
        early_t1=dict(mongo_binary=reduced_result['early_t1']['binary'], hybrid=True, controls=['original', 'split75']),
        early_it0=dict(mongo_binary=reduced_result['sparse']['binary'], hybrid=True, controls=['original', 'split75', 'early_t1']))
    for value in arms.values():
        value.update(overrides=overrides, shim=str(shim), module=str(hybrid.MODULE))
    paths = [Path(value['mongo_binary']) for value in arms.values()]
    inputs = [Path(__file__), Path(__file__).with_name('split_hybrid_prepare.py'),
        Path(hybrid.__file__), Path(balanced_backend.__file__), Path(backend_study.__file__),
        Path(__file__).with_name('hybrid_prepare.py'), b.REPO/'llvm_prefetchit/tools/call_stub_prefetch.py',
        b.REPO/'llvm_prefetchit/tools/hybrid_call_assembly.py',
        Path(__file__).with_name('balanced_load.py'), Path(__file__).with_name('dense_causes.py'),
        shim, hybrid.MODULE]
    record = dict(valid=True, arms=arms, binary_hashes={str(p): b.sha(p) for p in paths},
        source_hashes={str(p): b.sha(p) for p in inputs},
        full_diagnostic=str(full_result), sparse_diagnostic=str(sparse_result))
    b.save(root/'prepared_complete.json', record)


def campaign(root):
    prepared = json.loads((root/'prepared_complete.json').read_text()); assert prepared['valid']
    assert all(b.sha(p) == digest for p, digest in prepared['source_hashes'].items())
    assert all(b.sha(p) == digest for p, digest in prepared['binary_hashes'].items())
    stage = root/'hybrid_screen'; stage.mkdir(exist_ok=False); screen = stage/'screen'; screen.mkdir()
    arms = prepared['arms']; orders = trial_orders(list(arms), 4)
    protocol = dict(arms=arms, blocks=4, orders=orders, monitored=MONITORED, seedbase=87101,
        source_sha256=b.sha(__file__), prepared=prepared, limitation=LIMIT,
        scope='Fresh full Media compose-review C4 including MovieId. Eight workload CPUs; 50s warmup, 60s clean ROI, PMU only afterwards. No performance-based exclusions or retries.')
    b.save(stage/'protocol.json', protocol); b.save(screen/'protocol.json', protocol)
    rows = []
    for block, order in enumerate(orders):
        for arm in order:
            b.space(root); out = screen/f'{block:02d}_{arm}'; manifest = out.with_suffix('.json')
            b.save(manifest, dict(arms[arm], out=str(out), seed=87101+block, reverse_pmu=bool(block%2)))
            h.platform(out, ['python3', Path(__file__), 'trial', manifest])
            result = json.loads((out/'result.json').read_text()); assert result['valid']
            row = dict(block=block, arm=arm, valid=True, output=str(out), achieved_rps=result['pool']['achieved_rps'],
                pool_util_pct=result['pool_util_pct'], metrics=dict(mean_ms=result['pool']['mean_ms'],
                p99_ms=result['pool']['p99_ms'], stack_cpu=result['whole_stack_cpu_us_per_request'],
                inverse_rps=1/result['pool']['achieved_rps']))
            rows.append(row); b.save(screen/'rows.json', rows); b.save(screen/'summary.json', summarize(rows, arms))
            print(json.dumps(row), flush=True)
    b.save(screen/'complete.json', dict(rows=len(rows)))
    from split_coverage_campaign import report
    report(stage)
    (stage/'report.md').write_text((stage/'report.md').read_text().replace('Continuation-aware placement: fresh full Media C4',
        'Split75 plus early IT0: fresh full Media C4').replace('PMU windows follow the clean ROI and cover three MongoDBs only;', 'Cache/prefetch PMU windows follow the clean ROI and cover three MongoDBs; separate top-down/memory windows additionally cover pool user and kernel execution;'))
    b.save(stage/'complete.json', dict(valid=True, clean_trials=len(rows)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare', 'campaign', 'trial'])
    parser.add_argument('path', type=Path); parser.add_argument('--parent', type=Path)
    args = parser.parse_args()
    def interrupted(sig, frame): raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM, interrupted)
    if args.action == 'prepare': prepare(args.parent, args.path)
    elif args.action == 'trial': trial(json.loads(args.path.read_text()))
    else: campaign(args.path)
