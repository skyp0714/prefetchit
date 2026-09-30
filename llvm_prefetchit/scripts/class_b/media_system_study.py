#!/usr/bin/env python3
"""Joint Media application-server + MongoDB prefetch deployment study.

The nine application servers on compose-review's request path are independent
address spaces. Train each original executable separately; hold workload,
dependencies, RPCs and tracing fixed. Clean endpoint trials contain no profiler.
"""
import argparse
import collections
import gzip
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import time

import balanced_backend as balanced
import backend_study
import dense_build as b
import fullset as h
from backend_prefetch import audit_backends, bind_mongodb, observed_rows
from call_cost_selector import select
from callpath_prefetch import coverage, stubs
from dense_cause_analysis import Code, HEADER, category, mapping_bias
from dense_causes import decode
from e2e_lbr import remove_generated
from fullset_study import summarize
from lean_timeline import request_window
from split_coverage_campaign import trial_orders

NATIVE = dict(h.TARGETS['media'],
    unique=('unique-id-service', 'UniqueIdService', '32-39'),
    text=('text-service', 'TextService', '32-39'),
    user=('user-service', 'UserService', '32-39'),
    storage=('review-storage-service', 'ReviewStorageService', '32-39'),
    userreview=('user-review-service', 'UserReviewService', '32-39'),
    moviereview=('movie-review-service', 'MovieReviewService', '32-39'))
MONGO = {k:v for k,v in backend_study.MONITORED.items() if k.startswith('mongo_')}
MONITORED = dict({k:v[0] for k,v in NATIVE.items()}, **MONGO, nginx='nginx-web-server')
MISS_EVENT = 'cpu/event=0xc6,umask=0x3,config1=0x13,period=257,name=fe_l2/upp'
CALL_EVENT = 'cpu/event=0xc4,umask=0x2,period=4093,name=near_calls/upp'
LIMIT = ('Native policies cover each main ELF, including statically linked library code, '
    'but not unmodified shared DSOs, Nginx, Redis, Memcached, Jaeger or kernel instructions. '
    'LBR placement uses observed earlier direct calls, not whole-program dominators. '
    'Sample coverage and retired-cycle lead are not accepted fills or fetch deadlines. '
    'Separate kernel PMU includes scheduler/interrupt work and is not a request critical-path decomposition.')


def configure():
    h.TARGETS['media'] = NATIVE
    h.media.TARGETS = NATIVE
    backend_study.MONITORED = MONITORED


def initialize(root):
    root.mkdir(parents=True, exist_ok=False); b.space(root)
    prior = json.loads(Path('/storage/prefetchit/class_b_split_hybrid_20260929/latency_screen/protocol.json').read_text())
    refs = dict(prior['arms']['original']['overrides'])
    for key, (_, exe, _) in NATIVE.items():
        if key not in refs: refs[key] = str(h.media.OLD/'support'/exe)
    mongo = prior['arms']['split75']['mongo_binary']
    original = prior['arms']['original']['mongo_binary']
    for path in [*refs.values(), mongo, original]:
        assert Path(path).is_file() and not str(Path(path).resolve()).startswith('/fast-lab-share/')
    settings = dict(references=refs, mongo_original=original, mongo_split75=mongo,
        hashes={p:b.sha(p) for p in [*refs.values(),mongo,original]}, native=NATIVE,
        workload='Full Media compose-review, C4 balanced persistent HTTP connections, 8 CPUs 32-39, 2GHz, tracing unchanged at 100%.',
        training='Fresh original stack for train and heldout; near-call frequency only from train. 12s per service/event, miss period 257; call period 4093.',
        policy='Train-only cost-weighted direct-call placements, <=128 sites/512 hints/service, <=4 hints/site, >=8 observations, 65% main-image miss-cover goal, lead 64..8192 retired cycles. Fixed before timing.',
        comparison='Four fresh seed blocks: original, MongoDB-only split75, split75 + native NOP stubs, split75 + native T1. Clean 50s warmup + 60s ROI; no PMU during endpoint trials. Separate diagnostics after complete timing.',
        limitation=LIMIT, source_sha256=b.sha(__file__))
    b.save(root/'settings.json', settings)
    b.save(root/'space_budget.json', dict(root_free=__import__('shutil').disk_usage('/').free,
        storage_free=__import__('shutil').disk_usage(root).free, expected_local_generated_bytes=3*2**30,
        logs='Existing stack caps container logs to two 2MiB files; fresh anonymous DB volumes removed after each run.'))
    return settings


def verify(root):
    settings=json.loads((root/'settings.json').read_text())
    assert all(b.sha(p)==digest for p,digest in settings['hashes'].items())
    return settings


