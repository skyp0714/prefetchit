#!/usr/bin/env python3
"""Separate DWARF+LBR diagnosis of RPC context lost by bounded branch history."""
import argparse
import bisect
import collections
import gzip
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

import dense_build as b
import fullset as h
import media_system_study as system
import balanced_backend as balanced
from backend_prefetch import bind_mongodb, audit_backends
from media_library_study import bind_libraries, audit_libraries
from temporal_path_study import catalog_process
from lean_timeline import request_window
from rpc_route_study import load
from rpc_predict_environment import cpus


class RpcAttribution:
    """Bounded ranges only; shared stubs retain every possible source RPC."""
    def __init__(self, root, catalog):
        self.catalog=catalog;self.names=list(catalog)
        self.intervals=sorted((m['start'],m['end'],m['bias'],i)
            for i,name in enumerate(self.names) for m in catalog[name]['mappings'])
        self.starts=[v[0] for v in self.intervals]
        self.main=self.names.index('/custom/ComposeReviewService')
        inventory=load(root/'rpc_inventory.json')['compose']
        self.ranges=[(m[key]['va'],m[key]['va']+m[key]['size'],m['method'])
            for m in inventory['methods'] for key in ('handler','processor')]
        source=load(root/'arms.json')['full']['overrides']['compose']
        assert catalog[self.names[self.main]]['sha256']==b.sha(source)
        self.patches=load(Path(source+'.json'))['patches']
        self.label_cache={}

    def resolve(self,ip):
        index=bisect.bisect_right(self.starts,ip)-1
        if index>=0 and ip<self.intervals[index][1]:
            _,_,bias,dso=self.intervals[index];return [dso,ip-bias]
        return [-1,ip]

    def labels(self,address,legacy=False):
        dso,ip=address
        if dso!=self.main:return []
        key=tuple(address)+(legacy,)
        if key in self.label_cache:return self.label_cache[key]
        patches=[p for p in self.patches if p['stub']<=ip<max(p['terminal_jumps'])+5]
        if legacy and patches:
            patches=[max(patches,key=lambda p:(p['stub'],max(p['terminal_jumps'])+5,p['site']))]
        sites=[p['site'] for p in patches]
        labels=sorted({label for point in (sites or [ip]) for start,end,label in self.ranges if start<=point<end})
        self.label_cache[key]=labels;return labels

    def nearest(self,addresses,legacy=False):
        for depth,address in enumerate(addresses):
            labels=self.labels(address,legacy)
            if labels:return dict(labels=labels,depth=depth,address=address)
        return dict(labels=[],depth=None,address=None)


def audit_aliases(root,out):
    arm=load(root/'arms.json')['full'];inventory=load(root/'rpc_inventory.json')
    models={n:load(root/(n+'.json')) for n in ('model','wide_model','wide_span_model','reply_model')}
    rows=[]
    for service,source in arm['overrides'].items():
        groups=collections.defaultdict(list)
        for patch in load(Path(source+'.json'))['patches']:groups[patch['stub']].append(patch)
        for stub,patches in groups.items():
            if len(patches)<2:continue
            sites=[]
            for patch in patches:
                labels=sorted({m['method'] for m in inventory[service]['methods'] for key in ('handler','processor')
                    if m[key]['va']<=patch['site']<m[key]['va']+m[key]['size']})
                sites.append(dict(site=patch['site'],rpc_labels=labels))
            selected={name:[dict(method=c.get('method',c.get('reply_type')),target=t)
                for c in model[service]['choices'] for t in c['targets']
                if stub<=t<max(patches[0]['terminal_jumps'])+5] for name,model in models.items()}
            rows.append(dict(service=service,stub=stub,sites=sites,selected=selected))
    b.save(out/'shared_stub_audit.json',dict(groups=rows,
        limitation='One shared stub address can have several originating RPCs. Static range-to-last-site mapping is not dynamic caller attribution. The stored policies are frozen; this diagnostic does not alter their binaries or measured results.'))


def clean_symfs(out):
    root=out/'symfs';rows=[]
    if not root.exists():return
    paths=sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True)
    for path in paths:
        if path.is_symlink():
            rows.append(dict(path=str(path),target=str(path.readlink()),symlink_bytes=path.lstat().st_size))
        else:assert path.is_dir(),path
    record=dict(links=rows,removed_target_bytes=0,complete=False,free_before=shutil.disk_usage(out).free,
        reason='Only experiment-created symlinks and empty directories removed; mapped ELF targets retained.')
    b.save(out/'symfs_cleanup.json',record)
    for path in paths:
        if path.is_symlink():path.unlink()
        else:
            path.rmdir()
    root.rmdir()
    record.update(complete=True,free_after=shutil.disk_usage(out).free)
    b.save(out/'symfs_cleanup.json',record)


