#!/usr/bin/env python3
"""Extend the joint Media policy to measured shared-library code misses."""
import argparse
import collections
from contextlib import contextmanager
import gzip
import json
from pathlib import Path
import re
import shutil
import signal
import struct
import time

import dense_build as b
import fullset as h
import balanced_backend as balanced
from backend_prefetch import bind_mongodb, observed_rows
from call_cost_selector import select
from callpath_prefetch import coverage, stubs
from dense_cause_analysis import Code, HEADER, category, mapping_bias
from dense_causes import decode
from e2e_lbr import remove_generated
from lean_timeline import request_window
import media_system_study as system


@contextmanager
def bind_libraries(out,spec):
    mappings=spec.get('libraries',{});original=h.media.save
    def save(path,data):
        if path==out/'compose.json':
            for key,paths in mappings.items():
                name=system.NATIVE[key][0];service=data['services'][name]
                for target,source in paths.items():
                    source=Path(source);assert source.is_file() and not str(source.resolve()).startswith('/fast-lab-share/')
                    assert not any(v.split(':')[1]==target for v in service.get('volumes',[]))
                    service.setdefault('volumes',[]).append(str(source)+':'+target+':ro')
        original(path,data)
    h.media.save=save
    try:yield
    finally:h.media.save=original


def audit_libraries(stack,out,spec):
    identities={}
    for key,paths in spec.get('libraries',{}).items():
        pid=stack.states[system.NATIVE[key][0]]['State']['Pid']
        maps=Path(f'/proc/{pid}/maps').read_text()
        identities[key]={}
        for target,source in paths.items():
            mapped=[line for line in maps.splitlines() if len(line.split())>=6 and line.split()[-1]==target and 'x' in line.split()[1]]
            assert mapped,(key,target)
            actual=Path(f'/proc/{pid}/root')/target.lstrip('/')
            assert b.sha(actual)==b.sha(source),(key,target)
            identities[key][target]=dict(source=source,sha256=b.sha(source),maps=mapped)
    b.save(out/'library_runtime.json',identities)


def capture(spec):
    system.configure();root=Path(spec['root']);settings=system.verify(root);phase=spec['phase']
    out=root/'libraries/profiles'/phase;out.mkdir(parents=True,exist_ok=False);b.space(out)
    kinds=['miss','calls'] if phase=='train' else ['miss'];catalog={};captures=[];windows={};stack=client=None
    b.save(out/'protocol.json',dict(spec,kinds=kinds,source_sha256=b.sha(__file__),
        rule='Original binaries and original DSOs only; independent fresh training/heldout stacks. Decode and selection after shutdown.'))
    try:
        with bind_mongodb(out,settings['mongo_original']):stack=h.start(out,'media',settings['references'],8)
        runtime=system.audit_native(stack,out,settings['references'])
        for key,record in runtime.items():
            pid=record['pid'];entries={}
            for line in Path(f'/proc/{pid}/maps').read_text().splitlines():
                fields=line.split()
                if len(fields)!=6 or 'x' not in fields[1] or not fields[-1].startswith('/') or '.so' not in fields[-1]:continue
                path=fields[-1];source=Path(f'/proc/{pid}/root')/path.lstrip('/');digest=b.sha(source)
                local=root/'libraries/references'/digest/Path(path).name
                if not local.exists():
                    b.space(root);local.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,local);local.chmod(0o755)
                assert b.sha(local)==digest
                entries[path]=dict(binary=str(local),sha256=digest,bytes=local.stat().st_size)
            catalog[key]=entries
        b.save(out/'catalog.json',catalog)
        seconds=70+len(system.NATIVE)*len(kinds)*10
        client=balanced.start_client(out,seconds,spec['seed']);time.sleep(50)
        for kind in kinds:
            for key in system.NATIVE:
                b.space(root);dest=out/key/kind;dest.mkdir(parents=True);pid=runtime[key]['pid']
                (dest/'maps.txt').write_text(Path(f'/proc/{pid}/maps').read_text())
                group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                command=['perf','record','--no-buildid','--no-buildid-cache','-a','-C','32-39','-m','8M','-e',
                    system.MISS_EVENT if kind=='miss' else system.CALL_EVENT,'-j','any,u','-G',group,'-o',dest/'perf.data','--','sleep','8']
                a=time.time();b.run(command,dest/'record.log');windows[str(dest)]=(a,time.time())
                assert not re.search(r'\b(lost|truncated|throttled)\b',(dest/'record.log').read_text(),re.I)
                assert client.poll() is None;captures.append(dest)
                print(json.dumps(dict(stage='library_capture',phase=phase,kind=kind,service=key)),flush=True)
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
            if unused:remove_generated(unused,out/'failure_cleanup.json','Rejected library capture; identities, commands, failure and raw hashes retained.')
    try:
        for dest in captures:decode(dest)
    except BaseException as error:
        b.save(out/'decode_failure.json',dict(error=repr(error)))
        unused=[p for p in out.glob('*/*/*') if p.name in ['perf.data','samples.txt']]
        if unused:remove_generated(unused,out/'decode_failure_cleanup.json','Invalid decode; quality, error and hashes retained.')
        raise
    b.save(out/'complete.json',dict(valid=True,captures=list(map(str,captures))))


