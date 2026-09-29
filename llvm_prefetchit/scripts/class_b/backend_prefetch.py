#!/usr/bin/env python3
"""Fresh-stack MongoDB instruction-prefetch diagnostics and byte-exact variants.

Every MongoDB container uses the same selected ELF. This preserves executable
page sharing between MongoDB processes; binding only two patched containers
would change physical code sharing relative to the original workload.
"""
import argparse
import collections
from contextlib import contextmanager
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import time
import dense_build as b
import fullset as h
from dense_causes import decode
from dense_cause_analysis import Code,HEADER,EDGE,mapping_bias,category
from e2e_lbr import remove_generated
from index_executable_padding import is_padding_nop
from residual_retarget import plan

BACKENDS=['user-review-mongodb','movie-review-mongodb']

@contextmanager
def bind_mongodb(out,binary):
    """Adapt this private trial's compose construction without changing inputs."""
    if binary is None:
        yield
        return
    binary=Path(binary).resolve();assert binary.is_file() and not str(binary).startswith('/fast-lab-share/')
    original_save=h.media.save;changed=[]
    def save(path,data):
        if path==out/'compose.json':
            names=[n for n in data['services'] if n.endswith('-mongodb')]
            assert set(BACKENDS)<=set(names)
            assert len({data['services'][n]['image'] for n in names})==1,'MongoDB images differ'
            for name in names:
                service=data['services'][name]
                assert not any(v.split(':')[1]=='/usr/bin/mongod' for v in service.get('volumes',[]) if isinstance(v,str) and ':' in v)
                service.setdefault('volumes',[]).append(str(binary)+':/usr/bin/mongod:ro')
            changed.extend(names)
        original_save(path,data)
    h.media.save=save
    try:
        yield
        assert changed
        b.save(out/'backend_bindings.json',dict(binary=str(binary),sha256=b.sha(binary),services=changed,
            scope='Same ELF in every MongoDB container; original shared image and bind-mounted inputs unchanged.'))
    finally:h.media.save=original_save

def audit_backends(stack,out,reference=None):
    records={};digests=set();images=set()
    for name,state in stack.states.items():
        if not name.endswith('-mongodb'):continue
        pid=state['State']['Pid'];exe=Path(f'/proc/{pid}/exe')
        assert os.readlink(exe)=='/usr/bin/mongod'
        digest=b.sha(exe);digests.add(digest);images.add(state['Image'])
        stat=exe.stat()
        records[name]=dict(pid=pid,path=os.readlink(exe),sha256=digest,image=state['Image'],
            file_device=stat.st_dev,file_inode=stat.st_ino)
    assert len(digests)==len(images)==1
    if reference is not None:
        assert digests=={b.sha(reference)}
        # Only bind-mounted trials must resolve to the same host-file inode.
        # Original overlay mounts can report different device/inode identities.
        if (out/'backend_bindings.json').exists():
            stat=Path(reference).stat()
            assert {(r['file_device'],r['file_inode']) for r in records.values()}=={(stat.st_dev,stat.st_ino)}
    b.save(out/'backend_runtime.json',records)
    return records

def start_client(out,seconds,seed):
    load=out/'load';load.mkdir()
    command=['python3',Path(__file__).with_name('closed_loop_load.py'),'--out',load,
        '--concurrency','4','--seconds',str(seconds),'--seed',str(seed)]
    b.save(load/'command.json',command)
    with (load/'client.log').open('w') as log:client=subprocess.Popen(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    for _ in range(100):
        if (load/'started.json').exists():return client
        assert client.poll() is None;time.sleep(.1)
    raise RuntimeError('Client startup failed')

def timeline(spec):
    """Measure MongoDB's own switch-age distribution, outside clean timing."""
    from capture_miss_timeline import capture
    from lean_timeline import decode_one,request_window,remove_failed_captures
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),
        scope='Separate MongoDB PEBS + sched_switch diagnostic; profiling latency is not an E2E result.'))
    stack=client=None;captures=[];windows={};reference=Path(spec['reference'])
    try:
        with bind_mongodb(out,spec.get('mongo_binary')):stack=h.start(out,'media',spec['overrides'],8)
        runtime=audit_backends(stack,out,spec.get('mongo_binary') or reference)
        binary=Path(spec.get('mongo_binary') or reference)
        client=start_client(out,150,spec['seed']);time.sleep(50)
        for name in BACKENDS:
            pid=runtime[name]['pid'];maps=Path(f'/proc/{pid}/maps').read_text()
            (out/(name+'.maps')).write_text(maps)
            for period in spec.get('periods',[1021,4093]):
                assert client.poll() is None
                dest=out/f'{name}_p{period}';begin=time.time();capture(dest,pid,period)
                windows[str(dest)]=(begin,time.time());captures.append((dest,binary,maps));time.sleep(3)
        assert client.wait(timeout=210)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text())
        assert not info['steady_errors'] and info['client_cpu_cores']<.8
        with gzip.open(out/'load/requests.json.gz','rt') as f:samples=json.load(f)
        for dest,_,_ in captures:b.save(dest/'request_window.json',request_window(samples,*windows[str(dest)]))
        b.save(out/'load_validation.json',dict(valid=True,load=info))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)
        if (out/'failure.json').exists():remove_failed_captures(out,'Rejected backend timeline: compact quality, error and commands retained.')
    try:
        for dest,binary,maps in captures:decode_one(dest,binary,maps)
    except BaseException as error:
        b.save(out/'decode_failure.json',dict(error=repr(error)))
        remove_failed_captures(out,'Rejected backend timeline decoding: compact quality, error and commands retained.')
        raise
    b.save(out/'complete.json',dict(valid=True,captures=[str(x[0]) for x in captures]))

