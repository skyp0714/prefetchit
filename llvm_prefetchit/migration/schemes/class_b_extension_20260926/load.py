"""Open-loop HTTP load with exact completion timestamps and bounded concurrency."""
from pathlib import Path
import argparse,gzip,http.client,json,os,queue,random,re,string,threading,time,urllib.parse

REPO=Path('/home/hnpark2/prefetchit')
def save(p,x):p.write_text(json.dumps(x,separators=(',',':'))+'\n')

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--rate',type=int,required=True);p.add_argument('--seconds',type=int,default=120);p.add_argument('--seed',type=int,default=123);p.add_argument('--port',type=int,default=18081);p.add_argument('--workload',choices=['media','social'],default='media');a=p.parse_args()
 os.sched_setaffinity(0,{16,17,18,19});a.out.mkdir(exist_ok=True)
 rng=random.Random(a.seed);arrival=random.Random(a.seed+10000)
 if a.workload=='media':
  text=(REPO/'llvm_prefetchit/results/realistic_screen_20260918/media_compose_review.lua').read_text();table=text.split('local movie_titles = {',1)[1].split('\n}',1)[0]
  titles=[json.loads(x.rstrip(',').strip()) for x in table.splitlines() if x.strip()];assert len(titles)>=1000;titles=titles[:1000]
 jobs=queue.Queue(128);samples=[];errors=[];drops=[];bodies={};offered=0
 def worker():
  c=http.client.HTTPConnection('127.0.0.1',a.port,timeout=20)
  while True:
   job=jobs.get()
   if job is None:jobs.task_done();break
   planned,body=job
   try:
    endpoint='/wrk2-api/review/compose' if a.workload=='media' else '/wrk2-api/post/compose'
    c.request('POST',endpoint,body,{'Content-Type':'application/x-www-form-urlencoded'});response=c.getresponse();data=response.read();end=time.time()
    allowed=[b'',b'Success',b'Success!'] if a.workload=='media' else [b'Successfully upload post']
    assert response.status==200 and data.strip() in allowed,(response.status,data[:120])
    samples.append((planned,end));bodies[data[:80].decode(errors='replace')]=bodies.get(data[:80].decode(errors='replace'),0)+1
   except Exception as exc:
    errors.append((time.time(),str(exc)));c.close();c=http.client.HTTPConnection('127.0.0.1',a.port,timeout=20)
   finally:jobs.task_done()
  c.close()
 threads=[threading.Thread(target=worker) for _ in range(64)]
 for t in threads:t.start()
 start=time.time();planned=start;save(a.out/'started.json',dict(epoch=start,rate=a.rate,seconds=a.seconds,seed=a.seed,workers=64,queue=128,arrival='Poisson open loop',payload='upstream request field distributions'))
 while planned<start+a.seconds:
  user=rng.randrange(1,1001) if a.workload=='media' else rng.randrange(962);text=''.join(rng.choices(string.ascii_letters+string.digits,k=256))
  if a.workload=='media':payload=dict(username=f'username_{user}',password=f'password_{user}',title=rng.choice(titles),rating=rng.randrange(11),text=text)
  else:
   for _ in range(rng.randrange(6)+1):
    mention=rng.randrange(961);mention+=mention>=user;text+=f' @username_{mention}'
   for _ in range(rng.randrange(6)+1):text+=' http://'+''.join(rng.choices(string.ascii_letters+string.digits,k=64))
   ids=[''.join(rng.choices(string.digits,k=18)) for _ in range(rng.randrange(5)+1)]
   payload=dict(username=f'username_{user}',user_id=user,text=text,media_ids=json.dumps(ids),media_types=json.dumps(['png']*len(ids)),post_type=0)
  body=urllib.parse.urlencode(payload).encode();delay=planned-time.time()
  if delay>0:time.sleep(delay)
  try:jobs.put_nowait((planned,body))
  except queue.Full:drops.append(planned)
  offered+=1;planned+=arrival.expovariate(a.rate)
 jobs.join()
 for _ in threads:jobs.put(None)
 for t in threads:t.join()
 with gzip.open(a.out/'requests.json.gz','wt') as f:json.dump(samples,f,separators=(',',':'))
 warmup_end=start+50
 steady_errors=[e for e in errors if e[0]>=warmup_end];steady_drops=[e for e in drops if e>=warmup_end]
 save(a.out/'load.json',dict(rate=a.rate,seconds=a.seconds,seed=a.seed,offered=offered,completed=len(samples),errors=len(errors),error_examples=errors[:12],dropped=drops,response_bodies=bodies,warmup_s=50,warmup_errors=len(errors)-len(steady_errors),steady_errors=len(steady_errors),steady_error_examples=steady_errors[:12],steady_drops=steady_drops,validation='Zero errors/drops after the fixed 50s startup warmup; startup errors retained separately'))
 assert not steady_errors and not steady_drops,(len(steady_errors),len(steady_drops))

if __name__=='__main__':main()
