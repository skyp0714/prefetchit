#!/usr/bin/env python3
"""Schedule-relative PEBS/LBR observations across Media executables and DSOs.

Capture and endpoint timing are separate. Every observation retains ELF identity,
retirement age and a bounded retired branch history; none is a fetch timestamp,
hardware prefetch completion or proof of BTB state.
"""
import argparse
import bisect
import collections
from datetime import datetime, timezone, timedelta
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

import balanced_backend as balanced
from backend_prefetch import bind_mongodb, audit_backends
import dense_build as b
from e2e_lbr import remove_generated
import fullset as h
from lean_timeline import executable_maps, request_window
from media_library_study import bind_libraries, audit_libraries
import media_system_study as system
import wake_miss_timeline as wake
from temporal_path_common import PRIOR, EDGES

EVENTS = {
    'l2': (0xc6, 3, 0x13, 1021),
    'l1': (0xc6, 3, 0x12, 4093),
    'lat128': (0xc6, 3, 0x608006, 1021),
    'unknown': (0xc6, 3, 0x17, 1021),
    'calls': (0xc4, 2, None, 4093),
}


def initialize(root):
    root.mkdir(parents=True, exist_ok=False); b.space(root)
    settings = json.loads((PRIOR/'settings.json').read_text())
    assert all(b.sha(p) == digest for p, digest in settings['hashes'].items())
    start = datetime.now(timezone.utc)
    b.save(root/'protocol.json', dict(start_utc=start.isoformat(),
        deadline_utc=(start + timedelta(hours=7)).isoformat(),
        user_request='Seven-hour iterative prefetch campaign: temporal miss coverage, call graph and traces, clean throughput/latency validation.',
        prior=str(PRIOR), settings=settings, source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        workload='Full Media compose-review, balanced C4, CPUs32-39, fixed2GHz, tracing100%. Other request types require separate validation.',
        method='Original, retained Mongo split75, reconstructed prior joint policy. Train and heldout on independent fresh stacks. Sample retirement ages, LBR paths, static CFG/call graph; never equate coverage with actual fills. Clean endpoint validation against original, retained winner and layout NOP.',
        budget=dict(expected_temporary_bytes=8*2**30,root_free=shutil.disk_usage('/').free,storage_free=shutil.disk_usage(root).free),
        retention='Preserve compact observations, settings, source/patch records, hashes and exclusion reasons; remove raw/decoded captures after extraction and rejected generated ELFs immediately. No NAS timing.'))
    arms = json.loads((PRIOR/'prepared.json').read_text())['arms']
    b.save(root/'arms.json', {k:v for k,v in arms.items() if k in ('original','mongo')})


def reconstruct(root):
    """Rebuild the earlier joint policy exactly, as a current diagnostic control."""
    from callpath_prefetch import stubs
    old = json.loads((PRIOR/'prepared.json').read_text())
    libraries = json.loads((PRIOR/'libraries/prepared.json').read_text())
    tasks = []
    for key, entry in old['candidates'].items():
        audit = json.loads((PRIOR/'patch_records/native'/key/(Path(entry['binary']).name+'.json')).read_text())
        tasks.append((entry, audit, root/'controls/native'/key/Path(entry['binary']).name))
    for digest, entry in libraries['candidates'].items():
        audit = json.loads((PRIOR/'patch_records/libraries'/digest/(entry['name']+'.json')).read_text())
        tasks.append((entry, audit, root/'controls/libraries'/digest/entry['name']))
    remap = {}; records=[]
    for entry, audit, output in tasks:
        b.space(root)
        record=stubs.build(Path(audit['source']),audit['plan'],output)
        assert record['sha256']==entry['sha256'] and record['nop_sha256']==entry['nop_sha256']
        remap[entry['binary']]=str(output); remap[entry['nop']]=str(output)+'.nop'
        records.append(dict(source=audit['source'],binary=str(output),sha256=record['sha256'],nop_sha256=record['nop_sha256']))
        print(json.dumps(dict(stage='reconstructed',binary=str(output))),flush=True)
    arms=json.loads((root/'arms.json').read_text())
    for name in ('combined','combined_nop'):
        arm=json.loads(json.dumps(old['arms'][name]))
        arm['overrides']={k:remap[v] for k,v in arm['overrides'].items()}
        arm['libraries']={k:{target:remap[source] for target,source in entries.items()} for k,entries in arm['libraries'].items()}
        arms[name]=arm
    b.save(root/'arms.json',arms);b.save(root/'reconstruction.json',records)


