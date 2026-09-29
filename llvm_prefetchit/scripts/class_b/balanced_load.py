#!/usr/bin/env python3
"""Fixed C4 Media load with one persistent HTTP connection per Nginx worker.

Resolve accepted socket ownership before the
warmup clock starts; no HTTP requests are sent by the balancer. Account for
Docker's possible userland proxy by matching newly accepted socket inodes,
not assuming that the client source port survives forwarding. Warmup-only
repairs preserve the assigned worker; steady operation forbids reconnects.
"""
import argparse
import collections
import gzip
import hashlib
import http.client
import itertools
import json
import os
from pathlib import Path
import threading
import time
from closed_loop_load import payload,REPO


def owned_connections(master):
    children=[int(value) for value in Path(f'/proc/{master}/task/{master}/children').read_text().split()]
    workers=[pid for pid in children if b'nginx: worker process' in Path(f'/proc/{pid}/cmdline').read_bytes()]
    assert len(workers)==4,'Require the benchmark configuration of four Nginx workers'
    sockets={}
    for family in ['tcp','tcp6']:
        for line in Path(f'/proc/{master}/net/{family}').read_text().splitlines()[1:]:
            fields=line.split()
            if fields[3]=='01' and int(fields[1].rsplit(':',1)[1],16)==8080:
                sockets[int(fields[9])]=int(fields[2].rsplit(':',1)[1],16)
    owners={}
    for worker in workers:
        for path in Path(f'/proc/{worker}/fd').iterdir():
            try:link=path.readlink().as_posix()
            except FileNotFoundError:continue
            if link.startswith('socket:['):
                inode=int(link[8:-1])
                if inode in sockets:
                    assert inode not in owners
                    owners[inode]=dict(worker=worker,peer_port=sockets[inode])
    return workers,owners


def connect_balanced(master,port,out):
    started=time.monotonic();deadline=started+20;kept={};sockets=set();attempts=[];pending=None
    def wait_for(predicate):
        while time.monotonic()<deadline:
            workers,owners=owned_connections(master)
            if predicate(owners):return workers,owners
            time.sleep(.025)
        raise TimeoutError('Timed out while identifying balanced accepted HTTP sockets')
    try:
        workers,_=wait_for(lambda owners:not owners)
        for attempt in range(64):
            if len(kept)==4:break
            # Drain rejected sockets before the next connect so the new inode
            # cannot be confused with a delayed proxy accept from an old try.
            _,before=wait_for(lambda owners:set(owners)==sockets)
            pending=http.client.HTTPConnection('127.0.0.1',port,timeout=20);pending.connect()
            client_port=pending.sock.getsockname()[1]
            current,after=wait_for(lambda owners:len(set(owners)-set(before))==1)
            assert set(current)==set(workers),'Nginx worker identity changed during setup'
            inode=next(iter(set(after)-set(before)));owner=after[inode]['worker']
            accept=owner not in kept
            attempts.append(dict(attempt=attempt,client_port=client_port,server_inode=inode,
                server_peer_port=after[inode]['peer_port'],worker=owner,accepted=accept))
            if accept:kept[owner]=pending;sockets.add(inode);pending=None
            else:pending.close();pending=None
        assert len(kept)==4,'Connection-attempt budget exhausted'
        _,final=wait_for(lambda owners:set(owners)==sockets)
        counts=collections.Counter(value['worker'] for value in final.values())
        assert set(counts)==set(workers) and all(value==1 for value in counts.values())
        record=dict(valid=True,master_pid=master,worker_pids=sorted(workers),attempts=attempts,
            server_inodes=sorted(sockets),counts=dict(counts),setup_seconds=time.monotonic()-started,
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            rule='One accepted persistent connection for each existing worker, before timed warmup; no HTTP setup requests, server configuration or scheduling changes.')
        (out/'connection_balance.json').write_text(json.dumps(record,indent=2)+'\n')
        return [kept[pid] for pid in sorted(kept)]
    except BaseException as error:
        if pending is not None:pending.close()
        for connection in kept.values():connection.close()
        (out/'connection_balance_failure.json').write_text(json.dumps(dict(error=repr(error),attempts=attempts,
            setup_seconds=time.monotonic()-started),indent=2)+'\n')
        raise


def reconnect_worker(master,port,owner,warmup_end):
    """Repair a warmup-only transport loss without changing HTTP ownership."""
    deadline=min(time.monotonic()+10,time.monotonic()+max(0,warmup_end-time.time()))
    attempts=[];pending=None
    def wait_for(predicate):
        while time.monotonic()<deadline:
            workers,current=owned_connections(master)
            assert owner in workers,'Assigned Nginx worker disappeared'
            if predicate(current):return current
            time.sleep(.01)
        raise TimeoutError('Could not restore assigned worker within warmup')
    try:
        rejected=None
        for attempt in range(64):
            if rejected is not None:wait_for(lambda current:rejected not in current)
            _,before=owned_connections(master)
            pending=http.client.HTTPConnection('127.0.0.1',port,timeout=20);pending.connect()
            after=wait_for(lambda current:len(set(current)-set(before))==1)
            inode=next(iter(set(after)-set(before)));observed=after[inode]['worker']
            attempts.append(dict(attempt=attempt,server_inode=inode,worker=observed,accepted=observed==owner))
            if observed==owner:
                assert time.time()<warmup_end
                return pending,dict(owner=owner,completed_epoch=time.time(),attempts=attempts)
            pending.close();pending=None;rejected=inode
        raise RuntimeError('Warmup same-worker reconnect budget exhausted')
    except BaseException:
        if pending is not None:pending.close()
        raise


