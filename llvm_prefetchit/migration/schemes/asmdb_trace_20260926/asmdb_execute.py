"""Prepare, validate, screen, and independently confirm trace-guided native insertion."""
from pathlib import Path
import ast,collections,csv,hashlib,json,math,os,re,shutil,statistics,subprocess,sys,time
from scipy.stats import t
from asmdb_prepare import B,R,T,BASE,REPO,save
from asmdb_plan import make,coverage
from asmdb_rewrite import rewrite
S=R.parent
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def command(cmd,log,**kw):
 assert shutil.disk_usage(R).free>30*2**30
 with (R/log).open('w') as f:q=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,**kw)
 save(R/(log+'.command.json'),dict(command=list(map(str,cmd)),exit=q.returncode));assert q.returncode==0,(cmd,log)
def calibrate():
 binary=R/'latency';command(['g++','-O2','-std=c++17',str(B/'asmdb_latency.cc'),'-o',str(binary)],'latency_build.log')
 out=R/'latency_platform';cmd=['python3',str(REPO/'llvm_prefetchit/scripts/static/run_with_platform.py'),'--out',str(out),'--cpus','32','taskset','-c','32',str(binary)]
 command(cmd,'latency.log');values=[]
 for line in (R/'latency.log').read_text().splitlines():
  x=line.split()
  if len(x)==3 and x[0] in ['16','32']:values.append(dict(mib=int(x[0]),rep=int(x[1]),ns=float(x[2])))
 assert len(values)==6
 ctr=json.loads((T.parent/'counter_summary.json').read_text())['counters'];ipc=ctr['instructions:u']/ctr['cycles:u'];ns=statistics.median(r['ns'] for r in values);d=max(16,round(ns*2*ipc))
 save(R/'calibration.json',dict(rows=values,median_ns=ns,core_ghz=2,baseline_ipc=ipc,d_instructions=d,scope='dependent random cache-line chain16/32MiB warmed and fitting LLC but exceeding2MiB L2; latency proxy, not exact instruction-side fill latency; d=latency_ns*2GHz*measuredbaselineIPC',windows=[dict(name='short',low=max(8,d//2),high=max(8,d//2)+128),dict(name='nominal',low=d,high=d+256),dict(name='long',low=2*d,high=2*d+512)]))
 return json.loads((R/'calibration.json').read_text())
def decode():
 ins=json.loads((R/'instructions.json').read_text());im=json.loads((R/'image.json').read_text());heat=json.loads((R/'pebs_heat.json').read_text());mapping=R/'mapping.tsv';seq=R/'instructions.bin'
 with mapping.open('w') as mf:
  for r in ins:
   flow=0;dest=0;asm=r['asm'];branch=re.search(r'\b(j\w*|callq?|retq?|loop\w*|syscall|sysret|int\w*)\b',asm)
   if branch:
    flow=3;direct=re.search(r'\b(j\w*|callq?|loop\w*)\s+([0-9a-f]+)\b',asm)
    if direct:flow=2 if direct[1] in ['jmp','jmpq','call','callq'] else 1;dest=int(direct[2],16)+im['slide']
   mf.write(f"{r['id']} {r['va']+im['slide']} {r['va']&~63} {0 if r['kind']=='none' else 1 if r['kind']=='nop' else 2} {r['va']+im['slide']+len(bytes.fromhex(r['bytes']))} {flow} {dest}\n")
 minimum_line_samples=int(os.environ.get('ASMDB_MIN_LINE_SAMPLES','2'))
 targets=sorted(((int(k),v) for k,v in heat['lines'].items() if v>=minimum_line_samples),key=lambda kv:(-kv[1],kv[0]))[:8192 if minimum_line_samples==1 else 4096];(R/'targets.txt').write_text(''.join(f'{k}\n' for k,v in targets))
 command(['g++','-O3','-std=c++17',str(B/'asmdb_stream.cc'),'-o',str(R/'stream')],'stream_build.log')
 validate_histories()
 windows=json.loads((R/'windows.json').read_text())['windows'];stats=[]
 with seq.open('wb') as merged:
  for i,(lo,hi) in enumerate(windows):
   cmd=['perf','script','-i',str(T/'perf.data'),'--ns','--itrace=i1ie','--time',f'{lo:.9f},{hi:.9f}','-F','pid,tid,event,ip']
   dst=R/f'window{i}.bin';stat=R/f'window{i}_stats.json'
   with (R/f'window{i}_decoder.log').open('w') as err:
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=err)
    q=subprocess.run([str(R/'stream'),'decode',str(mapping),str(dst),str(stat)],stdin=p.stdout);p.stdout.close();rc=p.wait()
   save(R/f'window{i}_command.json',dict(command=cmd,decoder_exit=rc,parser_exit=q.returncode));assert rc==q.returncode==0
   row=json.loads(stat.read_text());assert row['decode_errors']==0 and row['instructions']>10000;stats.append(row)
   with dst.open('rb') as f:shutil.copyfileobj(f,merged,1024*1024)
   receipt=dict(path=str(dst),bytes=dst.stat().st_size,sha256=sha(dst),reason='window compact stream merged; no duplicate decoded copy retained');dst.unlink();save(R/f'window{i}_cleanup.json',receipt)
 save(R/'decode_summary.json',dict(windows=stats,bytes=seq.stat().st_size,sha256=sha(seq),target_lines=len(targets),pebs_weight_covered=100*sum(v for k,v in targets)/heat['samples']))
 return seq
def validate_histories():
 import array,random
 mapping=R/'history_test_mapping.tsv';mapping.write_text('1 4096 4096 2\n2 8192 8192 0\n3 12288 12288 0\n4 16384 16384 1\n')
 targets=R/'history_test_targets.txt';targets.write_text('12288\n')
 rng=random.Random(15)
 cases=[[1,2,3,2,3,2,2,2,2,2]*100,[1,2,0,3,2,2,2]*100,[rng.choice([1,2,2,2,3,4]) for _ in range(3000)]]
 for index,seq in enumerate(cases):
  binary=R/f'history_test{index}.bin';binary.write_bytes(array.array('I',seq).tobytes());out=R/f'history_test{index}.tsv'
  command([str(R/'stream'),'pairs',str(mapping),str(binary),str(targets),'2','4',str(out)],f'history_test{index}.log')
  expected={};start=0
  while start<len(seq):
   while start<len(seq) and seq[start]==0:start+=1
   end=start
   while end<len(seq) and seq[end]:end+=1
   for pos in range(start,end):
    s=seq[pos]
    if s not in [1,4]:continue
    hit=any(seq[j]==3 and (j==start or seq[j-1]!=3) for j in range(pos+2,min(pos+5,end)))
    n,f=expected.get(s,(0,0));expected[s]=(n+int(hit),f+1)
   start=end+1
  with out.open() as f:f.readline();actual={int(r['site_id']):(int(r['hits']),int(r['triggers'])) for r in csv.DictReader(f,delimiter='\t')}
  assert actual=={s:v for s,v in expected.items() if v[0]>=8},(index,actual,expected)
 save(R/'history_tests.json',dict(passed=3,scope='independent forward-window oracle checks repeated target deduplication, gaps, trigger denominator and randomized multi-site histories'))
def validate_rewriter():
 # Exercise instruction relocation with live flags, a register result, and same-size NOP.
 src=R/'rewrite_check.S';src.write_text('''.text
.global probe
.type probe,@function
probe:
 leal 0x12345678(%rdi),%eax
 cmpl $0x12345678,%eax
 sete %dl
 movzbl %dl,%edx
 addl %edx,%eax
 .byte 0x0f,0x1f,0x80,0,0,0,0
 ret
.size probe,.-probe
.section .note.GNU-stack,"",@progbits
''')
 c=R/'rewrite_check.c';c.write_text('''#include <stdint.h>
extern uint32_t probe(uint32_t);
int main(){for(uint32_t i=0;i<20000;i++){uint32_t x=i*1777777u;uint32_t v=x+0x12345678u;v+=(v==0x12345678u);if(probe(x)!=v)return 1;}return 0;}
''')
 base=R/'rewrite_check';command(['gcc','-O2','-fPIE','-pie',str(c),str(src),'-o',str(base)],'rewrite_check_build.log')
 raw=subprocess.check_output(['objdump','-d','--insn-width=16',str(base)],text=True);rows=[];inside=False
 for line in raw.splitlines():
  if '<probe>:' in line:inside=True;continue
  if inside and not line.strip():break
  if not inside:continue
  x=line.split('\t')
  if len(x)<3:continue
  try:va=int(x[0].strip().rstrip(':'),16);code=bytes.fromhex(x[1])
  except ValueError:continue
  if len(code)>=5:rows.append(dict(va=va,bytes=code.hex(),asm=x[2],kind='nop' if 'nop' in x[2] else 'detour'))
 assert len(rows)>=3
 for row in rows:row['targets']=[rows[0]['va']&~63]
 rewritten=R/'rewrite_check_pf';patch=rewrite(base,rewritten,dict(sites=rows))
 for binary in [base,rewritten,Path(str(rewritten)+'.nop')]:command([str(binary)],binary.name+'.test.log')
 save(R/'rewrite_test.json',dict(status='passed',cases='20000 inputs including flags producer/consumer and wraparound; original, PF, matchedNOP',sites=len(rows),sha256=patch['prefetch_sha256']))
def compare(directory,arms,reps,seed):
 cmd=['python3',str(REPO/'llvm_prefetchit/scripts/static/measure_class_a.py'),'--out',str(directory),'--cpu','32','--iterations','100','--reps',str(reps),'--seed',str(seed),*[k+'='+str(v) for k,v in arms.items()]]
 command(cmd,directory.name+'.log',cwd=REPO)
 rows=list(csv.DictReader((directory/'runs.csv').open()));assert len(rows)==reps*len(arms)
 groups={a:{int(r['rep']):r for r in rows if r['arm']==a} for a in arms}
 def effect(arm,ref):
  vals=[math.log(float(groups[ref][i]['cpu_ns_per_op'])/float(groups[arm][i]['cpu_ns_per_op'])) for i in range(1,reps+1)];mean=statistics.mean(vals);half=t.ppf(.975,reps-1)*statistics.stdev(vals)/math.sqrt(reps)
  return dict(speedup_pct=100*math.expm1(mean),ci95_pct=[100*math.expm1(mean-half),100*math.expm1(mean+half)])
 results=[]
 for arm in arms:
  if arm in ['base','static'] or arm.endswith('_nop'):continue
  results.append(dict(arm=arm,reps=reps,seed=seed,comparisons={ref:effect(arm,ref) for ref in ['base','static',arm+'_nop']},mean_l2_mpki=statistics.mean(float(r['l2_mpki']) for r in groups[arm].values())))
 report=dict(results=results,static_vs_base=effect('static','base'),mean_l2_mpki={a:statistics.mean(float(r['l2_mpki']) for r in g.values()) for a,g in groups.items()},scope='paired CPU efficiency on fixed work; seed and repetitions recorded per result, screening/confirmation stage explicit in output path; each policy and its NOP share code layout')
 save(directory/'paired_summary.json',report);return report
def cleanup(paths,reason,name):
 removed=[]
 for p in paths:
  if not p.exists():continue
  assert p.parent==R and not p.is_symlink();removed.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p),reason=reason));p.unlink()
 save(R/name,dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed),free=shutil.disk_usage(R).free))