def dso_counts(folder,catalog):
    counts=collections.Counter();weighted=collections.Counter();all_samples=0
    requests=json.loads((folder/'request_window.json').read_text())['completed_requests']
    names={Path(path).name:path for path in catalog};assert len(names)==len(catalog)
    for line in (folder/'samples.txt').open():
        match=HEADER.match(line)
        if not match:continue
        all_samples+=1;dso=match[3][1:-1];path=dso if dso in catalog else names.get(Path(dso).name)
        counts[path or dso]+=1
        if path:weighted[catalog[path]['sha256']]+=257/requests
    assert all_samples==json.loads((folder/'record_types.json').read_text())['SAMPLE']
    b.save(folder/'dso_distribution.json',dict(counts=dict(counts),all_samples=all_samples,requests=requests,decoded_sha256=b.sha(folder/'samples.txt')))
    return weighted


def frequency(folder,code,path):
    bias=mapping_bias((folder/'maps.txt').read_text(),re.compile(r'(?:^|/)'+re.escape(Path(path).name)+r'$'),code.sections);assert bias is not None
    counts=collections.Counter();ips=collections.Counter()
    for line in (folder/'samples.txt').open():
        match=HEADER.match(line)
        if not match or match[3][1:-1] not in (path,Path(path).name):continue
        ip=int(match[2],16)-bias;counts[category(code.get(ip)[1])]+=1;ips[ip]+=1
    requests=json.loads((folder/'request_window.json').read_text())['completed_requests']
    rates={ip:n*4093/requests for ip,n in ips.items() if category(code.get(ip)[1])=='direct_call'}
    return rates,3*4093/requests,dict(counts=dict(counts),histogram=dict(ips),requests=requests,period=4093)