def catalog_process(pid, root, out):
    """Keep original mapped files local and identify every DSO by SHA, not build-id."""
    text=Path(f'/proc/{pid}/maps').read_text();(out/'maps.txt').write_text(text)
    catalog={}; known={}
    prior=json.loads((PRIOR/'libraries/prepared.json').read_text())
    for digest,entry in prior['references'].items():
        known[digest]=entry['binary']
    settings=json.loads((PRIOR/'settings.json').read_text())
    known.update({digest:path for path,digest in settings['hashes'].items()})
    for directory in ('controls','builds'):
        for audit_path in (root/directory).rglob('*.json'):
            record=json.loads(audit_path.read_text());binary=Path(str(audit_path)[:-5])
            if 'hints' in record:
                if binary.is_file():known[record['sha256']]=str(binary)
                twin=Path(record.get('nop_path',str(binary)+'.nop'))
                if twin.is_file():known[record['nop_sha256']]=str(twin)
    for line in text.splitlines():
        fields=line.split(None,5)
        if len(fields)!=6 or 'x' not in fields[1] or not fields[5].startswith('/'):continue
        name=fields[5]
        if name in catalog:continue
        source=Path(f'/proc/{pid}/root')/name.lstrip('/');digest=b.sha(source)
        if digest in known:local=Path(known[digest])
        else:
            local=root/'references'/digest/Path(name).name
            if not local.exists():
                b.space(root);local.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,local);local.chmod(0o755)
        assert b.sha(local)==digest
        catalog[name]=dict(binary=str(local),sha256=digest,mappings=executable_maps(local,text))
    b.save(out/'catalog.json',catalog)
    return catalog


def capture(spec):
    system.configure();root=Path(spec['root']);out=Path(spec['out'])
    out.mkdir(parents=True,exist_ok=False);b.space(root)
    versions={}
    for name in ('temporal_path_study.py','temporal_path_common.py','wake_miss_timeline.py','perf_record_quality.py'):
        source=Path(__file__).with_name(name);digest=b.sha(source)
        saved=root/'source_versions'/(digest+'.py');saved.parent.mkdir(exist_ok=True)
        if not saved.exists():saved.write_bytes(source.read_bytes())
        versions[name]=dict(sha256=digest,snapshot=str(saved))
    b.save(out/'source_manifest.json',versions)
    kinds=spec.get('kinds',['l2','lat128']);keys=spec['services'];seconds=spec.get('capture_s',8)
    period_override=spec.get('periods',{})
    total_seconds=65+len(kinds)*len(keys)*(seconds+1)
    assert total_seconds<=290,'Split long diagnostics before the fixed server connection limit'
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),bins_us=EDGES,
        clock='Single perf recorder, default clock, native PEBS TSC timestamps; scheduler selection before switch completion.',
        events=EVENTS,scope='Perturbing diagnosis only; not clean endpoint performance.'))
    stack=client=None;captures=[];windows={}
    try:
        with bind_libraries(out,spec),bind_mongodb(out,spec['mongo_binary']):
            stack=h.start(out,'media',spec['overrides'],8)
        system.audit_native(stack,out,spec['overrides']);audit_backends(stack,out,spec['mongo_binary'])
        if spec.get('libraries'):audit_libraries(stack,out,spec)
        runtime={key:stack.states[system.MONITORED[key]]['State']['Pid'] for key in keys}
        for key,pid in runtime.items():
            folder=out/key;folder.mkdir();catalog_process(pid,root,folder)
        client=balanced.start_client(out,total_seconds,spec['seed']);time.sleep(50)
        for kind in kinds:
            ev,mask,config,period=EVENTS[kind];period=period_override.get(kind,period)
            assert period>=257
            event=f'cpu/event=0x{ev:x},umask=0x{mask:x},period={period},name=fe_{kind},branch_type=any'+(f',config1=0x{config:x}' if config is not None else '')+'/upp'
            for key,pid in runtime.items():
                b.space(root);dest=out/key/kind;dest.mkdir()
                tids=sorted(int(p.name) for p in Path(f'/proc/{pid}/task').iterdir())
                group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                command=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M',
                    '-e',event,'-e','sched:sched_switch','-G',group+',','-o',dest/'perf.data','--','sleep',str(seconds)]
                b.save(dest/'capture.json',dict(pid=pid,tids=tids,cgroup=group,period=period,event=event,kind=kind))
                begin=time.time();b.run(command,dest/'record.log');windows[str(dest)]=(begin,time.time())
                assert not re.search(r'\b(lost|truncated|throttled)\b',(dest/'record.log').read_text(),re.I)
                assert client.poll() is None;captures.append(dest)
                print(json.dumps(dict(stage='captured',service=key,kind=kind)),flush=True)
        assert client.wait(timeout=total_seconds+30)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text());assert not info['steady_errors'] and info['mapping_preserved']
        with gzip.open(out/'load/requests.json.gz','rt') as stream:samples=json.load(stream)
        for dest in captures:b.save(dest/'request_window.json',request_window(samples,*windows[str(dest)]))
        b.save(out/'load_validation.json',dict(valid=True,load=info))
    except BaseException as error:b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)
        if (out/'failure.json').exists():
            files=list(out.glob('*/*/perf.data'))
            if files:remove_generated(files,out/'failure_cleanup.json','Invalid capture; protocol, command, failure and hashes retained.')
    errors=[]
    for dest in captures:
        try:decode(dest)
        except Exception as error:
            errors.append(dict(path=str(dest),error=repr(error)))
    if errors:
        b.save(out/'decode_failures.json',errors)
        raise RuntimeError('One or more temporal captures failed decoding/quality; compact outcomes retained and all raw copies cleaned')
    b.save(out/'complete.json',dict(valid=True,captures=list(map(str,captures))))