def profile(spec):
    out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False);b.space(out)
    services=spec.get('services',BACKENDS)
    assert services and len(set(services))==len(services) and all(s.endswith('-mongodb') for s in services)
    b.save(out/'protocol.json',dict(spec,source_sha256=b.sha(__file__),
        scope='Original unmodified MongoDBs in full Media C4; main-ELF retired L2 miss LBR training, no performance claim.'))
    stack=client=None;captures=[]
    try:
        stack=h.start(out,'media',spec['overrides'],8)
        runtime=audit_backends(stack,out)
        reference=Path(spec['reference']);reference.parent.mkdir(parents=True,exist_ok=True)
        source=Path(f"/proc/{runtime[BACKENDS[0]]['pid']}/exe")
        if not reference.exists():
            b.space(reference.parent);shutil.copyfile(source,reference);reference.chmod(0o755)
        assert b.sha(reference)==b.sha(source)
        b.save(reference.with_suffix('.source.json'),dict(path=str(reference),sha256=b.sha(reference),
            bytes=reference.stat().st_size,source_image=runtime[BACKENDS[0]]['image'],source_path='/usr/bin/mongod'))
        client=start_client(out,90,spec['seed']);time.sleep(50)
        for name in services:
            b.space(out);dest=out/name;dest.mkdir();pid=runtime[name]['pid']
            (dest/'maps.txt').write_text(Path(f'/proc/{pid}/maps').read_text())
            group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
            event='cpu/event=0xc6,umask=0x3,config1=0x13,period=257,name=fe_l2/upp'
            command=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M',
                '-e',event,'-j','any,u','-G',group,'-o',str(dest/'perf.data'),'--','sleep','8']
            b.run(command,dest/'record.log')
            assert not re.search(r'\b(lost|truncated|throttled)\b',(dest/'record.log').read_text(),re.I)
            assert client.poll() is None;captures.append(dest)
        assert client.wait(timeout=90)==0;client=None;stack.check()
        info=json.loads((out/'load/load.json').read_text());assert not info['steady_errors'] and info['client_cpu_cores']<.8
        b.save(out/'load_validation.json',dict(valid=True,load=info))
    except BaseException as error:
        b.save(out/'failure.json',dict(error=repr(error)));raise
    finally:
        h.c.stop(client)
        if stack is not None:stack.close()
        h.old.compact(out)
        if (out/'failure.json').exists():
            unused=[out/name/file for name in services for file in ['perf.data','samples.txt'] if (out/name/file).exists()]
            if unused:remove_generated(unused,out/'failed_capture_cleanup.json','Invalid capture; quality, commands, failure and binary/source hashes retained.')
    try:
        for dest in captures:decode(dest)
    except BaseException as error:
        b.save(out/'decode_failure.json',dict(error=repr(error)))
        unused=[dest/file for dest in captures for file in ['perf.data','samples.txt'] if (dest/file).exists()]
        if unused:remove_generated(unused,out/'failed_decode_cleanup.json','Rejected decoder/quality result; commands, quality records and failure retained.')
        raise
    b.save(out/'complete.json',dict(captures=list(map(str,captures)),valid=True))

