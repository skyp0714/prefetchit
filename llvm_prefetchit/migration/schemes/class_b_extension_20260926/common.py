from pathlib import Path
import csv,datetime,hashlib,json,os,shutil,signal,subprocess,time
REPO=Path('/home/hnpark2/prefetchit');B=Path(__file__).resolve().parent
S=Path(os.environ.get('CLASS_B_STORAGE_ROOT','/storage/prefetchit/class_b_extension_20260926'));T=Path(os.environ.get('CLASS_B_TRACE_ROOT','/trace/prefetchit/class_b_extension_20260926'))
REPORT_SUFFIX=os.environ.get('CLASS_B_REPORT_SUFFIX','');assert REPORT_SUFFIX in ['', '_sampling10']
EVIDENCE=REPO/('llvm_prefetchit/migration/evidence/class_b_extension_20260926'+REPORT_SUFFIX)
RESULT_DOC=REPO/('docs/class_b_extension_results_20260926'+REPORT_SUFFIX+'.md')
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2,default=str)+'\n');tmp.replace(p)
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(cmd,log,timeout=1200,**kwargs):
 log.parent.mkdir(parents=True,exist_ok=True);save(log.with_suffix('.command.json'),cmd)
 with log.open('w') as f:subprocess.run(list(map(str,cmd)),stdout=f,stderr=subprocess.STDOUT,check=True,timeout=timeout,**kwargs)
def space():
 assert shutil.disk_usage(REPO).free>7*2**30
 assert shutil.disk_usage('/storage').free>30*2**30
def ensure_local(path):
 path=Path(path)
 if not path.is_symlink():return path
 remote=path.resolve()
 if not str(remote).startswith('/fast-lab-share/hnpark2/'):return path
 space();plan=json.loads((S/'cold_backup_plan.json').read_text());row=next(x for x in plan['files'] if S/x['path']==path)
 assert remote==Path(plan['destination'])/row['path']
 assert subprocess.run(['pgrep','-x','rsync'],stdout=subprocess.DEVNULL).returncode==1,'Another NAS transfer is active'
 temp=path.with_name(path.name+'.stage-partial')
 run(['rsync','-rt','--partial','--bwlimit=20480','--timeout=60',str(remote),str(temp)],path.with_name(path.name+'.stage.log'),timeout=14400)
 assert temp.stat().st_size==row['bytes'] and sha(temp)==row['sha256']
 temp.chmod(row['mode']);temp.replace(path)
 save(path.with_name(path.name+'.staged.json'),dict(source=str(remote),sha256=row['sha256'],bytes=row['bytes'],verified_local=True))
 return path
def platform(name,cmd):
 space();p=S/('platform_'+name)
 try:run(['python3',B/'run_platform.py','--out',p,'--cpus','16-19,32-43',*cmd],S/(name+'.log'),timeout=14400)
 finally:
  checks=[]
  for cpu in p.glob('cpu*'):
   for kind in ['platform','hwp']:
    before=cpu/(kind+'_before.json');after=cpu/(kind+'_restored.json')
    checks.append(before.exists() and after.exists() and json.loads(before.read_text())==json.loads(after.read_text()))
  save(S/(name+'_restore.json'),dict(restored=bool(checks) and all(checks),checks=len(checks)))
  assert checks and all(checks),'Platform restoration must be checked before any next stage'
def stop(p):
 if p and p.poll() is None:
  os.killpg(p.pid,signal.SIGTERM)
  try:p.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
def cpu(pid):
 group=next(x.split('::')[1] for x in Path(f'/proc/{pid}/cgroup').read_text().splitlines() if x.startswith('0::'))
 path=Path('/sys/fs/cgroup')/group.lstrip('/')/'cpu.stat'
 return dict(path=str(path),epoch=time.time(),time=time.monotonic(),values={k:int(v) for k,v in map(str.split,path.read_text().splitlines())})
def diff_cpu(a,b):
 assert a['path']==b['path'];d={k:b['values'][k]-a['values'][k] for k in a['values']};assert d.get('nr_throttled',0)==0 and d['usage_usec']>=0
 return dict(start=a['epoch'],end=b['epoch'],wall_s=b['time']-a['time'],cpu_us=d['usage_usec'],user_us=d['user_usec'],system_us=d['system_usec'],delta=d)
EVENTS='instructions:u,cycles:u,cpu/event=0x24,umask=0x24,name=L2I/u,context-switches,{slots:u,topdown-retiring:u,topdown-bad-spec:u,topdown-fe-bound:u,topdown-be-bound:u,topdown-fetch-lat:u}'
def counters(p):
 vals={};scheduled=True
 for row in csv.reader(p.open()):
  if len(row)<5 or row[0].startswith('#'):continue
  try:
   vals[row[2]]=float(row[0])
   try:float(row[3]);percentage_index=4
   except ValueError:percentage_index=5
   scheduled &= float(row[percentage_index])>=99.99
  except (ValueError,IndexError):scheduled=False
 assert vals.get('instructions:u',0)>0
 return dict(counters=vals,fully_scheduled=scheduled,mpki=1000*vals['L2I']/vals['instructions:u'])