def extract(spec):
    """Compare two imperfect RPC context signals on the identical sample set."""
    from e2e_lbr import remove_generated
    from perf_record_quality import counts as record_counts
    from temporal_path_study import branch_stack
    from wake_miss_timeline import LINE
    root=Path(spec['root']);out=Path(spec['out']);assert load(out/'decode_ready.json')['valid']
    assert not (out/'complete.json').exists()
    try:
        counts=record_counts(out/'perf.data');b.save(out/'record_types.json',counts)
        assert not any(counts.get(k,0) for k in ('LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'))
        attribution=RpcAttribution(root,load(out/'catalog.json'))
        frame=re.compile(r'^\s+((?:0x)?[0-9a-fA-F]{1,16})\s+(.+)$')
        rows=[];current=None;unparsed=[]
        def finish():
            if current is None:return
            assert current['frames'] or current['header_ip'] is not None,current
            ip=current['header_ip'] if current['header_ip'] is not None else current['frames'][0][0]
            address=attribution.resolve(ip)
            frames=[dict(address=attribution.resolve(pointer),symbol=symbol,inlined=inlined)
                for pointer,symbol,inlined in current['frames']]
            edges=[]
            # With the dso output field, perf also decorates each branch endpoint
            # as `0xIP (DSO)/...`. Remove only that decoration before parsing.
            payload=re.sub(r'\s+\([^)]*\)(?=/)','',' '.join(current['payload']))
            for source,target,pred,cycles,typ in branch_stack('0 '+payload):
                edges.append([*attribution.resolve(source),*attribution.resolve(target),pred,cycles,typ])
            lbr_addresses=[address]+[v for edge in edges for v in (edge[:2],edge[2:4])]
            lbr=attribution.nearest(lbr_addresses)
            legacy=attribution.nearest(lbr_addresses,legacy=True)
            stack=attribution.nearest([f['address'] for f in frames])
            left,right=set(lbr['labels']),set(stack['labels'])
            if not left and not right:category='neither'
            elif not left:category='stack_only_unique' if len(right)==1 else 'stack_only_ambiguous'
            elif not right:category='lbr_only_unique' if len(left)==1 else 'lbr_only_ambiguous'
            elif len(left)==len(right)==1 and left==right:category='both_same_unique'
            elif left.isdisjoint(right):category='both_disagree'
            else:category='both_ambiguous_overlap'
            rows.append(dict(time_ns=current['time_ns'],cpu=current['cpu'],tid=current['tid'],pid=current['pid'],
                address=address,frames=frames,edges=edges,lbr_context=lbr,stack_context=stack,
                legacy_last_site_lbr_context=legacy,category=category,
                header_ip_present=current['header_ip'] is not None,
                leaf_matches_header=(frames[0]['address']==address if frames and current['header_ip'] is not None else None)))
        with (out/'events.txt').open() as stream:
            for line in stream:
                header=LINE.match(line)
                if header:
                    finish();payload=header[9]
                    assert header[8]=='fe_l2' and int(header[7])==257,header.groups()
                    leaf=re.match(r'^((?:0x)?[0-9a-fA-F]+)(?:\s|$)',payload)
                    current=dict(time_ns=int(header[5])*10**9+int(header[6]),cpu=int(header[4]),
                        pid=int(header[2]),tid=int(header[3]),header_ip=int(leaf[1],16) if leaf else None,
                        frames=[],payload=[payload])
                    continue
                if not line.strip():continue
                assert current is not None,('Content before first event',line)
                current['payload'].append(line.strip())
                match=frame.match(line)
                if match and re.match(r'^\([^)]*\)/(?:0x)?[0-9a-fA-F]+(?:\s|/)',match[2]):
                    match=None  # Decorated branch endpoints are not stack frames.
                if match:
                    # The last DSO parenthesis is display metadata, not identity;
                    # mapped executable addresses and SHA catalog define identity.
                    symbol=re.sub(r'\s+\([^)]*\)\s*$','',match[2])
                    current['frames'].append([int(match[1],16),symbol,match[2].endswith('(inlined)')])
                elif '/' not in line:
                    unparsed.append(line.strip())
        finish()
        assert len(rows)==counts.get('SAMPLE',0)>0,(len(rows),counts)
        assert not unparsed,unparsed[:10]
        assert sum(bool(r['edges']) for r in rows)>.95*len(rows),'Missing bounded branch history'
        requests=load(out/'request_window.json')['completed_requests'];assert requests>0
        weight=257/requests
        totals=collections.Counter(r['category'] for r in rows)
        main_totals=collections.Counter(r['category'] for r in rows if r['address'][0]==attribution.main)
        extra=collections.Counter();symbols=collections.Counter();depths=collections.Counter()
        physical_depths=collections.Counter();quality=collections.Counter()
        for row in rows:
            quality['samples']+=1;quality['with_frames']+=bool(row['frames'])
            quality['with_branches']+=bool(row['edges']);quality['unmapped_leaf']+=row['address'][0]<0
            quality['header_ip_present']+=row['header_ip_present'];quality['unknown_tid']+=row['tid']<0
            quality['leaf_header_mismatch']+=row['leaf_matches_header'] is False
            quality['frames']+=len(row['frames']);quality['unmapped_frames']+=sum(f['address'][0]<0 for f in row['frames'])
            physical=sum(not f['inlined'] for f in row['frames']);physical_depths[physical]+=1
            quality['with_two_physical_frames']+=physical>=2
            quality['leaf_symbol_unknown']+=bool(row['frames']) and row['frames'][0]['symbol']=='[unknown]'
            depths[len(row['frames'])]+=1
            left=row['legacy_last_site_lbr_context']['labels'];right=row['stack_context']['labels']
            quality['legacy_vs_stack_both_unique']+=len(left)==len(right)==1
            quality['legacy_vs_stack_unique_disagreement']+=len(left)==len(right)==1 and left!=right
            quality['legacy_forced_unique_at_ambiguous_nearest_stub']+=(len(row['lbr_context']['labels'])>1
                and len(left)==1 and row['legacy_last_site_lbr_context']['depth']==row['lbr_context']['depth'])
            if row['category']=='stack_only_unique':
                label=row['stack_context']['labels'][0];dso,ip=row['address']
                extra[label,dso,ip//64]+=1
                symbols[label,row['frames'][0]['symbol'] if row['frames'] else 'no_frame']+=1
        with gzip.open(out/'observations.json.gz','wt') as stream:
            json.dump(dict(format_version=1,names=attribution.names,catalog=attribution.catalog,
                period=257,requests=requests,rows=rows),stream,separators=(',',':'))
        result=dict(valid=True,source_sha256=b.sha(__file__),record_counts=counts,quality=dict(quality),
            requests=requests,period=257,frame_depth_samples=dict(sorted(depths.items())),
            physical_frame_depth_samples=dict(sorted(physical_depths.items())),
            categories=dict(totals),main_categories=dict(main_totals),
            events_per_request={k:v*weight for k,v in totals.items()},
            new_stack_context_lines=[dict(method=m,dso=d,line=line,samples=n,events_per_request=n*weight)
                for (m,d,line),n in extra.most_common(50)],
            new_stack_context_symbols=[dict(method=m,symbol=s,samples=n,events_per_request=n*weight)
                for (m,s),n in symbols.most_common(30)],
            definition='Nearest recognizable incoming handler/processor range at sampled IP or bounded LBR versus nearest such DWARF frame on identical samples. Shared stub labels retain all possible originating RPCs. Missing/ambiguous/disagreeing contexts remain explicit.',
            legacy_audit='Secondary comparison reproduces the old sorted-range last-site choice for a shared stub, using bounded handler/processor ranges. A disagreement with a stack is not by itself proof that the stack is complete or that this older branch belonged to the current RPC.',
            limitations='DWARF user stack is bounded to 8192 bytes; missing context is not proof of no RPC. LBR can contain completed earlier calls, while a stack only contains current live calls and may omit asynchronous parents. No unrecorded caller or current future branch outcome is invented. The perturbing single-service capture is not an endpoint comparison or complete execution trace. These diagnostic targets were never used to select the measured candidate.')
        b.save(out/'summary.json',result)
    except BaseException as error:
        b.save(out/'extraction_failure.json',dict(error=repr(error)));raise
    finally:
        paths=[p for p in (out/'perf.data',out/'events.txt') if p.exists()]
        if paths:remove_generated(paths,out/'extraction_cleanup.json',
            'Compact call-stack/LBR observations and quality retained, or rejection recorded. Raw samples and decoded text are no longer needed.')
        clean_symfs(out)
    b.save(out/'complete.json',dict(valid=True,epoch=time.time(),samples=len(rows),summary_sha256=b.sha(out/'summary.json')))
    print(json.dumps(dict(samples=len(rows),categories=dict(totals),quality=dict(quality))))


def capture(spec):
    root=Path(spec['root']);out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    assert load(root/'all_measurements_complete.json')['valid']
    b.space(root);system.configure();stack=client=None;catalog={}
    source=Path(__file__);snapshot=root/'source_versions'/(b.sha(source)+'.py')
    if not snapshot.exists():snapshot.write_bytes(source.read_bytes())
    audit_aliases(root,out)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),
        purpose='Exploratory diagnosis only: compare RPC attribution from sampled user call stacks and bounded LBR. No endpoint effect or candidate selection uses this capture.',
        workload='Same Media compose-review C4; incumbent full arm; ComposeReviewService only.',
        capture_s=8,user_stack_bytes=8192,period=257,seed=1022401))
    try:
        with bind_libraries(out,spec),bind_mongodb(out,spec['mongo_binary']):
            stack=h.start(out,'media',spec['overrides'],8)
        system.audit_native(stack,out,spec['overrides']);audit_backends(stack,out,spec['mongo_binary'])
        if spec.get('libraries'):audit_libraries(stack,out,spec)
        pid=stack.states[system.MONITORED['compose']]['State']['Pid']
        catalog=catalog_process(pid,root,out)
        group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
        client=balanced.start_client(out,90,1022401);time.sleep(50);b.space(root)
        event='cpu/event=0xc6,umask=0x3,config1=0x13,period=257,name=fe_l2/upp'
        command=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M',
            '-e',event,'-j','any,u','--call-graph','dwarf,8192','-G',group,
            '-o',out/'perf.data','--','sleep','8']
        b.save(out/'capture_command.json',list(map(str,command)))
        cpu_before=cpus();begin=time.time();b.run(command,out/'record.log');end=time.time();cpu_after=cpus()
        groups={}
        for label,indices in {'server':set(range(32,40)),'client':set(range(16,20)),
                'other_host':set(cpu_after)-set(range(32,40))-set(range(16,20))-{84,85}}.items():
            total=sum(cpu_after[i][0]-cpu_before[i][0] for i in indices)
            idle=sum(cpu_after[i][1]-cpu_before[i][1] for i in indices)
            groups[label]=100*(1-idle/total) if total else None
        b.save(out/'aggregate_environment.json',dict(begin_epoch=begin,end_epoch=end,cpu_busy_pct=groups,
            interpretation='Whole perf invocation average; descriptive only. No unrelated process identities.'))
        assert not re.search(r'\b(lost|truncated|throttled)\b',(out/'record.log').read_text(),re.I)
        assert client.wait(timeout=120)==0;client=None;stack.check()
        info=load(out/'load/load.json');assert info['mapping_preserved'] and not info['steady_errors']
        with gzip.open(out/'load/requests.json.gz','rt') as stream:requests=json.load(stream)
        b.save(out/'request_window.json',request_window(requests,begin,end))
        b.save(out/'load_validation.json',dict(valid=True,load=info))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)
        if (out/'failure.json').exists() and (out/'perf.data').exists():
            from e2e_lbr import remove_generated
            remove_generated([out/'perf.data'],out/'failure_cleanup.json','Rejected optional capture; command, failure and settings retained.')
    symroot=out/'symfs'
    command=['perf','script','--ns','--no-demangle','--symfs',str(symroot),'-i',str(out/'perf.data'),
        '-F','comm,pid,tid,cpu,time,event,ip,sym,dso,period,brstack']
    b.save(out/'decode_command.json',command)
    try:
        symroot.mkdir()
        for name,entry in catalog.items():
            local=Path(entry['binary']);assert b.sha(local)==entry['sha256']
            assert not str(local.resolve()).startswith('/fast-lab-share/')
            link=symroot/name.lstrip('/');link.parent.mkdir(parents=True,exist_ok=True)
            link.symlink_to(local)
        with (out/'events.txt').open('w') as output,(out/'decode.log').open('w') as err:
            subprocess.run(command,stdout=output,stderr=err,check=True)
    except BaseException as error:
        from e2e_lbr import remove_generated
        b.save(out/'decode_failure.json',dict(error=repr(error)))
        remove_generated([p for p in (out/'perf.data',out/'events.txt') if p.exists()],
            out/'decode_failure_cleanup.json','Rejected optional decoding; command, hashes and failure retained.')
        clean_symfs(out)
        raise
    b.save(out/'decode_ready.json',dict(valid=True,epoch=time.time(),raw_sha256=b.sha(out/'perf.data'),
        decoded_sha256=b.sha(out/'events.txt'),raw_bytes=(out/'perf.data').stat().st_size,
        note='Extraction and quality review still required before immediate raw/decoded/symfs cleanup.'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['capture','platform_capture','extract']);p.add_argument('spec',type=Path)
    args=p.parse_args();spec=load(args.spec)
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if args.action=='capture':capture(spec)
    elif args.action=='extract':extract(spec)
    else:h.platform(Path(spec['out']),['python3',__file__,'capture',args.spec])