def main():
 os.chdir(REPO);os.sched_setaffinity(0,{84,85});assert os.geteuid()==0
 save(R/'protocol.json',dict(primary='FleetBench upstream Arena unchanged fixed iterations',training='original baseline seed0 IntelPT+L2 PEBS, fourpredeclared10mswindows',selection='three calibrated instruction-distance windows; min32hits/P>=.8; max512sites,4paths/target,4targets/detour; estimated extra dynamic instructions<=1.5%',screen='three fresh seed1 paired repetitions against base, existing schema static, and own exact-layout NOP',confirmation='if best screen mean gain vsbase>=.5% and vsNOP>0, seven fresh seed2 paired repetitions. No pooling, no valid outlier deletion. Report base/static/NOP contrasts regardless significance.',limitations='ordinary T1 data prefetch, not paper hardware instruction; main-image target coverage; short baseline training trace; PEBS weights not per-instance cache simulation; async unwind in detour stubs unsupported'))
 validate_rewriter();cal=calibrate();seq=decode();plans=[]
 for w in cal['windows']:
  name=w['name'];command([str(R/'stream'),'pairs',str(R/'mapping.tsv'),str(seq),str(R/'targets.txt'),str(w['low']),str(w['high']),str(R/(name+'_pairs.tsv'))],name+'_planner.log')
  plan=make(name,w['low'],w['high']);assert plan['sites'],'No eligible histories: preserve diagnosis before parameter changes';save(R/(name+'_joint_coverage.json'),coverage(plan,seq));plans.append(plan)
  print(json.dumps(dict(stage='plan',name=name,sites=len(plan['sites']),hints=sum(len(r['targets']) for r in plan['sites']),added_instruction_pct=plan['estimated_added_dynamic_instructions_pct'])),flush=True)
 arms={'base':BASE,'static':S/'fleet_filters/static_all'};variantpaths=[]
 for plan in plans:
  name=plan['name'];out=R/name;patch=rewrite(BASE,out,plan);variantpaths.extend([out,Path(str(out)+'.nop')])
  for binary in [out,Path(str(out)+'.nop')]:
   for seed in [0,1,2]:
    cmd=['taskset','-c','32',str(binary),'--benchmark_filter=^BM_PROTO_Arena$','--benchmark_min_time=1x',f'--seed={seed}','--benchmark_format=json'];command(cmd,binary.name+f'_smoke{seed}.json',timeout=60)
    data=json.loads((R/(binary.name+f'_smoke{seed}.json')).read_text());assert len(data['benchmarks'])==1 and not data['benchmarks'][0].get('error_occurred')
  arms[name]=out;arms[name+'_nop']=Path(str(out)+'.nop')
 cleanup([seq,R/'instructions.json',R/'mapping.tsv',R/'stream',R/'latency',R/'rewrite_check',R/'rewrite_check_pf',R/'rewrite_check_pf.nop'], 'analysis/semantic validation completed; raw PT, source, selected plans, hashes and audits retained','pre_timing_cleanup.json')
 report=compare(R/'screen',arms,3,1);qualified=[r for r in report['results'] if r['comparisons']['base']['speedup_pct']>=.5 and r['comparisons'][r['arm']+'_nop']['speedup_pct']>0]
 winner=max(qualified,key=lambda r:r['comparisons']['base']['speedup_pct'])['arm'] if qualified else None
 losers=[p for p in variantpaths if winner is None or p.name not in [winner,winner+'.nop']];cleanup(losers,'failed/superseded screen; all paired results and exact patches retained','screen_cleanup.json')
 if winner:
  confirmation=compare(R/'confirmation',{k:v for k,v in arms.items() if k in ['base','static',winner,winner+'_nop']},7,2)
  result=confirmation['results'][0];retained=all(result['comparisons'][ref]['ci95_pct'][0]>0 for ref in ['base',winner+'_nop'])
  if not retained:cleanup([arms[winner],arms[winner+'_nop']],'independent confirmation did not support positive vsbothbase/NOP','confirmation_cleanup.json')
 else:confirmation=None;retained=False
 save(R/'completed.json',dict(screen=report,selected=winner,confirmation=confirmation,retained_candidate=retained,scope='FleetBench only; no new workload generalization claim'))
 print(json.dumps(dict(stage='completed',winner=winner,retained=retained)),flush=True)
if __name__=='__main__':main()
