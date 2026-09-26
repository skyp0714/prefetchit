#!/usr/bin/env python3
"""Selected-next-task emission experiments with matched paths and clean ROI."""
import argparse
import fcntl
import gzip
import json
import os
from pathlib import Path
import random
import subprocess
import time

import fullset as h
from fullset_study import metrics, summarize


def variants(key):
    root=h.OUT/'plans'/key
    report=json.loads((root/'strict/training_report.json').read_text())
    plan=json.loads((root/'strict/kernel32.json').read_text())
    for profile,details in zip(plan['profiles'],report['policies']['32']['details']):
        order=sorted(range(len(details['targets'])),key=lambda i:details['targets'][i]['mean_rank'])
        profile['targets']=[profile['targets'][i] for i in order]
    first=root/'first_order32.json';h.c.save(first,plan)
    result={f'b{n}':dict(plan=str(root/f'strict/kernel{n}.json'),options={}) for n in (8,16,32,64)}
    for name,options in {
        'space4':dict(spacing=4,group=1),
        'space16':dict(spacing=16,group=1),
        'group4':dict(spacing=16,group=4),
        'split8':dict(split_after=8),
        'group4_t0':dict(spacing=16,group=4,hint='t0'),
        'split8_t0':dict(split_after=8,hint='t0'),
    }.items():result[name]=dict(plan=str(root/'strict/kernel32.json'),options=options)
    result['split16_64']=dict(plan=str(root/'strict/kernel64.json'),options=dict(split_after=16))
    result['first_space']=dict(plan=str(first),options=dict(spacing=4,group=1))
    result['wide_split']=dict(plan=str(root/'wide/kernel64.json'),options=dict(split_after=16,spacing=16,group=4))
    return result