def audit_native(stack, out, overrides):
    identities={}
    for key,(name,exe,_) in NATIVE.items():
        pid=stack.states[name]['State']['Pid']; expected=Path(overrides[key])
        assert b.sha(f'/proc/{pid}/exe')==b.sha(expected), (name,expected)
        identities[key]=dict(service=name,exe=exe,pid=pid,binary=str(expected),sha256=b.sha(expected))
    b.save(out/'native_runtime.json', identities)
    return identities


def audited_start(spec=None):
    """Verify all nine actually mapped executables before warmup/timing."""
    original=h.start
    def start(out,family,overrides,pool,alone=False):
        stack=original(out,family,overrides,pool,alone)
        try:
            audit_native(stack,out,overrides)
            if spec and spec.get('libraries'):
                from media_library_study import audit_libraries
                audit_libraries(stack,out,spec)
        except BaseException:
            stack.close();raise
        return stack
    h.start=start


def capture(spec):
    configure(); root=Path(spec['root']); settings=verify(root)
    phase=spec['phase']; out=root/'profiles'/phase; out.mkdir(parents=True,exist_ok=False); b.space(out)
    kinds=['miss','calls'] if phase=='train' else ['miss']
    b.save(out/'protocol.json', dict(spec, settings=settings, kinds=kinds, events=dict(miss=MISS_EVENT,calls=CALL_EVENT)))
    stack=client=None; captures=[]; windows={}
    try:
        with bind_mongodb(out,settings['mongo_original']):stack=h.start(out,'media',settings['references'],8)
        audit_backends(stack,out,settings['mongo_original']); runtime=audit_native(stack,out,settings['references'])
        seconds=70+len(NATIVE)*len(kinds)*14
        client=balanced.start_client(out,seconds,spec['seed']);time.sleep(50)
        for kind in kinds:
            for key,(name,exe,_) in NATIVE.items():
                b.space(out);dest=out/key/kind;dest.mkdir(parents=True)
                pid=runtime[key]['pid'];(dest/'maps.txt').write_text(Path(f'/proc/{pid}/maps').read_text())
                b.save(dest/'identity.json',runtime[key])
                group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                command=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M',
                    '-e',MISS_EVENT if kind=='miss' else CALL_EVENT,'-j','any,u','-G',group,
                    '-o',dest/'perf.data','--','sleep','12']
                start=time.time();b.run(command,dest/'record.log');windows[str(dest)]=(start,time.time())
                assert not re.search(r'\b(lost|truncated|throttled)\b',(dest/'record.log').read_text(),re.I)
                assert client.poll() is None;captures.append(dest)
                print(json.dumps(dict(stage='captured',phase=phase,service=key,kind=kind)),flush=True)
        assert client.wait(timeout=seconds+60)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text());assert not info['steady_errors'] and info['mapping_preserved']
        b.save(out/'load_validation.json',dict(valid=True,load=info))
        with gzip.open(out/'load/requests.json.gz','rt') as stream:samples=json.load(stream)
        for dest in captures:b.save(dest/'request_window.json',request_window(samples,*windows[str(dest)]))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)
        if (out/'failure.json').exists():
            unused=list(out.glob('*/*/perf.data'))
            if unused:remove_generated(unused,out/'failure_cleanup.json','Rejected capture; commands, identities, failure and settings retained.')
    for dest in captures:decode(dest)
    b.save(out/'complete.json',dict(valid=True,captures=list(map(str,captures))))


def frequencies(folder, code, main):
    bias=mapping_bias((folder/'maps.txt').read_text(),re.compile(r'(?:^|/)'+re.escape(Path(main).name)+r'$'),code.sections)
    assert bias is not None
    counts=collections.Counter();ips=collections.Counter();dsos=collections.Counter()
    for line in (folder/'samples.txt').open():
        match=HEADER.match(line)
        if not match:continue
        counts['all_samples']+=1;dsos[match[3]]+=1
        if match[3][1:-1] not in (main,Path(main).name):continue
        ip=int(match[2],16)-bias;counts['main_samples']+=1;ips[ip]+=1
        counts[category(code.get(ip)[1])]+=1
    assert counts['all_samples']==json.loads((folder/'record_types.json').read_text())['SAMPLE']
    calls=counts['direct_call']+counts['indirect_call']
    assert counts['main_samples']>100 and calls/counts['main_samples']>=.99,counts
    requests=json.loads((folder/'request_window.json').read_text())['completed_requests'];assert requests>0
    rates={ip:n*4093/requests for ip,n in ips.items() if category(code.get(ip)[1])=='direct_call'}
    result=dict(counts=dict(counts),dsos=dict(dsos),histogram=dict(ips),rates=rates,
        period=4093,requests=requests,floor=3*4093/requests,decoded_sha256=b.sha(folder/'samples.txt'))
    b.save(folder/'frequency.json',result)
    return rates,result['floor']