def observed_rows(folder,code,slots,minimum=64,maximum=8192):
    main='/usr/bin/mongod';pattern=re.compile(r'(?:^|/)mongod$')
    bias=mapping_bias((folder/'maps.txt').read_text(),pattern,code.sections);assert bias is not None
    def ismain(dso):return dso[1:-1] in (main,'mongod')
    old_sites=code.pf_sites;code.pf_sites=sorted(slots);rows=[];quality=collections.Counter()
    classes=collections.Counter();predecessors=collections.Counter();functions=collections.Counter()
    try:
        for line in (folder/'samples.txt').open():
            header=HEADER.match(line)
            if not header:continue
            quality['all_samples']+=1
            if not ismain(header[3]):continue
            ip=int(header[2],16)-bias
            if ip not in code.instructions:quality['not_instruction_boundary']+=1;continue
            quality['main_samples']+=1
            classes[category(code.get(ip)[1])]+=1;functions[code.get(ip)[2]]+=1
            edges=[(int(fr,16)-bias,ismain(fd),int(to,16)-bias,ismain(td),int(cyc) if cyc.isdigit() else None,pred)
                for fr,fd,to,td,pred,cyc,typ in EDGE.findall(line)]
            if edges and edges[0][0]==ip and edges[0][1]:edges=edges[1:]
            if not edges:
                quality['without_prior_lbr']+=1
                rows.append(dict(ip=ip,target=ip,line=ip//64,sites=[],nearest=None,ages=[]))
                continue
            target=edges[0][2] if edges[0][3] and edges[0][2]//64==ip//64 and edges[0][2] in code.instructions else ip
            nearest=None
            if edges[0][3] and 0<=ip-edges[0][2]<=65536 and code.straight(edges[0][2],ip):
                nearest=dict(distance=ip-edges[0][2],source=edges[0][0] if edges[0][1] else None,
                    branch_class=category(code.get(edges[0][0])[1]) if edges[0][1] else 'outside_main',
                    mispredicted=edges[0][5]=='M')
                predecessors[nearest['branch_class']]+=1
                quality['within_64B_of_target']+=nearest['distance']<64
                quality['nearest_branch_mispredicted']+=nearest['mispredicted']
            ages=collections.defaultdict(set);age=0
            for newer,older in zip(edges,edges[1:]):
                if age<=maximum and newer[1] and older[3]:
                    lo,hi=older[2],newer[0]
                    if lo in code.instructions and hi in code.instructions and 0<=hi-lo<=65536 and code.straight(lo,hi):
                        for s in code.sites(lo,hi):
                            if s//64!=target//64:ages[s].add(age)
                if newer[4] is None or newer[4]>=65535:
                    quality['age_missing_or_saturated']+=1;break
                age+=newer[4]
                if age>maximum:quality['age_bound_reached']+=1;break
            sites=sorted(s for s,a in ages.items() if any(minimum<=v<=maximum for v in a))
            rows.append(dict(ip=ip,target=target,line=target//64,sites=sites,nearest=nearest,
                ages=[(s,sorted(a)) for s,a in sorted(ages.items())]))
        quality['eligible_samples']=sum(bool(r['sites']) for r in rows)
        return rows,dict(quality,instruction_classes=dict(classes),preceding_branch_classes=dict(predecessors),
            top_functions=[dict(name=n,samples=v) for n,v in functions.most_common(40)],
            attribution_limitation='Retired IP/nearest taken-target association, not proof of BTB or FDIP causality. All main samples remain in the main-sample denominator.')
    finally:code.pf_sites=old_sites

def padding_variant(source,dest,code,slots,changes):
    assert not dest.exists();original=source.read_bytes();data=bytearray(original);patches=[]
    for row in changes:
        site=row['site'];target=row['target'];off,length=slots[site]
        before=original[off:off+length];assert is_padding_nop(before) and target in code.instructions
        displacement=target-site-length;assert -(1<<31)<=displacement<1<<31
        after=b'\x66'*(length-7)+b'\x0f\x18\x15'+struct.pack('<i',displacement)
        assert len(after)==length;data[off:off+length]=after
        patches.append(dict(site=site,target=target,offset=off,before=before.hex(),after=after.hex()))
    reverse=bytearray(data)
    for p in patches:reverse[p['offset']:p['offset']+len(bytes.fromhex(p['before']))]=bytes.fromhex(p['before'])
    assert bytes(reverse)==original
    dest.parent.mkdir(parents=True,exist_ok=True);b.space(dest.parent);dest.write_bytes(data);dest.chmod(0o755)
    try:
        print(json.dumps(dict(stage='verify_patched_instruction_boundaries',binary=str(dest),patches=len(patches))),flush=True)
        verified=Code(dest)
        for p in patches:
            assert verified.raw_targets[p['site']]==p['target']
            assert verified.instructions[p['site']][0]==code.instructions[p['site']][0]
        assert set(verified.instructions)==set(code.instructions)
    except BaseException as error:
        b.save(dest.with_suffix('.failure.json'),dict(error=repr(error),patches=patches,source_sha256=b.sha(source)))
        remove_generated([dest],dest.with_suffix('.cleanup.json'),'Generated ELF failed post-patch validation; patch/source/error records retained.')
        raise
    b.save(dest.with_suffix('.patches.json'),dict(source=str(source),source_sha256=b.sha(source),sha256=b.sha(dest),
        code_size_unchanged=True,instruction_boundaries_unchanged=True,patches=patches,
        original_software_prefetches_untouched=True,fully_reversible=True))

def prepare(spec):
    root=Path(spec['root']);source=Path(spec['reference']);b.space(root)
    b.save(root/'prepare_protocol.json',dict(spec,source_sha256=b.sha(__file__),
        decoder_sha256=b.sha(Path(__file__).with_name('dense_cause_analysis.py')),
        selector_sha256=b.sha(Path(__file__).with_name('residual_retarget.py')),binary_sha256=b.sha(source)))
    print(json.dumps(dict(stage='disassemble_original',binary=str(source),bytes=source.stat().st_size)),flush=True)
    code=Code(source);raw=source.read_bytes();slots={}
    for site,(length,asm,_) in code.instructions.items():
        if not 7<=length<=15 or not re.search(r'\bnop[wl]?\b',asm):continue
        sec=next((s for s in code.sections if s[0]<=site and site+length<=s[0]+s[2]),None)
        if sec is None:continue
        off=sec[1]+site-sec[0]
        if is_padding_nop(raw[off:off+length]):slots[site]=(off,length)
    assert slots
    print(json.dumps(dict(stage='original_decoded',instructions=len(code.instructions),padding_slots=len(slots))),flush=True)
    train=[];heldout=[];quality={};obsolete=[]
    for phase in ['train','heldout']:
        for name in BACKENDS:
            folder=root/'profiles'/phase/name
            rows,counts=observed_rows(folder,code,slots)
            recorded=json.loads((folder/'record_types.json').read_text()).get('SAMPLE',0)
            assert counts.get('all_samples',0)==recorded and recorded>100,(folder,counts.get('all_samples',0),recorded)
            (train if phase=='train' else heldout).extend(rows);quality[phase+':'+name]=counts
            path=root/'observations'/(phase+'_'+name+'.json.gz');path.parent.mkdir(exist_ok=True)
            with gzip.open(path,'wt') as f:json.dump(rows,f,separators=(',',':'))
            quality[phase+':'+name].update(trace_sha256=b.sha(folder/'samples.txt'),observations_sha256=b.sha(path))
            obsolete.append(folder/'samples.txt')
            print(json.dumps(dict(stage='observations',phase=phase,service=name,all_samples=counts['all_samples'],main_samples=counts['main_samples'],eligible_samples=counts['eligible_samples'])),flush=True)
    b.save(root/'profile_quality.json',dict(records=quality,source_sha256=b.sha(source),nop_slots=len(slots)))
    remove_generated(obsolete,root/'decoded_cleanup.json','All train/heldout compact observations and quality extracted; exact selector inputs retained, decoded copies no longer needed.')
    result=plan(train,{s:0 for s in slots},max_fraction=min(1,256/len(slots)),min_gain=3)
    assert result['changes'],'No safe, observed executed padding sites; do not invent placements'
    selected={c['site']:c['target']//64 for c in result['changes']}
    result.update(heldout_samples=len(heldout),heldout_covered=sum(any(selected.get(s)==r['line'] for s in r['sites']) for r in heldout),
        quality=quality,nop_slots=len(slots),source_sha256=b.sha(source),minimum_age=64,maximum_age=8192,
        train_all_samples=sum(v['all_samples'] for k,v in quality.items() if k.startswith('train:')),
        heldout_all_samples=sum(v['all_samples'] for k,v in quality.items() if k.startswith('heldout:')),
        lead_limitation='Completed retired LBR age, no within-segment interpolation; not actual issue-to-fetch time.')
    dest=root/'builds/mongo256/mongod';b.save(dest.with_suffix('.plan.json'),result)
    print(json.dumps(dict(stage='plan',patches=len(result['changes']),train_covered=result['final_covered'],heldout_covered=result['heldout_covered'],heldout_samples=len(heldout))),flush=True)
    padding_variant(source,dest,code,slots,result['changes'])
    b.save(root/'prepared.json',dict(binary=str(dest),reference=str(source),patches=len(result['changes']),
        train_covered=result['final_covered'],train_main_samples=len(train),train_all_samples=result['train_all_samples'],
        heldout_covered=result['heldout_covered'],heldout_main_samples=len(heldout),heldout_all_samples=result['heldout_all_samples']))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['profile','prepare','timeline']);p.add_argument('spec',type=Path);a=p.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);globals()[a.action](json.loads(a.spec.read_text()))
