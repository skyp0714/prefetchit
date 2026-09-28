#!/usr/bin/env python3
"""Schedule-age miss diagnostics for frozen Media candidates, outside E2E timing."""
import argparse
from bisect import bisect_right
from collections import Counter
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time

import dense_build as b
import lean_plan

EDGES = [0,1,2,5,8,10,15,20,22,24,30,40,50,100,200,500,1000]


def executable_maps(binary, text):
    """Translate runtime IPs using PT_LOAD file offsets, including non-PIE ELF."""
    data=Path(binary).read_bytes()
    assert data[:6]==b'\x7fELF\x02\x01'
    phoff=struct.unpack_from('<Q',data,32)[0]
    entsize,count=struct.unpack_from('<HH',data,54)
    assert entsize==56
    loads=[]
    for i in range(count):
        kind,flags,offset,va,_,filesize,memsize,_=struct.unpack_from('<IIQQQQQQ',data,phoff+i*entsize)
        if kind==1 and flags&1:loads.append((offset,va,filesize,memsize))
    result=[]
    for line in text.splitlines():
        fields=line.split(None,5)
        if len(fields)!=6 or 'x' not in fields[1]:continue
        path=fields[5].removesuffix(' (deleted)')
        if Path(path).name!=Path(binary).name:continue
        start,end=(int(x,16) for x in fields[0].split('-'));offset=int(fields[2],16)
        matches=[(off,va) for off,va,size,mem in loads if off//4096*4096<=offset<off+max(size,mem)]
        assert len(matches)==1,(line,matches)
        off,va=matches[0]
        result.append(dict(start=start,end=end,bias=start-(va+offset-off),path=path))
    assert result,'No executable main-image mapping'
    return result


def translate(ip, mappings):
    matches=[m for m in mappings if m['start']<=ip<m['end']]
    assert len(matches)<=1
    return ip-matches[0]['bias'] if matches else None


def remove_failed_captures(out, reason):
    from e2e_lbr import remove_generated
    paths=[p for directory in out.glob('*_p*') if directory.is_dir() and not directory.is_symlink()
           for name in ('perf.data','events.txt') if (p:=directory/name).exists()]
    if paths:
        remove_generated(paths,out/'failed_capture_cleanup.json',reason)


def decode_one(path, binary, maps):
    import capture_miss_timeline as capture
    import wake_miss_timeline as wake
    wake.EDGES_US=EDGES
    mappings=executable_maps(binary,maps)
    raw=Path(binary).read_bytes()
    has_metadata=any(s['name']==lean_plan.SECTION for s in lean_plan.sections(raw))
    targets=set()
    if has_metadata:
        image=lean_plan.read_image(binary)
        targets={r['target']//64 for r in image['records'] if r['active'] and r['direct']}
    bins=[Counter() for _ in EDGES]
    ips=Counter()

    def callback(age, ip, period, origin):
        bucket=bins[bisect_right(EDGES,age)-1]
        bucket['estimated_events']+=period
        va=translate(ip,mappings) if ip is not None else None
        if va is None:
            bucket['outside_main']+=period
        else:
            bucket['main']+=period;ips[va]+=period
            if has_metadata and va//64 in targets:bucket['static_target_line']+=period

    def retained():
        b.save(path/'target_overlap.json',dict(binary=str(binary),sha256=b.sha(binary),
            mappings=mappings,coverage_applicable=has_metadata,target_lines=len(targets),
            bins=[dict(lo_us=lo,hi_us=EDGES[i+1] if i+1<len(EDGES) else None,**counts)
                  for i,(lo,counts) in enumerate(zip(EDGES,bins))],
            top_main_ips=[dict(va=hex(ip),estimated_events=n) for ip,n in ips.most_common(80)],
            limitation='Static target-line overlap only. It does not prove this path issued a hint, that a fill arrived, or that a line survived until demand. Indirect T1 targets are not statically resolved.'))
    capture.decode_capture(path,sample_callback=callback,before_cleanup=retained)


def trial(spec):
    import fullset as h
    import capture_miss_timeline as capture
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    keys=spec.get('services',['movie'])
    assert keys and all(k in b.SERVICES for k in keys)
    periods=spec.get('periods',[1021,4093]);assert all(type(p) is int and p>=257 for p in periods)
    b.save(out/'protocol.json',dict(spec,binary_hashes={k:b.sha(p) for k,p in spec['overrides'].items()},
        bins_us=EDGES,purpose='Perturbing PEBS diagnostic; no E2E speedup estimate',
        source_sha256=b.sha(__file__),warmup_s=50,seconds_per_capture=15))
    stack=client=None;loaded=False;old=os.environ.get('CLASS_B_SCHED_CLOCK')
    captures=[];failure=None
    try:
        assert not Path('/sys/module/prefetchit_sched_clock').exists()
        if spec.get('clock',True):
            allowed={'dense_us','medium_us','sparse_us','dense_begin_us','medium_begin_us','sparse_begin_us'}
            options=spec.get('clock_options',{})
            assert all(k in allowed and type(v) is int and 0<=v<=1000 for k,v in options.items())
            command=['insmod',spec['module'],*['%s=%d'%(k,v) for k,v in options.items()]]
            b.run(command,out/'insmod.log');loaded=True
        os.environ['CLASS_B_SCHED_CLOCK']='1' if loaded else '0'
        stack=h.start(out,'media',spec['overrides'],8)
        load=out/'load';load.mkdir()
        command=['python3',Path(__file__).with_name('closed_loop_load.py'),'--out',load,
            '--concurrency',str(spec['concurrency']),'--seconds',str(65+18*len(keys)*len(periods)),
            '--seed',str(spec['seed'])]
        b.save(load/'command.json',command)
        with (load/'client.log').open('w') as log:
            client=subprocess.Popen(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if (load/'started.json').exists():break
            assert client.poll() is None;time.sleep(.1)
        else:raise RuntimeError('Diagnostic client did not start')
        time.sleep(50)
        for key in keys:
            service=h.TARGETS['media'][key][0];pid=stack.states[service]['State']['Pid']
            maps=Path(f'/proc/{pid}/maps').read_text();(out/(key+'.maps')).write_text(maps)
            for period in periods:
                assert client.poll() is None
                dest=out/f'{key}_p{period}'
                if spec.get('gate_stats'):
                    import lean_gate_stats
                    stats_path=Path(f'/proc/{pid}/root/tmp/prefetchit_gate_stats.bin')
                    stats_before=lean_gate_stats.read(stats_path)
                capture.capture(dest,pid,period)
                if spec.get('gate_stats'):
                    stats_after=lean_gate_stats.read(stats_path)
                    b.save(dest/'gate_activity.json',dict(before=stats_before,after=stats_after,
                        delta=lean_gate_stats.delta(stats_before,stats_after)))
                captures.append((dest,Path(spec['overrides'][key]),maps));time.sleep(3)
        assert client.wait(timeout=90)==0;client=None;stack.check()
        info=json.loads((load/'load.json').read_text())
        assert not info['steady_errors'] and info['client_cpu_cores']<.8
        b.save(out/'load_validation.json',dict(valid=True,load=info,
            interpretation='Health under profiling only, not an accepted latency/throughput trial'))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)));failure=error
    finally:
        h.c.stop(client)
        try:
            if stack is not None:stack.close()
        finally:
            if old is None:os.environ.pop('CLASS_B_SCHED_CLOCK',None)
            else:os.environ['CLASS_B_SCHED_CLOCK']=old
            if loaded:subprocess.run(['rmmod','prefetchit_sched_clock'],check=True)
            b.save(out/'clock_restoration.json',dict(unloaded=not Path('/sys/module/prefetchit_sched_clock').exists(),enabled=loaded))
        h.old.compact(out)
    if failure is not None:
        remove_failed_captures(out,'Invalid or interrupted diagnostic: settings, commands, logs, source and binary hashes retained; no performance claim.')
        raise failure
    errors=[]
    for dest,binary,maps in captures:
        try:decode_one(dest,binary,maps)
        except BaseException as error:
            b.save(dest/'decode_failure.json',dict(error=repr(error)))
            if isinstance(error,(KeyboardInterrupt,SystemExit)):
                remove_failed_captures(out,'Diagnostic decode interrupted; compact results and interruption record retained.')
                raise
            errors.append(dict(path=str(dest),error=repr(error)))
    if errors:
        b.save(out/'decode_failures.json',errors)
        remove_failed_captures(out,'Diagnostic decode/quality rejection: valid compact results and failure reasons retained; remaining raw/decoded copies unused.')
        raise RuntimeError('One or more diagnostic captures failed quality/decode')
    b.save(out/'complete.json',dict(valid=True,captures=[str(p[0]) for p in captures]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['trial','campaign']);parser.add_argument('spec',type=Path)
    args=parser.parse_args();spec=json.loads(args.spec.read_text())
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action=='trial':trial(spec);return
    import fullset as h
    root=Path(spec['out']);root.mkdir(parents=True,exist_ok=False);b.save(root/'protocol.json',spec)
    for index,setting in enumerate(spec['trials']):
        manifest=root/(str(index)+'.json');dest=root/('%02d_%s'%(index,setting['name']))
        b.save(manifest,dict(setting,out=str(dest)))
        h.platform(dest,['python3',__file__,'trial',str(manifest)])
    b.save(root/'complete.json',dict(trials=len(spec['trials'])))


if __name__=='__main__':main()
