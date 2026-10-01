#!/usr/bin/env python3
"""Separate kernel/user instruction-supply diagnosis on Media's CPU pool.

Sampling is outside all endpoint performance trials. Function histograms keep
actual sampled symbols, not a speculative causal attribution to syscall edges.
"""
import argparse
import collections
import gzip
import json
from pathlib import Path
import re
import signal
import subprocess
import time

import dense_build as b
import fullset as h
import balanced_backend as balanced
from backend_prefetch import bind_mongodb, audit_backends
from dense_causes import counters
from e2e_lbr import remove_generated
from media_system_study import configure, audit_native
from media_library_study import bind_libraries, audit_libraries
from split_hybrid_study import pool_window

CACHE='cycles:u,instructions:u,cpu/event=0x24,umask=0x24,name=L2I/u,cpu/event=0x24,umask=0xe4,name=L2_CODE_ALL/u,cpu/event=0xc6,umask=0x3,config1=0x13,name=FE_L2/u,cpu/event=0x80,umask=0x4,name=ICACHE_STALL/u'
L1='cycles:u,instructions:u,cpu/event=0xc6,umask=0x3,config1=0x12,name=FE_L1I/u,cpu/event=0x80,umask=0x4,cmask=1,edge=1,name=ICACHE_PERIODS/u,cpu/event=0x11,umask=0x10,cmask=1,name=ITLB_WALK_ACTIVE/u,cpu/event=0x80,umask=0x4,name=ICACHE_STALL/u'
SAMPLES=dict(cycles=('cycles:k',1000003),l2=('cpu/event=0xc6,umask=0x3,config1=0x13,name=kernel_l2/kpp',1021))


def decode_symbols(dest):
    types=collections.Counter()
    with (dest/'quality.log').open('w') as err:
        proc=subprocess.Popen(['perf','script','-D','-i',str(dest/'perf.data')],stdout=subprocess.PIPE,stderr=err,text=True)
        for line in proc.stdout:
            match=re.search(r'PERF_RECORD_(\w+)',line)
            if match:types[match[1]]+=1
        assert proc.wait()==0
    b.save(dest/'record_types.json',dict(types))
    command=['perf','script','-i',str(dest/'perf.data'),'-F','ip,sym,dso'];b.save(dest/'decode_command.json',command)
    histogram=collections.Counter();ips=collections.Counter();unparsed=[]
    with (dest/'decode.log').open('w') as err:
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=err,text=True)
        for line in proc.stdout:
            if not line.strip():continue
            match=re.match(r'^\s*([0-9a-f]+)\s+(.+?)\s+\((.*)\)\s*$',line)
            if match:
                histogram[(match[2],match[3])]+=1
                ips[(match[1],match[2],match[3])]+=1
            else:unparsed.append(line.rstrip())
        assert proc.wait()==0
    result=dict(samples=sum(histogram.values()),record_samples=types['SAMPLE'],unparsed=unparsed[:50],
        histogram=[dict(symbol=s,dso=d,samples=n) for (s,d),n in histogram.most_common()],
        instruction_histogram=[dict(ip=ip,symbol=s,dso=d,samples=n) for (ip,s,d),n in ips.most_common()],
        raw_sha256=b.sha(dest/'perf.data'),scope='CPU pool kernel-only samples; associations, not exclusive syscall or cache-stall causal costs.')
    b.save(dest/'symbols.json',result)
    assert not any(types[k] for k in ['LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'])
    assert result['samples']==types['SAMPLE'] and not unparsed and result['samples']>100
    remove_generated([dest/'perf.data'],dest/'raw_cleanup.json','Full symbol histogram, sample-quality records, source/commands/hash retained.')


def trial(spec):
    configure();out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),cache=CACHE,l1=L1,samples=SAMPLES,
        perf_max_sample_rate=Path('/proc/sys/kernel/perf_event_max_sample_rate').read_text().strip(),
        scope='Full Media C4, separate diagnostic only; CPU pool 32-39. User and kernel PMU windows are sequential, each with its own request count.'))
    stack=client=None;windows=[];captures=[]
    try:
        with bind_libraries(out,spec),bind_mongodb(out,spec['mongo_binary']):stack=h.start(out,'media',spec['overrides'],8)
        audit_native(stack,out,spec['overrides']);audit_backends(stack,out,spec['mongo_binary']);audit_libraries(stack,out,spec)
        client=balanced.start_client(out,125,spec['seed']);time.sleep(50)
        for privilege in ['u','k']:
            for label,event in [('cache',CACHE),('l1',L1)]:
                stem=out/(privilege+'_'+label);events=event.replace(':u',':'+privilege).replace('/u','/'+privilege)
                a=h.old.pool_cpu(set(range(32,40)))
                b.run(['perf','stat','-x,','-o',str(stem)+'.csv','-e',events,'-a','-C','32-39','--','sleep','5'],Path(str(stem)+'.log'))
                z=h.old.pool_cpu(set(range(32,40)));row=counters(Path(str(stem)+'.csv'),privilege=privilege)
                assert row['fully_scheduled']
                windows.append(dict(privilege=privilege,label=label,**row,window=pool_window(a,z)))
                b.save(out/'windows_pending.json',windows)
        for label,(event,period) in SAMPLES.items():
            b.space(out);dest=out/label;dest.mkdir()
            command=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M','-e',event,
                '-c',str(period),'-o',dest/'perf.data','--','sleep','10']
            a=time.time();b.run(command,dest/'record.log');z=time.time();captures.append(dest)
            b.save(dest/'window.json',dict(start=a,end=z,event=event,period=period))
            assert not re.search(r'\b(lost|truncated|throttled)\b',(dest/'record.log').read_text(),re.I)
        assert client.wait(timeout=180)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text());assert not info['steady_errors'] and info['mapping_preserved']
        with gzip.open(out/'load/requests.json.gz','rt') as stream:samples=json.load(stream)
        for row in windows:
            h.old.attach(row['window'],samples)
            row['per_request']={k:v/row['window']['completed'] for k,v in row['counters'].items()}
        b.save(out/'result.json',dict(valid=True,windows=windows,load=info))
        # Read existing tracing only after load and every PMU recorder stop.
        from request_path_trace import collect
        collect(stack,out,info)
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)
        if (out/'failure.json').exists():
            unused=list(out.glob('*/perf.data'))
            if unused:remove_generated(unused,out/'failure_cleanup.json','Failed diagnostic; failure, settings, source and hashes retained.')
    try:
        for dest in captures:decode_symbols(dest)
    except BaseException as error:
        b.save(out/'decode_failure.json',dict(error=repr(error)))
        unused=list(out.glob('*/perf.data'))
        if unused:remove_generated(unused,out/'decode_failure_cleanup.json','Rejected symbol decode; compact histogram, quality, error and hashes retained.')
        raise
    b.save(out/'complete.json',dict(valid=True))


def run(root):
    prepared=json.loads((root/'prepared.json').read_text())
    for arm in ['original','combined']:
        out=root/'boundaries'/arm;manifest=out.with_suffix('.json')
        b.save(manifest,dict(prepared['arms'][arm],out=str(out),seed=932101))
        h.platform(out,['python3',Path(__file__),'trial',manifest])
    b.save(root/'boundaries/complete.json',dict(valid=True,runs=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','trial']);p.add_argument('path',type=Path);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if a.action=='trial':trial(json.loads(a.path.read_text()))
    else:run(a.path)
