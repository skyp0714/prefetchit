#!/usr/bin/env python3
"""Media HTTP clients with fixed in-flight concurrency and no intentional think time."""
import argparse
import gzip
import http.client
import itertools
import json
import os
from pathlib import Path
import random
import string
import threading
import time
import urllib.parse

REPO=Path(__file__).resolve().parents[3]


def payload(seed,index,titles):
    # Dispatch index fixes the request independently of the completing worker.
    rng=random.Random(seed*1000003+index)
    user=rng.randrange(1,1001)
    text=''.join(rng.choices(string.ascii_letters+string.digits,k=256))
    return urllib.parse.urlencode(dict(username=f'username_{user}',password=f'password_{user}',
        title=rng.choice(titles),rating=rng.randrange(11),text=text)).encode()


def run_load(out,concurrency,seconds,seed,port,titles,warmup=50):
    assert concurrency>0 and seconds>warmup>=0
    out.mkdir(parents=True,exist_ok=True)
    samples=[];errors=[];examples=[];indices=itertools.count();ready=threading.Barrier(concurrency+1)
    go=threading.Event();state={};bodies={}
    def worker():
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=20)
        ready.wait();go.wait()
        while time.monotonic()<state['deadline']:
            body=payload(seed,next(indices),titles)
            started=time.time()
            try:
                connection.request('POST','/wrk2-api/review/compose',body,
                                   {'Content-Type':'application/x-www-form-urlencoded'})
                response=connection.getresponse();data=response.read();ended=time.time()
                if response.status!=200 or data.strip() not in (b'',b'Success',b'Success!'):
                    raise RuntimeError((response.status,data[:120]))
                samples.append((started,ended))
                key=data[:80].decode(errors='replace');bodies[key]=bodies.get(key,0)+1
            except Exception as error:
                errors.append(time.time())
                if len(examples)<12:examples.append(str(error))
                connection.close();connection=http.client.HTTPConnection('127.0.0.1',port,timeout=20)
        connection.close()
    threads=[threading.Thread(target=worker) for _ in range(concurrency)]
    for thread in threads:thread.start()
    ready.wait();start=time.time();monotonic=time.monotonic();cpu=time.process_time()
    state['deadline']=monotonic+seconds
    metadata=dict(epoch=start,seconds=seconds,concurrency=concurrency,seed=seed,warmup_s=warmup,
        port=port,pid=os.getpid(),mode='closed-loop; next request after completion; no intentional think time',
        latency='HTTP dispatch to response completion; excludes external arrival queue',
        payload='Upstream Media field distributions; deterministic per-dispatch-index seed',
        client_cpus=sorted(os.sched_getaffinity(0)))
    (out/'started.json').write_text(json.dumps(metadata,indent=2))
    go.set()
    for thread in threads:thread.join()
    wall=time.monotonic()-monotonic
    client_cpu=(time.process_time()-cpu)/wall
    with gzip.open(out/'requests.json.gz','wt') as f:json.dump(samples,f,separators=(',',':'))
    result=dict(**metadata,completed=len(samples),errors=len(errors),error_times=errors,error_examples=examples,
        steady_errors=sum(t>=start+warmup for t in errors),response_bodies=bodies,
        client_cpu_cores=client_cpu,elapsed_s=wall)
    (out/'load.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--concurrency',type=int,required=True);p.add_argument('--seconds',type=float,default=125)
    p.add_argument('--seed',type=int,default=43001);p.add_argument('--port',type=int,default=18081)
    p.add_argument('--warmup',type=float,default=50);a=p.parse_args()
    os.sched_setaffinity(0,{16,17,18,19})
    text=(REPO/'llvm_prefetchit/results/realistic_screen_20260918/media_compose_review.lua').read_text()
    table=text.split('local movie_titles = {',1)[1].split('\n}',1)[0]
    titles=[json.loads(row.rstrip(',').strip()) for row in table.splitlines() if row.strip()][:1000]
    assert len(titles)==1000
    run_load(a.out,a.concurrency,a.seconds,a.seed,a.port,titles,a.warmup)


if __name__=='__main__':main()