def prepare(root):
    settings=verify(root); candidates={};summary={}
    for phase in ['train','heldout']:assert json.loads((root/'profiles'/phase/'complete.json').read_text())['valid']
    for key,(_,exe,_) in NATIVE.items():
        b.space(root);reference=Path(settings['references'][key]);code=Code(reference)
        raw=reference.read_bytes();elf=stubs.Elf(raw);calls={};main='/custom/'+exe
        for site,(length,asm,_) in code.instructions.items():
            if length!=5 or category(asm)!='direct_call':continue
            offset=elf.offset(site,5,True)
            if raw[offset]!=0xe8:continue
            callee=site+5+struct.unpack_from('<i',raw,offset+1)[0]
            if callee in code.instructions:calls[site]=dict(site=site,callee=callee,expected=raw[offset:offset+5].hex())
        phases={};quality={};cleanup=[]
        for phase in ['train','heldout']:
            folder=root/'profiles'/phase/key/'miss'
            rows,counts=observed_rows(folder,code,calls,main=main)
            expected=json.loads((folder/'record_types.json').read_text())['SAMPLE']
            assert counts['all_samples']==expected and counts['main_samples']>100,(key,phase,counts)
            requests=json.loads((folder/'request_window.json').read_text())['completed_requests']
            for row in rows:row['miss_weight']=257/requests
            phases[phase]=rows;quality[phase]=dict(counts,requests=requests,decoded_sha256=b.sha(folder/'samples.txt'))
            dest=root/'observations'/key/(phase+'.json.gz');dest.parent.mkdir(parents=True,exist_ok=True)
            with gzip.open(dest,'wt') as stream:json.dump(rows,stream,separators=(',',':'))
            cleanup.append(folder/'samples.txt')
        folder=root/'profiles/train'/key/'calls';frequency,floor=frequencies(folder,code,main);cleanup.append(folder/'samples.txt')
        chosen=select(phases['train'],frequency,floor,max_sites=128,max_hints=512,goal=.65)
        chosen['heldout']=coverage(phases['heldout'],chosen['choices']);chosen['quality']=quality
        b.save(root/'plans'/key/'selection.json',chosen)
        assert chosen['sites']>0,(key,'No eligible direct-call placements')
        grouped=collections.defaultdict(list)
        for row in chosen['choices']:grouped[row['site']].append(row['target'])
        plan=dict(sha256=b.sha(reference),calls=[dict(calls[s],targets=targets) for s,targets in sorted(grouped.items())])
        b.save(root/'plans'/key/'plan.json',plan)
        output=root/'builds'/key/exe
        try:
            record=stubs.build(reference,plan,output,boundaries=code.instructions)
            del code
            check=Code(output);assert all(check.raw_targets[x['va']]==x['target'] for x in record['hints']);del check
        except BaseException as error:
            b.save(root/'plans'/key/'failure.json',dict(error=repr(error)))
            unused=[p for p in [output,Path(str(output)+'.nop')] if p.exists()]
            if unused:remove_generated(unused,root/'plans'/key/'failed_build_cleanup.json','Failed candidate build; source, plan, command and error retained.')
            raise
        candidates[key]=dict(binary=str(output),nop=str(output)+'.nop',sha256=record['sha256'],nop_sha256=record['nop_sha256'])
        summary[key]=dict(sites=chosen['sites'],hints=chosen['hints'],
            train_coverage=chosen['covered']/chosen['samples'],heldout_coverage=chosen['heldout']['covered']/chosen['heldout']['samples'],
            main_sample_fraction=quality['train']['main_samples']/quality['train']['all_samples'],
            estimated_hints_per_request=chosen['estimated_hint_executions_per_request'],
            extra_instruction_bytes=record['extra_instruction_bytes'])
        b.save(root/'prepared_pending.json',dict(candidates=candidates,summary=summary))
        remove_generated(cleanup,root/'plans'/key/'decoded_cleanup.json','Selection, all observations, frequency histogram, trace hashes and quality retained; decoded copies no longer needed.')
        print(json.dumps(dict(stage='prepared',service=key,**summary[key])),flush=True)
    base=dict(overrides=settings['references'],mongo_binary=settings['mongo_original'])
    arms=dict(original=base,mongo=dict(base,mongo_binary=settings['mongo_split75'],controls=['original']),
        combined_nop=dict(overrides={k:v['nop'] for k,v in candidates.items()},mongo_binary=settings['mongo_split75'],controls=['mongo']),
        combined=dict(overrides={k:v['binary'] for k,v in candidates.items()},mongo_binary=settings['mongo_split75'],controls=['original','mongo','combined_nop']))
    b.save(root/'prepared.json',dict(candidates=candidates,summary=summary,arms=arms,limitation=LIMIT))


