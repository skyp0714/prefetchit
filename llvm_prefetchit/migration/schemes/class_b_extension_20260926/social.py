"""Second application family: complete SocialNetwork compose-post request path."""
from common import *
from media import Stack as MediaStack,trial,confirmation_primary_only
from tracing_config import prepare as prepare_tracing
import argparse,concurrent.futures,socket,urllib.error,urllib.parse,urllib.request,yaml
SN=REPO/'benchmarks/DeathStarBench/socialNetwork';BUILD=S/'social_build'
TARGETS={'composepost':('compose-post-service','ComposePostService','40-41'),'usertimeline':('user-timeline-service','UserTimelineService','42-43')}

class Stack(MediaStack):
 def __init__(self,out,overrides=None):
  super().__init__(out,overrides);self.project='codex-b-social-20260926';self.dc=['docker','compose','-p',self.project,'-f',str(out/'compose.json')]
  self.targets=TARGETS;self.build_root=BUILD;self.workload='social';self.port=18082
 def start(self):
  space();assert not subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project='+self.project],text=True).strip()
  with socket.socket() as p:p.bind(('127.0.0.1',self.port))
  config_dir,nginx_tracer=prepare_tracing(self.out,SN,float(os.environ.get('CLASS_B_SOCIAL_SAMPLE_RATE','.1')))
  config=yaml.safe_load((SN/'docker-compose.yml').read_text());config.pop('version',None)
  for name,c in config['services'].items():
   c['restart']='on-failure:5';c['cpuset']='32-39';c.pop('ports',None);c['logging']={'driver':'json-file','options':{'max-size':'2m','max-file':'2'}}
   c['volumes']=[str((SN/v.split(':',1)[0]).resolve())+':'+v.split(':',1)[1] if v.startswith('./') else v for v in c.get('volumes',[])]
   exe=c.get('entrypoint','')
   if isinstance(exe,str) and exe.endswith('Service'):
    binary=BUILD/'support'/exe
    for key,(service,bn,_) in TARGETS.items():
     if name==service:binary=Path(self.overrides.get(key,BUILD/key/'base'/bn))
    binary=ensure_local(binary)
    assert binary.is_file() and not str(binary.resolve()).startswith('/fast-lab-share/'),binary
    c.update(image='dsb-deps-jammy',working_dir='/social-network-microservices',entrypoint=['/custom/'+exe],volumes=[str(binary)+':/custom/'+exe+':ro',str(config_dir)+':/social-network-microservices/config:ro'])
  config['services']['nginx-thrift']['ports']=[f'127.0.0.1:{self.port}:8080'];config['services']['jaeger-agent'].update(image='jaegertracing/all-in-one:1.57',command=['--memory.max-traces=10000'])
  config['services']['nginx-thrift']['volumes']=[str(nginx_tracer)+':/usr/local/openresty/nginx/jaeger-config.json:ro' if v.split(':')[1]=='/usr/local/openresty/nginx/jaeger-config.json' else v for v in config['services']['nginx-thrift']['volumes']]
  save(self.out/'compose.json',config);self.config=config;run(self.dc+['up','-d','jaeger-agent'],self.out/'jaeger_up.log')
  for _ in range(60):
   info=self.info('jaeger-agent');ip=next(x['IPAddress'] for x in info['NetworkSettings']['Networks'].values())
   try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://'+ip+':14269/',timeout=1) as resp:
     if resp.status==200:break
   except OSError:pass
   time.sleep(1)
  else:raise RuntimeError('Jaeger readiness failed')
  backends=[n for n in config['services'] if n.endswith(('-mongodb','-memcached','-redis'))];run(self.dc+['up','-d',*backends],self.out/'backends_up.log')
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
    with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/',timeout=2):break
   except urllib.error.HTTPError:break
   except OSError:time.sleep(1)
  else:raise RuntimeError('Nginx readiness failed')
  # Official Reed98 social graph; every initialization response is checked.
  graph=SN/'datasets/social-graph/socfb-Reed98';nodes=int((graph/'socfb-Reed98.nodes').read_text());assert nodes==962
  edges=[tuple(map(int,l.split())) for l in (graph/'socfb-Reed98.edges').read_text().splitlines() if l.strip()];assert all(0<=u<nodes and 0<=v<nodes for u,v in edges)
  def post(item):
   endpoint,payload=item;body=urllib.parse.urlencode(payload).encode()
   with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/wrk2-api/'+endpoint,data=body,timeout=30) as resp:
    data=resp.read();assert resp.status==200 and data.strip()==b'Success!',(resp.status,data[:200])
  with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
   list(pool.map(post,[('user/register',dict(first_name=f'first_name_{i}',last_name=f'last_name_{i}',username=f'username_{i}',password=f'password_{i}',user_id=i)) for i in range(nodes)]))
   follows=[('user/follow',dict(user_name=f'username_{u}',followee_name=f'username_{v}')) for a,b in edges for u,v in [(a,b),(b,a)]];list(pool.map(post,follows))
  save(self.out/'dataset_validation.json',dict(graph='socfb-Reed98',nodes=nodes,edges=len(edges),registered_users=nodes,successful_directed_follows=len(follows),edge_sha256=sha(graph/'socfb-Reed98.edges'),validation='Every register/follow response status and success body checked; compose-only benchmark initializes posts during warmup'))
  self.states={n:self.info(n) for n in config['services']};save(self.out/'runtime.json',{n:dict(pid=i['State']['Pid'],image=i['Image'],restart=i['RestartCount']) for n,i in self.states.items()})
  save(self.out/'binary_hashes.json',{k:dict(path=str(self.overrides.get(k,BUILD/k/'base'/exe)),sha256=sha(self.overrides.get(k,BUILD/k/'base'/exe))) for k,(_,exe,_) in TARGETS.items()})

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--qualify',action='store_true');p.add_argument('--service',choices=list(TARGETS));p.add_argument('--binary',type=Path);p.add_argument('--rate',type=int,default=300);p.add_argument('--seed',type=int,default=123);a=p.parse_args()
 a.out.mkdir(parents=True,exist_ok=False);stack=Stack(a.out,{a.service:a.binary} if a.binary else {})
 save(a.out/'harness_hashes.json',{p.name:sha(p) for p in B.glob('*.py')})
 def interrupt(signum,frame):raise KeyboardInterrupt(signum)
 signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
 try:
  stack.start();rows=[]
  if a.qualify:
   for rate in [150,300,600]:
    for layout in ['alone','shared']:
     rows.append(trial(stack,a.out/f'{layout}_{rate}',rate,layout));save(a.out/'summary.json',rows)
   selected={}
   for key in TARGETS:
    candidates=[]
    for rate in [150,300,600]:
     pair={r['layout']:r for r in rows if r['rate']==rate};shared=pair['shared']['services'][key];alone=pair['alone']['services'][key];mpki=shared['post_pmu']['mpki'];ratio=mpki/alone['post_pmu']['mpki']
     if shared['valid'] and alone['valid'] and pair['shared']['pool_util_pct']>=15 and mpki>=5 and ratio>=2:candidates.append(dict(rate=rate,mpki=mpki,alone_mpki=alone['post_pmu']['mpki'],inflation=ratio))
    selected[key]=max(candidates,key=lambda x:x['mpki']) if candidates else dict(status='No valid >=15% pool utilization, >=5 shared MPKI and >=2x MPKI inflation point')
   save(a.out/'selected.json',selected)
  else:save(a.out/'summary.json',[trial(stack,a.out/'measurement',a.rate,'shared',a.seed,primary_only=confirmation_primary_only(a.out))])
 finally:stack.close()
if __name__=='__main__':main()
