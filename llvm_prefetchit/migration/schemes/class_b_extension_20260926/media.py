"""Private, fully initialized Media stack; exact completed-request CPU accounting."""
from pathlib import Path
import argparse,gzip,json,os,re,shutil,signal,socket,subprocess,sys,time,urllib.error,urllib.request,yaml
from common import *
from tracing_config import prepare as prepare_tracing

MM=REPO/'benchmarks/DeathStarBench/mediaMicroservices'
OLD=REPO/'llvm_prefetchit/results/class_a2_20260923/media_rpc_production'
BUILD=S/'media_build'
TARGETS={'compose':('compose-review-service','ComposeReviewService','40-41'),'rating':('rating-service','RatingService','42-43')}

class Stack:
 def __init__(self,out,overrides=None):
  self.out=out;self.project='codex-b-media-20260926';self.dc=['docker','compose','-p',self.project,'-f',str(out/'compose.json')];self.overrides=overrides or {}
  self.targets=TARGETS;self.build_root=BUILD;self.workload='media';self.port=18081
 def cid(self,name):return subprocess.check_output(self.dc+['ps','-q',name],text=True).strip()
 def info(self,name):return json.loads(subprocess.check_output(['docker','inspect',self.cid(name)],text=True))[0]
 def start(self):
  space();assert not subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+self.project],text=True).strip()
  with socket.socket() as p:p.bind(('127.0.0.1',18081))
  sampling=os.environ.get('CLASS_B_MEDIA_SAMPLE_RATE');config_dir,nginx_tracer=prepare_tracing(self.out,MM,float(sampling) if sampling is not None else None)
  config=yaml.safe_load((MM/'docker-compose.yml').read_text());config.pop('version',None);config['services'].pop('dns-media',None)
  for name,c in config['services'].items():
   c['restart']='on-failure:5';c['cpuset']='32-39';c.pop('ports',None);c['logging']={'driver':'json-file','options':{'max-size':'2m','max-file':'2'}}
   c['volumes']=[str((MM/v.split(':',1)[0]).resolve())+':'+v.split(':',1)[1] if v.startswith('./') else v for v in c.get('volumes',[])]
   exe=c.get('entrypoint','')
   if isinstance(exe,str) and exe.endswith('Service'):
    binary=OLD/'support'/exe
    for key,(service,bn,_) in TARGETS.items():
     if service==name:binary=Path(self.overrides.get(key,BUILD/key/'base'/bn))
    binary=ensure_local(binary)
    assert binary.is_file() and not str(binary.resolve()).startswith('/fast-lab-share/'),binary
    c.update(image='dsb-deps-jammy',working_dir='/media-microservices',entrypoint=['/custom/'+exe],volumes=[str(binary)+':/custom/'+exe+':ro',str(config_dir)+':/media-microservices/config:ro'])
    if os.environ.get('CLASS_B_SCHED_CLOCK') == '1' and name in {v[0] for v in TARGETS.values()}:
     c['devices']=['/dev/prefetchit_sched_clock:/dev/prefetchit_sched_clock:r']
     c.setdefault('environment',{})['PREFETCHIT_SCHED_REQUIRED']='1'
  config['services']['nginx-web-server']['ports']=['127.0.0.1:18081:8080']
  config['services']['nginx-web-server']['volumes']=[str(nginx_tracer)+':/usr/local/openresty/nginx/jaeger-config.json:ro' if v.split(':')[1]=='/usr/local/openresty/nginx/jaeger-config.json' else v for v in config['services']['nginx-web-server']['volumes']]
  config['services']['jaeger'].update(image='jaegertracing/all-in-one:1.57',command=['--memory.max-traces=10000'])
  nginx=(MM/'nginx-web-server/conf/nginx.conf').read_text()
  for loc in ['movie-info/write','cast-info/write','plot/write']:
   needle='location /wrk2-api/'+loc+' {';assert needle in nginx;nginx=nginx.replace(needle,needle+'\n      client_body_buffer_size 1m;')
  (self.out/'nginx.conf').write_text(nginx)
  config['services']['nginx-web-server']['volumes']=[str(self.out/'nginx.conf')+':/usr/local/openresty/nginx/conf/nginx.conf:ro' if v.split(':')[1]=='/usr/local/openresty/nginx/conf/nginx.conf' else v for v in config['services']['nginx-web-server']['volumes']]
  save(self.out/'compose.json',config);self.config=config
  run(self.dc+['up','-d','jaeger'],self.out/'jaeger_up.log')
  for _ in range(60):
   info=self.info('jaeger');ip=next(x['IPAddress'] for x in info['NetworkSettings']['Networks'].values())
   try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://'+ip+':14269/',timeout=1) as resp:
     if resp.status==200:break
   except OSError:pass
   time.sleep(1)
  else:raise RuntimeError('Jaeger readiness failed')
  backends=[n for n in config['services'] if n.endswith(('-mongodb','-memcached','-redis'))]
  run(self.dc+['up','-d',*backends],self.out/'backends_up.log')
  for name in backends:
   info=self.info(name);ip=next(x['IPAddress'] for x in info['NetworkSettings']['Networks'].values());port=27017 if name.endswith('-mongodb') else 6379 if name.endswith('-redis') else 11211
   for _ in range(60):
    try:
     with socket.create_connection((ip,port),timeout=1):break
    except OSError:time.sleep(1)
   else:raise RuntimeError('Backend readiness failed: '+name)
   if name.endswith('-redis'):
    for setting,value in [('save',''),('appendonly','no')]:subprocess.run(['docker','exec',self.cid(name),'redis-cli','CONFIG','SET',setting,value],stdout=subprocess.DEVNULL,check=True)
  run(self.dc+['up','-d'],self.out/'up.log');time.sleep(10)
  for _ in range(60):
   try:
    with urllib.request.urlopen('http://127.0.0.1:18081/',timeout=2):break
   except urllib.error.HTTPError:break
   except OSError:time.sleep(1)
  else:raise RuntimeError('Nginx readiness failed')
  initializer=REPO/'llvm_prefetchit/results/class_a2_20260923/media_production_qualification/base_2500/initialize_movies.py'
  assert initializer.exists();run(['taskset','-c','16-19','runuser','-u','hnpark2','--','python3',initializer,'-c',MM/'datasets/tmdb/casts.json','-m',MM/'datasets/tmdb/movies.json','--server_address','http://127.0.0.1:18081'],self.out/'init_movies.log',timeout=900)
  expected=len({m['title'] for m in json.loads((MM/'datasets/tmdb/movies.json').read_text())})
  actual=int(subprocess.check_output(['docker','exec',self.cid('movie-id-mongodb'),'mongo','--quiet','--eval','db.getSiblingDB("movie-id").getCollection("movie-id").countDocuments({})'],text=True).strip());assert actual==expected
  for i in range(1,1001):
   body=f'first_name=first_name_{i}&last_name=last_name_{i}&username=username_{i}&password=password_{i}'.encode()
   with urllib.request.urlopen('http://127.0.0.1:18081/wrk2-api/user/register',data=body,timeout=10) as resp:assert resp.status==200 and resp.read().strip()==b''
  query='var c=db.getSiblingDB("user").getCollection("user"); var a=c.find({}, {username:1,user_id:1,_id:0}).toArray(); print(JSON.stringify({count:a.length,names:a.map(x=>x.username).sort(),nonzero:a.every(x=>x.user_id.toString()!="0")}))'
  users=json.loads(subprocess.check_output(['docker','exec',self.cid('user-mongodb'),'mongo','--quiet','--eval',query],text=True))
  assert users['count']==1000 and users['nonzero'] and users['names']==sorted(f'username_{i}' for i in range(1,1001)),users
  save(self.out/'dataset_validation.json',dict(expected_unique_titles=expected,actual_unique_titles=actual,registered_users=1000,users=users,initializer=str(initializer),initializer_sha256=sha(initializer)))
  self.states={n:self.info(n) for n in config['services']}
  save(self.out/'runtime.json',{n:dict(pid=i['State']['Pid'],image=i['Image'],restart=i['RestartCount']) for n,i in self.states.items()})
  save(self.out/'binary_hashes.json',{k:dict(path=str(self.overrides.get(k,BUILD/k/'base'/exe)),sha256=sha(self.overrides.get(k,BUILD/k/'base'/exe))) for k,(_,exe,_) in TARGETS.items()})
 def layout(self,mode):
  for _,(name,_,alone) in self.targets.items():subprocess.run(['docker','update','--cpuset-cpus',alone if mode=='alone' else '32-39',self.cid(name)],check=True,stdout=subprocess.DEVNULL)
 def accounts(self):return {name:cpu(i['State']['Pid']) for name,i in self.states.items()}
 def check(self):
  for name,i in self.states.items():
   new=self.info(name);assert new['State']['Running'] and new['State']['Pid']==i['State']['Pid'] and new['RestartCount']==i['RestartCount'],name
 def close(self):
  if (self.out/'compose.json').exists():
   volumes={};free_before=shutil.disk_usage(REPO).free
   ids=subprocess.check_output(self.dc+['ps','-aq'],text=True).split()
   if ids:
    for info in json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)):
     assert info['Config']['Labels']['com.docker.compose.project']==self.project
     for mount in info['Mounts']:
      if mount['Type']!='volume':continue
      name=mount['Name'];assert re.fullmatch('[0-9a-f]{64}',name),'Only task-created anonymous data volumes may be removed'
      source=Path(mount['Source']);total=allocated=0
      for directory,dirs,files in os.walk(source,followlinks=False):
       dirs[:]=[x for x in dirs if not (Path(directory)/x).is_symlink()]
       for filename in files:
        p=Path(directory)/filename
        if p.is_symlink():continue
        try:st=p.stat();total+=st.st_size;allocated+=st.st_blocks*512
        except FileNotFoundError:pass
      volumes[name]=dict(name=name,path=str(source),bytes_before_shutdown=total,allocated_bytes_before_shutdown=allocated)
   save(self.out/'volume_cleanup_plan.json',dict(volumes=volumes,free_before=free_before,scope='Only anonymous data volumes attached to this fresh task-owned compose project; bind-mounted sources/inputs excluded'))
   try:run(self.dc+['logs','--no-color','--tail','40'],self.out/'container_tail.log',timeout=60)
   finally:
    run(self.dc+['down','--volumes','--remove-orphans'],self.out/'down.log',timeout=180)
    for name in volumes:assert subprocess.run(['docker','volume','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
    save(self.out/'volume_cleanup.json',dict(removed=list(volumes.values()),bytes_before_shutdown=sum(v['bytes_before_shutdown'] for v in volumes.values()),free_before=free_before,free_after=shutil.disk_usage(REPO).free,note='Volume size sampled before service shutdown; free-space delta includes concurrent filesystem activity'))

def trial(stack,out,rate,layout,seed=123,trace=False,primary_only=False):
 space();out.mkdir();stack.layout(layout);stack.check();client=None
 cmd=['python3',str(B/'load.py'),'--out',str(out),'--rate',str(rate),'--seconds',str(95 if primary_only else 155),'--seed',str(seed),'--workload',stack.workload,'--port',str(stack.port)]
 save(out/'measurement_policy.json',dict(primary_only=primary_only,warmup_s=50,clean_cpu_window_s=30,total_load_s=95 if primary_only else 155,pmu='not collected in independent primary endpoint confirmation' if primary_only else '30s per service after primary window'))
 save(out/'load_command.json',cmd)
 try:
  with (out/'client.log').open('w') as f:client=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
  for _ in range(100):
   if (out/'started.json').exists():break
   assert client.poll() is None;time.sleep(.1)
  else:raise RuntimeError('load did not start')
  time.sleep(50);assert client.poll() is None
  before=stack.accounts();time.sleep(30);after=stack.accounts();primary={k:diff_cpu(before[k],after[k]) for k in before}
  pmu_cost={}
  for key,(name,_,_) in stack.targets.items():
   if primary_only:continue
   pid=stack.states[name]['State']['Pid'];before_pmu=cpu(pid);group=str(Path(before_pmu['path']).parent.relative_to('/sys/fs/cgroup'))
   command=['perf','stat','-x,','-o',str(out/(key+'.perf.csv')),'-e',EVENTS,'-a','-C','32-43','-G',group,'--','sleep','30'];save(out/(key+'.perf_command.json'),command)
   proc=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);save(out/(key+'.perf_status.json'),dict(exit=proc.returncode,stderr=proc.stderr.decode(),scope='all current/future tasks in target cgroup; one service PMU at a time'));assert proc.returncode==0
   pmu_cost[name]=diff_cpu(before_pmu,cpu(pid))
  rc=client.wait(timeout=90);client=None
  stack.check();info=json.loads((out/'load.json').read_text())
  with gzip.open(out/'requests.json.gz','rt') as f:samples=json.load(f)
  def attach(cost):
   lat=sorted((e-s)*1000 for s,e in samples if cost['start']<=e<cost['end']);n=len(lat);assert n
   cost.update(completed=n,achieved_rps=n/cost['wall_s'],cpu_us_per_request=cost['cpu_us']/n,p99_ms=lat[int(.99*(n-1))],user_us_per_request=cost['user_us']/n)
   return cost
  for costs in [primary,pmu_cost]:
   for v in costs.values():attach(v)
  total_cpu=sum(x['cpu_us'] for x in primary.values());duration=next(iter(primary.values()))['wall_s'];pool_util=100*total_cpu/(duration*1e6*(8 if layout=='shared' else 12))
  common_ok=rc==0 and not info.get('steady_errors',info['errors']) and not info.get('steady_drops',info['dropped']);result=dict(rate=rate,layout=layout,seed=seed,pool_util_pct=pool_util,services={},all_cpu_us=total_cpu,load=info)
  for key,(name,_,_) in stack.targets.items():
   if primary_only:
    cost=primary[name];valid=bool(common_ok and abs(cost['achieved_rps']/rate-1)<.04 and cost['p99_ms']<100)
    result['services'][key]=dict(primary=cost,post_pmu=dict(collected=False,mpki=None),valid=valid,user_cycles_per_request=None,code_misses_per_request=None,context_switches_per_request=None)
    continue
   c=counters(out/(key+'.perf.csv'));cost=primary[name];pc=pmu_cost[name];co=c['counters']
   valid=bool(common_ok and c['fully_scheduled'] and abs(cost['achieved_rps']/rate-1)<.04 and abs(pc['achieved_rps']/rate-1)<.04 and cost['p99_ms']<100)
   result['services'][key]=dict(primary=cost,post_pmu={**pc,**c},valid=valid,user_cycles_per_request=co['cycles:u']/pc['completed'],code_misses_per_request=co['L2I']/pc['completed'],context_switches_per_request=co.get('context-switches',0)/pc['completed'])
  save(out/'result.json',result);print(json.dumps(dict(path=str(out),rate=rate,layout=layout,pool_util=pool_util,services={k:dict(mpki=v['post_pmu']['mpki'],cpu=v['primary']['cpu_us_per_request'],valid=v['valid']) for k,v in result['services'].items()})),flush=True)
  return result
 finally:stop(client)

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--qualify',action='store_true');p.add_argument('--service',choices=list(TARGETS));p.add_argument('--binary',type=Path);p.add_argument('--rate',type=int,default=600);p.add_argument('--seed',type=int,default=123);a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=False);overrides={a.service:a.binary} if a.binary else {};stack=Stack(a.out,overrides)
 save(a.out/'harness_hashes.json',{p.name:sha(p) for p in B.glob('*.py')})
 def interrupt(signum,frame):raise KeyboardInterrupt(signum)
 signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
 try:
  stack.start();rows=[]
  if a.qualify:
   for rate in [300,600,900]:
    for layout in ['alone','shared']:
     rows.append(trial(stack,a.out/f'{layout}_{rate}',rate,layout));save(a.out/'summary.json',rows)
   selected={}
   for key in TARGETS:
    candidates=[]
    for rate in [300,600,900]:
     pair={r['layout']:r for r in rows if r['rate']==rate};shared=pair['shared']['services'][key];alone=pair['alone']['services'][key]
     mpki=shared['post_pmu']['mpki'];ratio=mpki/alone['post_pmu']['mpki']
     if shared['valid'] and alone['valid'] and pair['shared']['pool_util_pct']>=15 and mpki>=5 and ratio>=2:candidates.append(dict(rate=rate,mpki=mpki,alone_mpki=alone['post_pmu']['mpki'],inflation=ratio))
    selected[key]=max(candidates,key=lambda x:x['mpki']) if candidates else dict(status='No valid >=15% pool utilization, >=5 shared MPKI and >=2x MPKI inflation point')
   save(a.out/'selected.json',selected)
  else:save(a.out/'summary.json',[trial(stack,a.out/'measurement',a.rate,'shared',a.seed,primary_only=confirmation_primary_only(a.out))])
 finally:stack.close()

def confirmation_primary_only(out):
 policy=json.loads((B/'confirmation_policy.json').read_text()) if (B/'confirmation_policy.json').exists() else {}
 return bool(policy.get('primary_only') and out.parent.name=='confirmation' and out.parents[2].name in ['media_evaluation','social_evaluation'] and S in out.parents)

if __name__=='__main__':main()