def sequence(spec):
    h.c.space();out=Path(spec['out']);out.mkdir(parents=True,exist_ok=False)
    h.c.save(out/'protocol.json',dict(**spec,module_sha256=h.c.sha(h.REPO/'llvm_prefetchit/kernel/wake_prefetch/wake_prefetch.ko'),
        nop_module_sha256=h.c.sha(h.REPO/'llvm_prefetchit/kernel/wake_prefetch/wake_prefetch_nop.ko'),
        nop_control='Same-layout whole-module NOP twin; both modules run mode=1 and the same branches. Only three prefetch opcodes in emit are replaced.',
        diagnostic_exclusion='Any phase with diagnostic!=0 is excluded from CPU performance claims',
        phase_transition='Close registration, unload module, set next arm, settle; no builds or transfers'))
    family=spec['family'];key=spec['service'];name=h.TARGETS[family][key][0]
    module=h.REPO/'llvm_prefetchit/kernel/wake_prefetch/wake_prefetch.ko'
    stack=client=None;fd=None;loaded=False;windows=[]
    try:
        stack=h.start(out,family,{},spec['pool'])
        pid=stack.states[name]['State']['Pid']
        group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
        roi=spec.get('roi_s',20);settle=spec.get('settle_s',8);pmu_s=spec.get('pmu_s',10)
        seconds=65+len(spec['order'])*(roi+settle+pmu_s+2)
        client=h.load(out/'load',family,h.RATE[family],spec['seed'],seconds)
        time.sleep(50)
        for index,arm in enumerate(spec['order']):
            h.c.space();setting=spec['arms'][arm];dest=out/f'{index:02d}_{arm}';dest.mkdir()
            if fd is not None:os.close(fd);fd=None
            if loaded:subprocess.run(['rmmod','wake_prefetch'],check=True);loaded=False
            if setting.get('mode','off')!='off':
                selected_module=module.with_name('wake_prefetch_nop.ko') if setting['mode']=='nop' else module
                subprocess.run(['insmod',str(selected_module)],check=True);loaded=True
                if setting['mode']!='empty':
                    plan=json.loads(Path(setting['plan']).read_text())
                    profiles,audit=h.old.control.resolve(plan,pid)
                    fd=os.open('/dev/wake_prefetch',os.O_RDWR|os.O_CLOEXEC)
                    fcntl.ioctl(fd,h.old.control.CONFIG_IOCTL,h.old.control.pack_config(pid,
                        1,profiles,**setting.get('options',{})),True)
                    h.c.save(dest/'registration.json',dict(profiles=profiles,audit=audit,settings=setting,
                        plan_sha256=h.c.sha(setting['plan']),actual_config_mode=1,module_sha256=h.c.sha(selected_module)))
            time.sleep(settle);assert client.poll() is None
            kb=h.old.control.stats(fd) if fd is not None else None
            db=h.old.control.detail(fd) if fd is not None else None
            before=stack.accounts();pb=h.old.pool_cpu(set(range(32,32+spec['pool'])))
            time.sleep(roi)
            pa=h.old.pool_cpu(set(range(32,32+spec['pool'])));after=stack.accounts()
            ka=h.old.control.stats(fd) if fd is not None else None
            da=h.old.control.detail(fd) if fd is not None else None
            window=dict(arm=arm,index=index,costs={n:h.c.diff_cpu(before[n],after[n]) for n in before},
                pool=dict(start=pb['epoch'],end=pa['epoch'],wall_s=pa['monotonic']-pb['monotonic'],
                    cpu_us=sum(pa['ticks'][k]-v for k,v in pb['ticks'].items())*1e6/pb['clock_ticks']),
                kernel_before=kb,kernel_after=ka,detail_before=db,detail_after=da,pmu=None)
            if pmu_s:
                before=h.c.cpu(pid)
                h.c.run(['perf','stat','-x,','-o',dest/'pmu.csv','-e',h.c.EVENTS,'-a','-C','32-45','-G',group,
                         '--','sleep',str(pmu_s)],dest/'pmu.log')
                window['pmu']=dict(**h.c.counters(dest/'pmu.csv'),window=h.c.diff_cpu(before,h.c.cpu(pid)))
            windows.append(window);h.c.save(dest/'windows.json',window);stack.check()
        if fd is not None:os.close(fd);fd=None
        if loaded:subprocess.run(['rmmod','wake_prefetch'],check=True);loaded=False
        assert client.wait(timeout=120)==0;client=None
        info=json.loads((out/'load/load.json').read_text())
        with gzip.open(out/'load/requests.json.gz','rt') as f:samples=json.load(f)
        rows=[]
        for w in windows:
            for cost in w['costs'].values():h.old.attach(cost,samples)
            h.old.attach(w['pool'],samples)
            valid=not info['steady_errors'] and not info['steady_drops']
            for cost in w['costs'].values():
                valid &= abs(cost['achieved_rps']/h.RATE[family]-1)<.04 and cost['p99_ms']<100
            if w['kernel_after']:
                valid &= w['kernel_after']['matched_switches']>w['kernel_before']['matched_switches']
                options=spec['arms'][w['arm']].get('options',{})
                if options.get('split_after'):
                    valid &= w['detail_after']['second_switches']>w['detail_before']['second_switches']
            pmu=w['pmu']
            if pmu:
                h.old.attach(pmu['window'],samples);n=pmu['window']['completed']
                pmu.update(user_cycles_per_request=pmu['counters']['cycles:u']/n,code_misses_per_request=pmu['counters']['L2I']/n)
                valid &= pmu['fully_scheduled'] and abs(pmu['window']['achieved_rps']/h.RATE[family]-1)<.04
            result=dict(whole_stack_cpu_us_per_request=sum(v['cpu_us'] for v in w['costs'].values())/w['pool']['completed'],
                pool=w['pool'],services={k:dict(cpu=w['costs'][v[0]],pmu=pmu if k==key else None) for k,v in h.TARGETS[family].items()})
            row=dict(arm=w['arm'],block=spec.get('block',0),valid=bool(valid),metrics=metrics(result),
                output=str(out/f"{w['index']:02d}_{w['arm']}"),diagnostic=bool(spec['arms'][w['arm']].get('options',{}).get('diagnostic')))
            h.c.save(Path(row['output'])/'result.json',dict(**row,windows=w));rows.append(row)
        h.c.save(out/'rows.json',rows);h.c.save(out/'complete.json',dict(all_valid=all(r['valid'] for r in rows),rows=rows,load=info))
        print(json.dumps(dict(out=str(out),rows=rows)),flush=True)
    finally:
        h.c.stop(client)
        if fd is not None:os.close(fd)
        if loaded:subprocess.run(['rmmod','wake_prefetch'],check=True)
        if stack is not None:stack.close()
        if (out/'complete.json').exists():h.old.compact(out)


