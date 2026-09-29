#!/usr/bin/env python3
"""Read accepted HTTP socket ownership after a trial's clean ROI."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def identity(pid):
    raw=Path(f'/proc/{pid}/stat').read_text();fields=raw.split(') ',1)[1].split()
    return dict(pid=pid,start_ticks=int(fields[19]),user_ticks=int(fields[11]),system_ticks=int(fields[12]))


def snapshot(trial):
    started=json.loads((trial/'load/started.json').read_text());age=time.time()-started['epoch']
    assert 115<=age<started['seconds']-3,'Observe after clean ROI while the original client is still running'
    assert not (trial/'result.json').exists()
    pid=json.loads((trial/'runtime.json').read_text())['nginx-web-server']['pid']
    master=identity(pid);sockets={}
    for family in ['tcp','tcp6']:
        for line in Path(f'/proc/{pid}/net/{family}').read_text().splitlines()[1:]:
            values=line.split();local=int(values[1].rsplit(':',1)[1],16)
            if values[3]!='01' or local!=8080:continue
            inode=int(values[9]);sockets[inode]=dict(inode=inode,peer_port=int(values[2].rsplit(':',1)[1],16),family=family)
    children=[int(value) for value in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]
    workers=[];seen=[]
    for child in children:
        before=identity(child);owned=[]
        for fd in Path(f'/proc/{child}/fd').iterdir():
            try:link=fd.readlink().as_posix()
            except FileNotFoundError:continue
            if not link.startswith('socket:['):continue
            inode=int(link[8:-1])
            if inode in sockets:owned.append(dict(sockets[inode],fd=int(fd.name)));seen.append(inode)
        after=identity(child);assert before['start_ticks']==after['start_ticks']
        workers.append(dict(**after,http_connections=owned,count=len(owned)))
    assert identity(pid)['start_ticks']==master['start_ticks']
    return dict(valid=len(seen)==len(set(seen))==len(sockets)==started['concurrency'],
        epoch=time.time(),load_age_s=age,trial=str(trial),master=master,workers=workers,
        connection_counts=sorted((worker['count'] for worker in workers),reverse=True),
        accepted_http_sockets=len(sockets),expected_connections=started['concurrency'],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitation='One post-clean-ROI snapshot of accepted persistent HTTP socket ownership. It does not prove occupancy throughout the ROI, request service time, causality, or worker load balance. No connection, worker or workload setting is changed.')


def watch(root):
    out=root/'nginx_connection_snapshots';out.mkdir(exist_ok=False)
    while not (root/'screen/complete.json').exists():
        for trial in sorted((root/'screen').glob('[0-9][0-9]_*')):
            target=out/(trial.name+'.json');started=trial/'load/started.json'
            if not trial.is_dir() or target.exists() or not started.exists() or (trial/'result.json').exists():continue
            info=json.loads(started.read_text());age=time.time()-info['epoch']
            if not 115<=age<info['seconds']-3:continue
            try:result=snapshot(trial)
            except (OSError,AssertionError) as error:result=dict(valid=False,error=repr(error),trial=str(trial),epoch=time.time())
            target.write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(dict(trial=trial.name,valid=result['valid'],connection_counts=result.get('connection_counts'),error=result.get('error'))),flush=True)
        time.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();watch(a.root)
