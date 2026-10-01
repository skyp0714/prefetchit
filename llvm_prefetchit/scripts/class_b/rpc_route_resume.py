#!/usr/bin/env python3
"""Preserve an interrupted cohort and confirm frozen RPC policies after reboot."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import dense_build as b
from rpc_route_study import load
from rpc_route_finish import run


def recover(root):
    assert os.geteuid()==0
    b.space(root)
    old=root/'confirmation';archived=root/'interrupted_confirmation'
    assert old.exists() and not archived.exists() and not (old/'complete.json').exists()
    protocol=load(old/'protocol.json');rows=load(old/'rows.json')
    assert len(rows)==8 and all(row['valid'] for row in rows)
    unfinished=old/'01_rpc_worker'
    assert not (unfinished/'result.json').exists()
    started=load(unfinished/'load/started.json')['epoch']
    boot=int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))
    assert boot>started
    for path,digest in protocol['source_hashes'].items():assert b.sha(path)==digest,path
    for path,digest in protocol['binary_hashes'].items():assert b.sha(path)==digest,path
    project='codex-b-fullset-media'
    ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],text=True).split()
    states=json.loads(subprocess.check_output(['docker','inspect','--size',*ids],text=True)) if ids else []
    assert states and all(not state['State']['Running'] for state in states)
    volumes={m['Name']:m['Source'] for state in states for m in state['Mounts'] if m['Type']=='volume'}
    volume_records=[]
    for name,path in volumes.items():
        assert path.startswith('/var/lib/docker/volumes/') and not Path(path).is_symlink()
        size=sum(p.stat().st_size for base,dirs,files in os.walk(path,followlinks=False)
                 for n in files if not (p:=Path(base,n)).is_symlink())
        volume_records.append(dict(name=name,path=path,bytes=size))
    record=dict(epoch=time.time(),boot_epoch=boot,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        interrupted_trial_started=started,completed_trials_retained=len(rows),
        reason='Host reboot after unfinished trial; preserve all eight completed endpoints but exclude the entire interrupted confirmation cohort from promotion. Restart all frozen arms in three complete fresh blocks. No performance-based exclusions.',
        archived_directory=str(archived),original_directory=str(old),
        interrupted_platform=str(archived/'01_rpc_worker_platform'),
        old_spec=load(root/'confirmation_spec.json'),source_hashes=protocol['source_hashes'],binary_hashes=protocol['binary_hashes'],
        resources=[dict(id=v['Id'],name=v['Name'],state=v['State'],writable_bytes=v.get('SizeRw'),
                        mounts=v['Mounts'],labels=v['Config']['Labels']) for v in states],
        volumes_removed=volume_records,free_before={str(p):shutil.disk_usage(p).free for p in [Path('/'),root]},
        cleanup_complete=False,platform_note='No claim of normal restoration for the reboot-interrupted trial. New trials snapshot and restore the post-boot platform state.')
    b.save(root/'resumption.json',record)
    for state in states:
        with (unfinished/(state['Name'].strip('/')+'.interrupted.log')).open('w') as output:
            subprocess.run(['docker','logs','--tail','40',state['Id']],stdout=output,stderr=subprocess.STDOUT,check=False)
    command=['docker','compose','-p',project,'-f',str(unfinished/'compose.json'),'down','-v','--remove-orphans']
    b.save(root/'interrupted_cleanup_command.json',command)
    with (root/'interrupted_cleanup.log').open('w') as output:subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,check=True)
    assert not subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],text=True).strip()
    assert all(not Path(row['path']).exists() for row in volume_records)
    old.rename(archived)
    shutil.copyfile(root/'confirmation_spec.json',root/'confirmation_pre_interrupt_spec.json')
    # Old measurement paths are retained verbatim; this map resolves their
    # archived counterparts without rewriting the historical evidence.
    record.update(cleanup_complete=True,free_after={str(p):shutil.disk_usage(p).free for p in [Path('/'),root]},
        anonymous_volume_bytes_removed=sum(v['bytes'] for v in volume_records),
        writable_container_bytes_removed=sum(v.get('SizeRw',0) for v in states))
    b.save(root/'resumption.json',record)
    spec=load(root/'confirmation_spec.json')
    spec.update(seedbase=1041601,resumption=str(root/'resumption.json'),
        scope='Fresh independent post-reboot full-request confirmation; same frozen five arms, order and three blocks. Pre-interruption endpoints retained separately and not pooled.')
    b.save(root/'confirmation_spec.json',spec)
    selection=load(root/'confirmation_selection.json');selection['resumption']=str(root/'resumption.json')
    b.save(root/'confirmation_selection.json',selection)


def finish(root):
    recover(root)
    scripts=Path(__file__).parent.resolve()
    run(root,'confirmation_resumed',['python3',scripts/'temporal_path_campaign.py','campaign',root/'confirmation_spec.json'])
    assert load(root/'confirmation/complete.json')['valid']
    chosen=load(root/'confirmation_selection.json');combined=chosen['combined']
    prepared=load(root/'prepared_candidates.json');diag=root/'diagnostics';diag.mkdir(exist_ok=False)
    files=[scripts/name for name in ['rpc_route_followup.py','split_hybrid_study.py','backend_study.py',
        'media_system_study.py','fullset.py','balanced_backend.py','balanced_load.py','media_library_study.py',
        'backend_prefetch.py','hybrid_campaign.py','dense_causes.py']]
    hashes={str(path):b.sha(path) for path in files}
    for path in [*files,Path(__file__)]:
        snapshot=root/'source_versions'/(b.sha(path)+'.py')
        if not snapshot.exists():snapshot.write_bytes(path.read_bytes())
    b.save(diag/'protocol.json',dict(arms=[combined+'_nop',combined],source_hashes=hashes,
        services=['movie','compose','rating'],purpose='Separate diagnostic; excluded from clean endpoint inference.'))
    for index,(name,kind) in enumerate([(combined+'_nop','nop'),(combined,'arm')]):
        assert all(b.sha(path)==value for path,value in hashes.items())
        spec=diag/(f'{index:02d}_{name}.json')
        b.save(spec,dict(prepared[combined][kind],out=str(spec.with_suffix('')),seed=1041701,reverse_pmu=bool(index)))
        run(root,'diagnostic_'+name,['python3',scripts/'rpc_route_followup.py','platform_diagnostic',spec])
        assert load(spec.with_suffix('')/'result.json')['valid']
    b.save(diag/'complete.json',dict(valid=True,trials=2))
    b.save(root/'measurement_complete.json',dict(valid=True,epoch=time.time(),clean_trials=29,
        interrupted_cohort_completed_trials_retained=8,interrupted_trials=1,
        diagnostic_trials=2,smoke_trials=5,nominee=chosen['nominee'],combined=combined,
        resumption='User requested continuation after reboot; fresh confirmation excludes all historical interrupted-cohort endpoints.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    finish(parser.parse_args().root)