def run_sequence(spec):
    out=Path(spec['out']);manifest=out.with_suffix('.json');h.c.save(manifest,spec)
    h.platform(out,['python3',Path(__file__),'sequence',manifest])
    return json.loads((out/'rows.json').read_text())


def campaign():
    h.c.space()
    module=h.REPO/'llvm_prefetchit/kernel/wake_prefetch'
    original=module/'wake_prefetch.ko';nop=module/'wake_prefetch_nop.ko'
    assert not nop.exists()
    h.c.run(['objdump','-d','--disassemble=emit',original],h.OUT/'kernel_emit_disassembly.log')
    h.c.run(['python3',h.REPO/'llvm_prefetchit/tools/make_nop_control_binary.py',
             '--input',original,'--output',nop,'--symbol','emit','--mnemonics','prefetcht0,prefetcht1,prefetchnta'],
            h.OUT/'kernel_nop_build.log')
    before=original.read_bytes();after=nop.read_bytes();assert len(before)==len(after)
    differences=[dict(offset=i,before=a,after=b) for i,(a,b) in enumerate(zip(before,after)) if a!=b]
    assert len(differences)==6,differences
    h.c.save(h.OUT/'kernel_nop_audit.json',dict(original_sha256=h.c.sha(original),nop_sha256=h.c.sha(nop),
        equal_size=True,differences=differences,scope='Three 3-byte prefetch instructions in emit changed to equal-length NOPs; all other bytes identical'))
    h.c.run(['taskset','-c','84-85','python3',module/'smoke.py','--module',nop,'--out',h.OUT/'kernel_nop_smoke'],
            h.OUT/'kernel_nop_smoke.log')
    finalists=[]
    for family,key in [('media','movie'),('social','usertimeline')]:
        selected=json.loads((h.OUT/(family+'_selection.json')).read_text());pool=selected['pool']
        base=h.OUT/'kernel_emission'/key;variants_by_name=variants(key)
        arms={'off':dict(mode='off'),'empty':dict(mode='empty')};order=['off','empty']
        names=list(variants_by_name);random.Random(17001).shuffle(names)
        for i,name in enumerate(names):
            variant=variants_by_name[name]
            arms[name+'_nop']=dict(**variant,mode='nop',controls=['off'])
            arms[name]=dict(**variant,mode='t1',controls=['off',name+'_nop'])
            pair=[name+'_nop',name]
            if i%2:pair.reverse()
            order+=pair
        rows=run_sequence(dict(out=str(base/'screen'),family=family,service=key,pool=pool,seed=17001,
            arms=arms,order=order,roi_s=20,settle_s=8,pmu_s=10))
        summary=summarize(rows,arms);h.c.save(base/'screen_summary.json',summary)
        eligible=[]
        for name,variant in variants_by_name.items():
            comparisons=summary.get(name,{})
            if all(key+'_cpu' in comparisons.get(control,{}) for control in ('off',name+'_nop')):
                score=min(comparisons[control][key+'_cpu']['cost_reduction_pct'] for control in ('off',name+'_nop'))
                eligible.append(dict(family=family,service=key,pool=pool,name=name,variant=variant,score=score,summary=comparisons))
        assert eligible;best=max(eligible,key=lambda r:r['score']);finalists.append(best)
        h.c.save(base/'selection.json',dict(best=best,candidates=eligible,
            rule='Highest minimum target CPU saving against module-off and matching NOP, single-block exploratory only. Confirm independently even when screen gains are nonpositive.'))
        # Separate pre/post diagnostic sessions prevent the pre-load from warming
        # the line used in post measurements. Diagnostics are never pooled.
        diagnostic={}
        for phase in (1,2):
            for mode in ('nop','t1'):
                settings=best['variant'];options=dict(settings['options'],diagnostic=phase)
                diagnostic[f'd{phase}_{mode}']=dict(plan=settings['plan'],options=options,mode=mode)
        run_sequence(dict(out=str(base/'diagnostic'),family=family,service=key,pool=pool,seed=17501,
            arms=diagnostic,order=list(diagnostic),roi_s=30,settle_s=8,pmu_s=0))
    best=max(finalists,key=lambda r:r['score'])
    h.c.save(h.OUT/'kernel_emission/frozen_finalist.json',dict(selected=best,finalists=finalists,
        confirmation='Seven new baseline processes; within each, rotate module-off, matching-NOP and candidate. No screen data pooled.'))
    arms={'off':dict(mode='off'),'nop':dict(**best['variant'],mode='nop',controls=['off']),
          'candidate':dict(**best['variant'],mode='t1',controls=['off','nop'])}
    all_rows=[]
    for block in range(7):
        names=list(arms);order=names[block%3:]+names[:block%3]
        if block//3%2:order.reverse()
        for attempt in range(3):
            label=f'{block:02d}' if attempt==0 else f'{block:02d}_retry{attempt}'
            rows=run_sequence(dict(out=str(h.OUT/'kernel_emission/confirmation'/label),
                family=best['family'],service=best['service'],pool=best['pool'],seed=18001+block,block=block,
                arms=arms,order=order,roi_s=30,settle_s=10,pmu_s=0,
                invalid='Reject and repeat the entire block if any operating gate fails; maximum two retries, never based on performance.'))
            if all(row['valid'] for row in rows):
                all_rows+=rows;break
            for row in rows:
                row.update(valid=False,exclusion='Entire block excluded because at least one operating gate failed')
            all_rows+=rows
            h.c.save(h.OUT/'kernel_emission/confirmation_rows.json',all_rows)
        else:raise RuntimeError(f'Kernel confirmation block {block} invalid after three attempts')
        h.c.save(h.OUT/'kernel_emission/confirmation_rows.json',all_rows)
        h.c.save(h.OUT/'kernel_emission/confirmation_summary.json',summarize(all_rows,arms))
    summary=summarize(all_rows,arms)
    target=[summary.get('candidate',{}).get(control,{}).get(best['service']+'_cpu',{}) for control in ('off','nop')]
    pool=summary.get('candidate',{}).get('off',{}).get('pool_cpu',{})
    promoted=all(r.get('pairs')==7 and r.get('ci95_pct',[-1])[0]>0 for r in [*target,pool])
    h.c.save(h.OUT/'kernel_emission/complete.json',dict(selected=best,summary=summary,promoted=promoted,
        promotion='Positive individual 95% lower bounds for target CPU vs module-off and matching NOP, plus pool CPU vs module-off; seven valid independent process blocks.'))
    # Functional cache-fill check is separate from all application CPU windows.
    probe=h.OUT/'kernel_cache_probe'
    h.platform(probe,['python3',h.REPO/'llvm_prefetchit/kernel/wake_prefetch/cache_probe.py','--out',probe,'--cpu','42'])
    module=h.REPO/'llvm_prefetchit/kernel/wake_prefetch'
    generated=[]
    for p in module.iterdir():
        if p.is_file() and not p.is_symlink() and (p.suffix in ('.o','.ko','.mod','.cmd') or p.name in ('wake_prefetch.mod.c','modules.order','Module.symvers')):
            if promoted and p.suffix=='.ko':continue
            generated.append(dict(path=str(p),bytes=p.stat().st_size,sha256=h.c.sha(p)))
    import shutil
    result=dict(reason='Kernel comparison complete; keep module executable only if promoted. Source, options, hashes, tests and all negative outcomes retained.',
        files=generated,free_before=shutil.disk_usage(module).free)
    h.c.save(h.OUT/'kernel_build_cleanup.json',result)
    for row in generated:Path(row['path']).unlink()
    result.update(bytes_removed=sum(r['bytes'] for r in generated),free_after=shutil.disk_usage(module).free)
    h.c.save(h.OUT/'kernel_build_cleanup.json',result)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['sequence','campaign'])
    p.add_argument('manifest',nargs='?',type=Path);a=p.parse_args()
    if a.action=='sequence':sequence(json.loads(a.manifest.read_text()))
    else:campaign()


if __name__=='__main__':main()