def prepare(root):
    libroot=root/'libraries';b.space(root)
    catalogs={phase:json.loads((libroot/'profiles'/phase/'catalog.json').read_text()) for phase in ['train','heldout']}
    assert catalogs['train']==catalogs['heldout'],'Shared library identities changed between fresh stacks'
    catalog=catalogs['train'];ranking=collections.Counter();representatives={};users=collections.defaultdict(dict)
    for key,paths in catalog.items():
        ranking.update(dso_counts(libroot/'profiles/train'/key/'miss',paths))
        dso_counts(libroot/'profiles/heldout'/key/'miss',paths)
        for path,entry in paths.items():representatives[entry['sha256']]=dict(entry,path=path);users[entry['sha256']][key]=path
    total=sum(ranking.values());selected=[digest for digest,n in ranking.most_common() if n>=.005*total]
    policy=dict(weighted_misses_per_request=dict(ranking),selected=selected,
        rule='All DSOs contributing >=0.5% of the aggregate native-library retired-L2 sample weight, train only. <=256 sites/1024 hints/DSO, <=4/site, >=8 samples, 65% model coverage. No performance-based selection.',
        continuation_model='For a sampled instruction spanning a cache line, target the next instruction in the second line; same modeled continuation rule as MongoDB split75, not a measured fetch address.',
        source_sha256=b.sha(__file__),builder_sha256=b.sha(stubs.__file__))
    b.save(libroot/'selection_protocol.json',policy);candidates={};excluded={};summaries={}
    for digest in selected:
        entry=representatives[digest];reference=Path(entry['binary']);name=reference.name;dest=libroot/'plans'/digest;dest.mkdir(parents=True)
        if name.startswith('ld-linux'):
            excluded[digest]='Dynamic loader bootstrap excluded from binary rewriting';continue
        code=Code(reference);raw=reference.read_bytes();elf=stubs.Elf(raw);calls={}
        if not any(p[0]==stubs.EH_FRAME for p in elf.ph):
            excluded[digest]='No supported unwind header';del code;continue
        for site,(length,asm,_) in code.instructions.items():
            if length!=5 or category(asm)!='direct_call':continue
            off=elf.offset(site,5,True)
            if raw[off]!=0xe8:continue
            callee=site+5+struct.unpack_from('<i',raw,off+1)[0]
            if callee in code.instructions:calls[site]=dict(site=site,callee=callee,expected=raw[off:off+5].hex())
        phases={};quality={};rates=collections.Counter();floor=0;freq={}
        for phase in ['train','heldout']:
            aggregate=[]
            for key,path in users[digest].items():
                folder=libroot/'profiles'/phase/key/'miss';rows,counts=observed_rows(folder,code,calls,main=path)
                requests=json.loads((folder/'request_window.json').read_text())['completed_requests']
                for row in rows:
                    length=code.get(row['ip'])[0]
                    if row['ip']//64!=(row['ip']+length-1)//64:
                        target=row['ip']+length
                        if target in code.instructions:row.update(target=target,line=target//64)
                    row['miss_weight']=257/requests
                aggregate.extend(rows);quality[phase+':'+key]=counts
                if phase=='train':
                    r,f,q=frequency(libroot/'profiles/train'/key/'calls',code,path);rates.update(r);floor+=f;freq[key]=q
            phases[phase]=aggregate
            observation=libroot/'observations'/digest/(phase+'.json.gz');observation.parent.mkdir(parents=True,exist_ok=True)
            with gzip.open(observation,'wt') as stream:json.dump(aggregate,stream,separators=(',',':'))
        b.save(dest/'frequency.json',dict(records=freq,rates=dict(rates),floor=floor))
        freq_counts=collections.Counter()
        for record in freq.values():freq_counts.update(record['counts'])
        count=sum(freq_counts.values());valid=count>100 and (freq_counts['direct_call']+freq_counts['indirect_call'])/count>=.99
        if not valid:
            excluded[digest]=dict(reason='Insufficient or misaligned near-call samples',counts=dict(freq_counts));del code;continue
        chosen=select(phases['train'],rates,floor,max_sites=256,max_hints=1024,goal=.65)
        chosen.update(heldout=coverage(phases['heldout'],chosen['choices']),quality=quality)
        b.save(dest/'selection.json',chosen)
        if not chosen['sites']:
            excluded[digest]='No eligible direct-call placements';del code;continue
        grouped=collections.defaultdict(list)
        for row in chosen['choices']:grouped[row['site']].append(row['target'])
        plan=dict(sha256=digest,calls=[dict(calls[site],targets=targets) for site,targets in sorted(grouped.items())]);b.save(dest/'plan.json',plan)
        binary=libroot/'builds'/digest/name;b.space(root)
        record=stubs.build(reference,plan,binary,boundaries=code.instructions);del code
        verified=Code(binary);assert all(verified.raw_targets[x['va']]==x['target'] for x in record['hints']);del verified
        candidates[digest]=dict(binary=str(binary),nop=str(binary)+'.nop',sha256=record['sha256'],nop_sha256=record['nop_sha256'],users=users[digest],name=name)
        summaries[digest]=dict(name=name,sites=chosen['sites'],hints=chosen['hints'],extra_instruction_bytes=record['extra_instruction_bytes'],
            train_coverage=chosen['covered']/chosen['samples'],heldout_coverage=chosen['heldout']['covered']/chosen['heldout']['samples'],
            estimated_hints_per_request=chosen['estimated_hint_executions_per_request'],weighted_baseline_misses_per_request=ranking[digest])
        b.save(libroot/'prepared_pending.json',dict(candidates=candidates,summaries=summaries,excluded=excluded))
        print(json.dumps(dict(stage='library_prepared',**summaries[digest])),flush=True)
    # Retain every DSO's frequency histogram, including excluded/unselected ones,
    # before removing decoded copies. This supports future coverage analysis.
    for phase in ['train','heldout']:
        for key in system.NATIVE:
            for kind in (['miss','calls'] if phase=='train' else ['miss']):
                folder=libroot/'profiles'/phase/key/kind
                if kind=='calls':
                    histogram=collections.Counter()
                    for line in (folder/'samples.txt').open():
                        match=HEADER.match(line)
                        if match:histogram[match[3]]+=1
                    b.save(folder/'all_dso_sample_counts.json',dict(histogram))
                remove_generated([folder/'samples.txt'],folder/'decoded_cleanup.json','Per-library observations, selected frequencies, full DSO counts, commands and quality retained.')
    result=dict(candidates=candidates,summaries=summaries,excluded=excluded,ranking=dict(ranking),references=representatives)
    b.save(libroot/'prepared.json',result)
    prior=json.loads((root/'prepared.json').read_text());b.save(root/'main_only_prepared.json',prior)
    mappings={kind:{key:{} for key in system.NATIVE} for kind in ['binary','nop']}
    for entry in candidates.values():
        for key,path in entry['users'].items():
            for kind in mappings:mappings[kind][key][path]=entry[kind]
    prior['arms']['combined']['libraries']=mappings['binary'];prior['arms']['combined_nop']['libraries']=mappings['nop']
    prior['library_summary']=summaries
    prior['limitation']='Nine main ELF policies plus selected shared DSOs in all nine native servers; original infrastructure and kernel code. '+system.LIMIT
    b.save(root/'prepared.json',prior)


def run(root):
    libroot=root/'libraries';libroot.mkdir(exist_ok=False);b.space(root)
    b.save(libroot/'protocol.json',dict(source_sha256=b.sha(__file__),main_prepared_sha256=b.sha(root/'prepared.json'),
        scope='Extend main-only preparation before any clean endpoint trials; independent DSO train/heldout captures.'))
    for phase,seed in [('train',929201),('heldout',929202)]:
        manifest=libroot/(phase+'_spec.json');b.save(manifest,dict(root=str(root),phase=phase,seed=seed))
        h.platform(libroot/phase,['python3',Path(__file__),'capture',manifest])
    prepare(root)
    prepared=json.loads((root/'prepared.json').read_text());out=root/'library_smoke';manifest=root/'library_smoke_spec.json'
    b.save(manifest,dict(prepared['arms']['combined'],out=str(out),seed=930002))
    h.platform(out,['python3',Path(system.__file__),'smoke',manifest])
    system.campaign(root);system.diagnostics(root)
    b.save(root/'complete.json',dict(valid=True,clean_trials=16,diagnostic_runs=6,shared_libraries=len(prepared['library_summary'])))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['run','capture','prepare']);p.add_argument('path',type=Path);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda sig,frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    if a.action=='capture':capture(json.loads(a.path.read_text()))
    else:globals()[a.action](a.path)
