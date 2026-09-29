#!/usr/bin/env python3
"""Diagnose translation, DSB and ANT events after frozen call-path timing."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import time
import dense_build as b
import fullset as h
from backend_prefetch import bind_mongodb,audit_backends,start_client
from dense_causes import counters
from fullset_study import summarize

EVENTS={
    'ant':'cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_ANY_ANT,config1=0x9/u,cpu/event=0xc6,umask=0x2,name=FE_MISP_ANT,config1=0x9/u,branches:u,branch-misses:u',
    'itlb':'cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_ITLB,config1=0x14/u,cpu/event=0x11,umask=0x10,name=ITLB_WALK_ACTIVE,cmask=1/u,cpu/event=0x80,umask=0x4,name=ICACHE_DATA_STALL/u',
    'dsb':'cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,name=FE_CRITICAL_DSB,config1=0x11/u,cpu/event=0x79,umask=0x8,name=DSB_UOPS/u,cpu/event=0x79,umask=0x4,name=MITE_UOPS/u,cpu/event=0xad,umask=0x40,name=UNKNOWN_BRANCH_CYCLES,config1=0x7/u'}
SCOPES={'mongo_user':('user-review-mongodb','u'),
        'mongo_movie':('movie-review-mongodb','u'),
        'mongo_storage':('review-storage-mongodb','u'),
        'pool_user':(None,'u'),'pool_kernel':(None,'k')}
LIMIT=('Separate request-normalized diagnostic windows, not E2E timing or an exclusive cause partition. '
       'ANY_ANT and MISP_ANT describe particular conditional-branch conditions, not all BTB misses. '
       'Do not divide MISP_ANT by ANY_ANT as a misprediction probability: the published ANY_ANT definition excludes mispredicted branches. '
       'CPU-pool and service scopes overlap. Critical DSB and ITLB events can overlap cache/branch costs. '
       'The cost75 candidate is fixed independently of performance outcomes.')


def events(label,privilege):
    return EVENTS[label].replace(':u',':'+privilege).replace('/u','/'+privilege)


def trial(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(spec,events=EVENTS,scopes=SCOPES,
        source_sha256=b.sha(__file__),limitation=LIMIT))
    stack=client=None;windows=[]
    try:
        with bind_mongodb(out,spec['mongo_binary']):stack=h.start(out,'media',spec['overrides'],8)
        audit_backends(stack,out,spec['mongo_binary'])
        order=[(label,scope) for label in EVENTS for scope in SCOPES]
        if spec['reverse']:order.reverse()
        client=start_client(out,70+len(order)*5,spec['seed']);time.sleep(50)
        for label,scope in order:
            b.space(out);name,privilege=SCOPES[scope]
            command=['perf','stat','-x,','-e',events(label,privilege),'-a','-C','32-39']
            if name:
                pid=stack.states[name]['State']['Pid']
                group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                command+=['-G',group]
            stem=out/(label+'_'+scope)
            command+=['-o',str(stem)+'.csv','--','sleep','4']
            before=h.old.pool_cpu(set(range(32,40)))
            b.run(command,Path(str(stem)+'.log'))
            after=h.old.pool_cpu(set(range(32,40)))
            row=counters(Path(str(stem)+'.csv'),privilege=privilege)
            assert row['fully_scheduled'] and client.poll() is None
            windows.append(dict(scope=scope,label=label,privilege=privilege,**row,
                window=dict(start=before['epoch'],end=after['epoch'],
                    wall_s=after['monotonic']-before['monotonic'],
                    cpu_us=sum(after['ticks'][k]-v for k,v in before['ticks'].items())*1e6/before['clock_ticks'])))
            b.save(out/'windows_pending.json',windows)
        assert client.wait(timeout=200)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text())
        assert not info['steady_errors'] and info['client_cpu_cores']<.8
        with gzip.open(out/'load/requests.json.gz','rt') as stream:requests=json.load(stream)
        for row in windows:
            h.old.attach(row['window'],requests);assert row['window']['completed']>0
            row['per_request']={k:v/row['window']['completed'] for k,v in row['counters'].items()}
        b.save(out/'result.json',dict(valid=True,windows=windows,load=info,limitation=LIMIT))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)


def campaign(parent):
    source=parent/'callpath_coverage75';assert (source/'complete.json').exists()
    root=parent/'callpath_frontend';root.mkdir(exist_ok=False);b.space(root)
    prepared=json.loads((source/'prepared.json').read_text());candidate=prepared['candidates']['cost75']
    patch=json.loads(Path(candidate['binary']+'.json').read_text())
    assert b.sha(candidate['binary'])==patch['sha256'] and b.sha(candidate['nop'])==patch['nop_sha256']
    base=json.loads((source/'screen_spec.json').read_text())['arms']['original']['overrides']
    arms={'original':dict(mongo_binary=prepared['reference']),
          'cost75_nop':dict(mongo_binary=candidate['nop'],controls=['original']),
          'cost75':dict(mongo_binary=candidate['binary'],controls=['original','cost75_nop'])}
    b.save(root/'protocol.json',dict(arms=arms,blocks=2,seedbase=83001,events=EVENTS,scopes=SCOPES,
        source_sha256=b.sha(__file__),event_source='https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/',
        ordering='Fresh stack for each arm. Reverse arm and window order in the second block. Start diagnostics after 50 seconds.',
        limitation=LIMIT))
    # No event configuration is added to the active clean E2E campaign.
    for privilege in ['u','k']:
        for label in EVENTS:
            stem=root/('preflight_'+privilege+'_'+label)
            b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',events(label,privilege),
                   '-a','-C','84','--','sleep','.2'],Path(str(stem)+'.log'))
            assert counters(Path(str(stem)+'.csv'),privilege=privilege)['fully_scheduled']
    rows=[];names=list(arms)
    for block in range(2):
        for arm in names if block==0 else list(reversed(names)):
            out=root/f'{block:02d}_{arm}';manifest=out.with_suffix('.json')
            b.save(manifest,dict(out=str(out),mongo_binary=arms[arm]['mongo_binary'],
                overrides=base,seed=83001+block,reverse=bool(block)))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            result=json.loads((out/'result.json').read_text());assert result['valid']
            metrics={row['scope']+':'+row['label']+':'+key:value
                     for row in result['windows'] for key,value in row['per_request'].items()}
            rows.append(dict(block=block,arm=arm,valid=True,metrics=metrics,output=str(out)))
            b.save(root/'rows.json',rows)
            print(json.dumps(dict(block=block,arm=arm,windows=len(result['windows']),valid=True)),flush=True)
    b.save(root/'complete.json',dict(valid=True,trials=len(rows),windows=len(rows)*len(SCOPES)*len(EVENTS),
        comparisons=summarize(rows,arms),limitation=LIMIT))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['trial','campaign']);p.add_argument('path',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    (trial(json.loads(a.path.read_text())) if a.action=='trial' else campaign(a.path))
