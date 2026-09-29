#!/usr/bin/env python3
"""Independent confirmation with controlled persistent-connection ownership."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import time
import backend_study
import dense_build as b
import fullset as h
from backend_prefetch import bind_mongodb,audit_backends
from fullset_study import summarize
from mechanism_report import evaluate
from privilege_frontend import DECODE_EVENTS


def start_client(out,seconds,seed,warmup=50):
    master=json.loads((out/'runtime.json').read_text())['nginx-web-server']['pid']
    load=out/'load';load.mkdir()
    command=['python3',Path(__file__).with_name('balanced_load.py'),'--out',load,
        '--seconds',str(seconds),'--seed',str(seed),'--nginx-pid',str(master),'--warmup',str(warmup)]
    b.save(load/'command.json',command)
    with (load/'client.log').open('w') as log:
        child=subprocess.Popen(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        for _ in range(300):
            if (load/'started.json').exists():
                assert json.loads((load/'connection_balance.json').read_text())['valid'];return child
            assert child.poll() is None,'Balanced client setup failed'
            time.sleep(.1)
        raise TimeoutError('Balanced client did not start within 30 seconds')
    except BaseException:h.c.stop(child);raise


def smoke(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out);stack=client=None
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),scope='Functional connection-assignment smoke only; no performance inference.'))
    try:
        with bind_mongodb(out,spec['mongo_binary']):stack=h.start(out,'media',spec['overrides'],8)
        audit_backends(stack,out,spec['mongo_binary'])
        client=start_client(out,12,spec['seed'],warmup=0)
        assert client.wait(timeout=60)==0;client=None;stack.check()
        result=json.loads((out/'load/load.json').read_text())
        assert result['mapping_preserved'] and result['completed']>100 and not result['errors']
        b.save(out/'result.json',dict(valid=True,load=result,balance=json.loads((out/'load/connection_balance.json').read_text())))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)


def trial(spec):
    # This override exists only in this dedicated child process. The original
    # campaign/client files and active unbalanced measurements are unchanged.
    backend_study.start_client=start_client
    spec=dict(spec,client_control='One persistent HTTP connection per Nginx worker, established before warmup. Any reconnect is an operating failure.',
        balanced_runner_sha256=b.sha(__file__),balanced_client_sha256=b.sha(Path(__file__).with_name('balanced_load.py')))
    backend_study.trial(spec)
    load=json.loads((Path(spec['out'])/'load/load.json').read_text());assert load['mapping_preserved']


def campaign(parent,blocks=4):
    assert blocks>=3
    source=parent/'callpath_coverage75'
    assert (source/'complete.json').exists() and (parent/'callpath_frontend/complete.json').exists()
    root=parent/'balanced_callpath';root.mkdir(exist_ok=False);b.space(root)
    prepared=json.loads((source/'prepared.json').read_text());candidate=prepared['candidates']['cost75']
    native=json.loads((parent/'confirmation_spec.json').read_text())['arms']
    base=native['base']['overrides'];nop=native['selected_nop']['overrides'];t1=native['candidate']['overrides']
    test_work=root/'opcode_test_work'
    from e2e_lbr import remove_generated
    try:
        b.run([b.REPO/'profiling/.venv/bin/python','-m','pytest','-q','--basetemp',test_work,
            b.REPO/'llvm_prefetchit/tests/test_callpath_instruction_hint.py'],root/'opcode_tests.log')
    finally:
        fixtures=[path for path in test_work.rglob('*') if path.is_file() and not path.is_symlink()]
        b.save(root/'opcode_fixture_sources.json',{str(path.relative_to(test_work)):path.read_text()
            for path in fixtures if path.suffix in ['.c','.s','.ld','.json']})
        remove_generated(fixtures,root/'opcode_test_cleanup.json','Native opcode validation attempt finished; retain outcome, source, commands, hashes and audit records before removing generated fixtures.')
    from callpath_instruction_hint import build as hint_variant
    it0=hint_variant(candidate['binary'],root/'builds/cost75_it0/mongod','it0')
    assert b.sha(candidate['nop'])==it0['nop_sha256']
    arms={
        'original':dict(overrides=base,mongo_binary=prepared['reference']),
        'cost75_nop':dict(overrides=base,mongo_binary=candidate['nop'],controls=['original']),
        'cost75':dict(overrides=base,mongo_binary=candidate['binary'],controls=['original','cost75_nop']),
        'cost75_it0':dict(overrides=base,mongo_binary=it0['binary'],controls=['original','cost75_nop','cost75']),
        'combined_nop':dict(overrides=nop,mongo_binary=candidate['nop'],controls=['original','cost75_nop']),
        'combined':dict(overrides=t1,mongo_binary=candidate['binary'],controls=['original','combined_nop','cost75'])}
    hashes={}
    for settings in arms.values():
        settings['extra_events']={'decode':DECODE_EVENTS}
        for path in [settings['mongo_binary'],*settings['overrides'].values()]:
            file=Path(path);assert file.is_file() and not file.is_symlink()
            hashes[path]=b.sha(file)
    b.save(root/'protocol.json',dict(blocks=blocks,arms=arms,seedbase=84001,hashes=hashes,
        source_sha256=b.sha(__file__),client_sha256=b.sha(Path(__file__).with_name('balanced_load.py')),
        rationale='A post-clean-ROI snapshot observed 3/1/0/0 persistent connections across four Nginx workers. Control this nuisance factor in a separate campaign, never exclude or pool the existing unbalanced trials.',
        policy='Freeze cost75 for its measured emission reduction with similar miss coverage. Compare a same-address IT0 opcode, and combine T1 with the existing native retarget T1. The single and combined layouts have matched NOP controls.',
        qualification='Functional full-stack smoke, four workers with one connection each, no reconnects, fresh stacks, 50s warmup, 60s clean ROI before PMU. No performance-based retries.',
        scope='Full Media compose-review C4 at eight workload CPUs; not a maximum-throughput sweep.'))
    manifest=root/'smoke_spec.json';b.save(manifest,dict(out=str(root/'smoke'),overrides=base,mongo_binary=prepared['reference'],seed=83901))
    h.platform(root/'smoke',['python3',Path(__file__),'smoke',manifest])
    screen=root/'screen';screen.mkdir()
    b.save(screen/'protocol.json',dict(arms=arms,blocks=blocks,seedbase=84001,monitored=backend_study.MONITORED,
        source_sha256=b.sha(__file__),client_sha256=b.sha(Path(__file__).with_name('balanced_load.py')),
        interpretation='Independent paired-log comparisons under controlled HTTP-to-worker assignment; never pool with unbalanced blocks.'))
    rows=[];names=list(arms)
    for block in range(blocks):
        for arm in names if block%2==0 else list(reversed(names)):
            b.space(root);out=screen/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=84001+block))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            result=json.loads((out/'result.json').read_text());assert result['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=result['pool']['achieved_rps'],
                pool_util_pct=result['pool_util_pct'],metrics=dict(mean_ms=result['pool']['mean_ms'],
                    p99_ms=result['pool']['p99_ms'],stack_cpu=result['whole_stack_cpu_us_per_request'],
                    inverse_rps=1/result['pool']['achieved_rps']))
            rows.append(row);b.save(screen/'rows.json',rows);b.save(screen/'summary.json',summarize(rows,arms))
            print(json.dumps(row),flush=True)
    b.save(screen/'complete.json',dict(rows=len(rows),summary=summarize(rows,arms)))
    evaluate(screen,root/'screen_evaluation.json')
    b.save(root/'complete.json',dict(clean_trials=len(rows),source_campaign=str(source),policies=['cost75','cost75_it0','combined']))
    b.run(['python3',Path(__file__).with_name('backend_summary.py'),root,'--plot'],root/'summary.log')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['campaign','trial','smoke']);p.add_argument('path',type=Path)
    p.add_argument('--blocks',type=int,default=4);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if a.action=='campaign':campaign(a.path,a.blocks)
    else:globals()[a.action](json.loads(a.path.read_text()))