def trial(spec):
    configure();audited_start(spec)
    from media_library_study import bind_libraries
    with bind_libraries(Path(spec['out']),spec):
        if spec.get('diagnostic'):
            import split_hybrid_study as diagnostic
            diagnostic.MONITORED=MONITORED
            diagnostic.EVENTS={k:v for k,v in diagnostic.EVENTS.items() if k in ['cache','topdown','front','memory']}
            diagnostic.trial(spec)
        else:
            backend_study.EVENTS={}
            balanced.trial(spec)


def campaign(root):
    settings=verify(root);prepared=json.loads((root/'prepared.json').read_text());arms=prepared['arms']
    for value in prepared['candidates'].values():
        assert b.sha(value['binary'])==value['sha256'] and b.sha(value['nop'])==value['nop_sha256']
    screen=root/'screen';screen.mkdir(exist_ok=False);orders=trial_orders(list(arms),4)
    b.save(screen/'protocol.json',dict(arms=arms,blocks=4,orders=orders,seedbase=930101,
        monitored=MONITORED,source_sha256=b.sha(__file__),settings=settings,limitation=LIMIT))
    rows=[]
    for block,order in enumerate(orders):
        for arm in order:
            b.space(root);out=screen/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(arms[arm],out=str(out),seed=930101+block))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            r=json.loads((out/'result.json').read_text());assert r['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=r['pool']['achieved_rps'],
                pool_util_pct=r['pool_util_pct'],metrics=dict(mean_ms=r['pool']['mean_ms'],p99_ms=r['pool']['p99_ms'],
                stack_cpu=r['whole_stack_cpu_us_per_request'],inverse_rps=1/r['pool']['achieved_rps']))
            rows.append(row);b.save(screen/'rows.json',rows);b.save(screen/'summary.json',summarize(rows,arms))
            print(json.dumps(dict(stage='trial_complete',**row)),flush=True)
    b.save(screen/'complete.json',dict(valid=True,trials=len(rows)))
    from mechanism_report import evaluate
    evaluate(screen,root/'screen_evaluation.json')


def diagnostics(root):
    prepared=json.loads((root/'prepared.json').read_text())
    for block,order in enumerate([['original','mongo','combined'],['combined','mongo','original']]):
        for arm in order:
            b.space(root);out=root/'diagnostics'/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(prepared['arms'][arm],out=str(out),seed=931101+block,diagnostic=True,reverse_pmu=bool(block)))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            print(json.dumps(dict(stage='diagnostic_complete',arm=arm,block=block)),flush=True)
    b.save(root/'diagnostics/complete.json',dict(valid=True,runs=6))


def run(root):
    initialize(root)
    from call_frequency import preflight
    preflight(root/'call_ip_preflight')
    for phase,seed in [('train',929101),('heldout',929102)]:
        manifest=root/(phase+'_spec.json');b.save(manifest,dict(root=str(root),phase=phase,seed=seed))
        h.platform(root/phase,['python3',Path(__file__),'capture',manifest])
    prepare(root)
    # Exercise all nine PF binaries through initialization and live HTTP requests
    # before admitting any candidate to clean performance measurement.
    prepared=json.loads((root/'prepared.json').read_text())
    smoke=root/'smoke';manifest=root/'smoke_spec.json'
    b.save(manifest,dict(prepared['arms']['combined'],out=str(smoke),seed=930001))
    h.platform(smoke,['python3',Path(__file__),'smoke',manifest])
    campaign(root);diagnostics(root)
    b.save(root/'complete.json',dict(valid=True,clean_trials=16,diagnostic_runs=6))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','capture','prepare','trial','smoke','campaign','diagnostics'])
    parser.add_argument('path',type=Path);args=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    configure()
    if args.action in ['capture','trial','smoke']:
        spec=json.loads(args.path.read_text())
        if args.action=='smoke':
            from media_library_study import bind_libraries
            audited_start(spec)
            with bind_libraries(Path(spec['out']),spec):balanced.smoke(spec)
        else:globals()[args.action](spec)
    else:globals()[args.action](args.path)