def run(out,seconds,seed,port,nginx_pid,warmup=50):
    assert seconds>warmup>=0
    out.mkdir(parents=True,exist_ok=True)
    text=(REPO/'llvm_prefetchit/results/realistic_screen_20260918/media_compose_review.lua').read_text()
    table=text.split('local movie_titles = {',1)[1].split('\n}',1)[0]
    titles=[json.loads(row.rstrip(',').strip()) for row in table.splitlines() if row.strip()][:1000]
    assert len(titles)==1000
    connections=connect_balanced(nginx_pid,port,out)
    owners=json.loads((out/'connection_balance.json').read_text())['worker_pids']
    samples=[];errors=[];examples=[];fatal_errors=[];mapping_errors=[];repairs=[];bodies={};indices=itertools.count()
    repair_lock=threading.Lock()
    ready=threading.Barrier(5);go=threading.Event();stop=threading.Event();state={}
    def worker(connection,owner):
        original_socket=connection.sock
        ready.wait();go.wait()
        while time.monotonic()<state['deadline'] and not stop.is_set():
            body=payload(seed,next(indices),titles);started=time.time()
            try:
                # Implicit HTTP reconnects would change worker assignment.
                # Preserve that operating failure instead of silently rerouting.
                if connection.sock is not original_socket:
                    mapping_errors.append(time.time());raise RuntimeError('Balanced persistent connection changed')
                connection.request('POST','/wrk2-api/review/compose',body,
                    {'Content-Type':'application/x-www-form-urlencoded'})
                response=connection.getresponse();data=response.read();ended=time.time()
                if connection.sock is not original_socket:
                    mapping_errors.append(ended);raise RuntimeError(('Balanced response closed its persistent connection',response.status,data[:120]))
                if response.status!=200 or data.strip() not in (b'',b'Success',b'Success!'):
                    error=RuntimeError((response.status,data[:120]))
                    if ended<state['warmup_end']:
                        # The original harness retains warmup application
                        # errors and excludes them from steady qualification.
                        # Keep this fully consumed HTTP connection in place.
                        errors.append(ended);examples.append(str(error));continue
                    raise error
                samples.append((started,ended));key=data[:80].decode(errors='replace');bodies[key]=bodies.get(key,0)+1
            except Exception as error:
                failed=time.time();errors.append(failed);examples.append(str(error))
                if failed<state['warmup_end'] and not stop.is_set():
                    try:
                        connection.close()
                        with repair_lock:
                            connection,record=reconnect_worker(nginx_pid,port,owner,state['warmup_end'])
                        original_socket=connection.sock;repairs.append(record)
                        continue
                    except Exception as repair_error:examples.append(str(repair_error))
                fatal_errors.append(str(error));stop.set()
        connection.close()
    threads=[threading.Thread(target=worker,args=(connection,owner)) for connection,owner in zip(connections,owners)]
    for thread in threads:thread.start()
    ready.wait();start=time.time();monotonic=time.monotonic();cpu=time.process_time();state['deadline']=monotonic+seconds
    state['warmup_end']=start+warmup
    metadata=dict(epoch=start,seconds=seconds,concurrency=4,seed=seed,warmup_s=warmup,port=port,pid=os.getpid(),
        mode='Closed loop with one pre-established persistent HTTP connection per Nginx worker',
        latency='HTTP dispatch to response completion; excludes external arrival queue',
        payload='Same upstream Media field distributions and per-dispatch-index seed as closed_loop_load.py',
        client_cpus=sorted(os.sched_getaffinity(0)),client_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        balance_record=str(out/'connection_balance.json'))
    (out/'started.json').write_text(json.dumps(metadata,indent=2)+'\n');go.set()
    for thread in threads:thread.join()
    wall=time.monotonic()-monotonic;client_cpu=(time.process_time()-cpu)/wall
    with gzip.open(out/'requests.json.gz','wt') as stream:json.dump(samples,stream,separators=(',',':'))
    result=dict(**metadata,completed=len(samples),errors=len(errors),error_times=errors,error_examples=examples,
        steady_errors=sum(value>=start+warmup for value in errors),response_bodies=bodies,
        client_cpu_cores=client_cpu,elapsed_s=wall,mapping_preserved=not fatal_errors,
        fatal_errors=fatal_errors,mapping_errors=mapping_errors,warmup_reconnects=repairs,
        warmup_error_policy='Retain startup application/transport errors. Restore a closed warmup connection only to its originally assigned Nginx worker, with no setup HTTP requests. No reconnects or application errors are allowed after warmup; failures remain fatal. Same 50s warmup and 60s E2E ROI as the original harness.')
    (out/'load.json').write_text(json.dumps(result,indent=2)+'\n')
    if fatal_errors:raise RuntimeError('Balanced load stopped after a transport, mapping or steady application error')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seconds',type=float,required=True);p.add_argument('--seed',type=int,required=True)
    p.add_argument('--nginx-pid',type=int,required=True);p.add_argument('--port',type=int,default=18081)
    p.add_argument('--warmup',type=float,default=50)
    a=p.parse_args();os.sched_setaffinity(0,{16,17,18,19});run(a.out,a.seconds,a.seed,a.port,a.nginx_pid,a.warmup)