def branch_stack(payload):
    edges=[]
    for part in payload.split()[1:]:
        fields=part.split('/')
        if len(fields)<7:continue
        try:
            source,target=int(fields[0],16),int(fields[1],16)
            cycles=int(fields[5]) if fields[5].isdigit() else None
        except ValueError:continue
        edges.append((source,target,fields[2],cycles,fields[6]))
    return edges


def decode(dest):
    meta=json.loads((dest/'capture.json').read_text());pid=meta['pid'];kind=meta['kind']
    command=['perf','script','--ns','-i',str(dest/'perf.data'),'--show-lost-events','--show-task-events',
        '-F','comm,pid,tid,cpu,time,event,ip,period,trace,brstack']
    b.save(dest/'decode_command.json',command)
    try:
        with (dest/'events.txt').open('w') as output,(dest/'decode.log').open('w') as err:
            subprocess.run(command,stdout=output,stderr=err,check=True)
        from perf_record_quality import counts as record_counts
        try:
            counts=collections.Counter(record_counts(dest/'perf.data'))
        except AssertionError as error:
            counts=None
            b.save(dest/'binary_scanner_fallback.json',dict(error=repr(error),
                action='Use established perf script -D quality extraction for unsupported file framing. No quality gate relaxed.'))
        campaign=Path(json.loads((dest.parent.parent/'protocol.json').read_text())['root'])
        validation=campaign/'record_scan_validation.json'
        if counts is None or not validation.exists():
            legacy=collections.Counter()
            with (dest/'quality.log').open('w') as err:
                proc=subprocess.Popen(['perf','script','-D','-i',str(dest/'perf.data')],stdout=subprocess.PIPE,stderr=err,text=True)
                for line in proc.stdout:
                    match=re.search(r'PERF_RECORD_(\w+)',line)
                    if match:legacy[match[1]]+=1
                assert proc.wait()==0
            compared=['SAMPLE','FORK','EXIT','COMM','MMAP','MMAP2','LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE']
            if counts is None:counts=legacy
            else:
                assert all(counts[k]==legacy[k] for k in compared),(counts,legacy)
                b.save(validation,dict(valid=True,capture=str(dest),binary_counts=dict(counts),perf_script_counts=dict(legacy),
                    compared=compared,scanner_sha256=b.sha(Path(__file__).with_name('perf_record_quality.py'))))
        b.save(dest/'record_types.json',dict(counts))
        assert not any(counts[x] for x in ('LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'))
        catalog=json.loads((dest.parent/'catalog.json').read_text());names=list(catalog)
        intervals=sorted((m['start'],m['end'],m['bias'],i) for i,name in enumerate(names) for m in catalog[name]['mappings'])
        starts=[x[0] for x in intervals]
        def resolve(ip):
            j=bisect.bisect_right(starts,ip)-1
            if j>=0 and ip<intervals[j][1]:return [intervals[j][3],ip-intervals[j][2]]
            return [-1,ip]
        rows=[];ips=collections.Counter();edges=collections.Counter();dsos=collections.Counter();branches=0
        def detail(age,event,origin):
            nonlocal branches
            dso,va=resolve(event['ip']);history=[];dsos[dso]+=1
            ips[dso,va,bisect.bisect_right(EDGES,age)-1]+=1
            for source,target,pred,cycles,typ in branch_stack(event['payload']):
                fr=resolve(source);to=resolve(target);history.append([*fr,*to,pred,cycles,typ])
                edges[fr[0],fr[1],to[0],to[1],typ]+=1
            branches+=bool(history)
            rows.append(dict(dso=dso,ip=va,age_us=age,origin=origin,unknown_tid=event['tid']==-1,edges=history))
        wake.EDGES_US=EDGES
        known_tids=set(meta['tids'])
        with (dest/'events.txt').open() as stream:
            for line in stream:
                if 'PERF_RECORD_FORK' not in line:continue
                task=wake.TASK.match(line)
                if task and int(task[5])==pid:known_tids.add(int(task[6]))
        with (dest/'events.txt').open() as stream:
            parsed=wake.parse(stream,pid,sample_events=('fe_'+kind,),retain_payload=True,filter_tids=known_tids)
        timeline=wake.analyze(parsed,set(meta['tids']),pid,sample_detail_callback=detail)
        filter_validation=campaign/'schedule_filter_validation.json'
        if not filter_validation.exists():
            with (dest/'events.txt').open() as stream:
                full=wake.parse(stream,pid,sample_events=('fe_'+kind,))
            reference=wake.analyze(full,set(meta['tids']),pid)
            compared=['bins','origins','median_run_us','p90_run_us','runs_with_prior_out','migrated_pct','median_off_us']
            assert all(timeline[k]==reference[k] for k in compared),'Filtered schedule statistics differ'
            quality_keys=['target_samples','complete_samples','complete_runs','unmatched_samples','unknown_tid_resolved_by_cpu_interval']
            assert all(timeline['quality'].get(k,0)==reference['quality'].get(k,0) for k in quality_keys)
            b.save(filter_validation,dict(valid=True,capture=str(dest),full_records=len(full),filtered_records=len(parsed),
                compared=compared,quality_keys=quality_keys,parser_sha256=b.sha(Path(wake.__file__))))
            del full
        assert not timeline['quality'].get('foreign_samples',0)
        assert timeline['quality']['complete_sample_pct']>99,timeline['quality']
        assert branches>.95*len(rows),('Missing branch stacks',branches,len(rows))
        timeline.update(event=meta['event'],period=meta['period'],kind=kind)
        timeline['schedule_filter']='All recorded target TGID TIDs (initial plus FORK); preserve every target switch and any discontinuity on an active target CPU. Thread lifetimes still checked after filtering.'
        b.save(dest/'timeline.json',timeline)
        with gzip.open(dest/'observations.json.gz','wt') as stream:
            json.dump(dict(format_version=1,names=names,catalog=catalog,period=meta['period'],rows=rows),stream,separators=(',',':'))
        b.save(dest/'locations.json',dict(samples=len(rows),with_branches=branches,dso_counts=dict(dsos),
            ip_age_counts=[dict(dso=d,ip=ip,bin=i,samples=n) for (d,ip,i),n in ips.items()],
            observed_edges=[dict(source_dso=d,source=fr,target_dso=t,target=to,kind=k,occurrences=n) for (d,fr,t,to,k),n in edges.items()],
            limitation='LBR edges repeat across samples and are miss-conditioned, not unbiased call frequencies. Retirement age is not fetch time; absent branch history is not proof that a hint never ran.'))
    except BaseException as error:
        b.save(dest/'decode_failure.json',dict(error=repr(error)));raise
    finally:
        files=[dest/name for name in ('perf.data','events.txt') if (dest/name).exists()]
        if files:remove_generated(files,dest/'decode_cleanup.json','Compact schedule/ELF/LBR observations extracted, or decoder rejected with error retained. Raw and decoded copies no longer needed.')
    print(json.dumps(dict(stage='decoded',path=str(dest),samples=len(rows))),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['initialize','reconstruct','capture','decode','platform_capture']);p.add_argument('path',type=Path)
    a=p.parse_args();signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if a.action=='platform_capture':
        spec=json.loads(a.path.read_text());h.platform(Path(spec['out']),['python3',__file__,'capture',a.path])
    elif a.action=='capture':capture(json.loads(a.path.read_text()))
    else:globals()[a.action](a.path)


if __name__=='__main__':main()
