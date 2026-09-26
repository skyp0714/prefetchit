"""Audit AUX loss and derive long call-path candidates from recorded native PT.

PEBS ranks functions; PT supplies ordered calls. Associations are candidate
selection evidence, not causal miss coverage or a performance upper bound.
"""
from pathlib import Path
import argparse,bisect,collections,hashlib,json,os,re,struct,subprocess

def records(path):
 counts=collections.Counter();flags=collections.Counter();lost=0;auxbytes=0
 with path.open('rb') as f:
  h=f.read(104);assert h[:8]==b'PERFILE2';offset,size=struct.unpack_from('<QQ',h,40);pos=offset
  while pos<offset+size:
   f.seek(pos);head=f.read(8);kind,misc,n=struct.unpack('<IHH',head);assert n>=8
   body=f.read(n-8);counts[kind]+=1;pos+=n
   if kind==11:
    ao,az,af=struct.unpack_from('<QQQ',body);flags[af]+=1
   elif kind==2:lost+=struct.unpack_from('<QQ',body)[1]
   elif kind==13:lost+=struct.unpack_from('<Q',body)[0]
   elif kind==71:
    az=struct.unpack_from('<Q',body)[0];auxbytes+=az;pos+=az
  assert pos==offset+size,(pos,offset+size)
 return dict(record_types=dict(counts),aux_flags=dict(flags),lost_samples=lost,auxtrace_bytes=auxbytes,
             no_truncation_gaps_collision=not any(k & 0xd for k in flags) and lost==0)

def main():
 a=argparse.ArgumentParser();a.add_argument('capture',type=Path);args=a.parse_args();d=args.capture
 os.sched_setaffinity(0,{84,85});audit=records(d/'perf.data')
 meta=json.loads((d/'metadata.json').read_text());exe=Path(meta['executable'])
 with exe.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==meta['sha256']
 with exe.open('rb') as f:
  h=f.read(64);assert h[:6]==b'\x7fELF\x02\x01';phoff=struct.unpack_from('<Q',h,32)[0];ents,n=struct.unpack_from('<HH',h,54)
  loads=[]
  for i in range(n):
   f.seek(phoff+i*ents);v=struct.unpack('<IIQQQQQQ',f.read(56))
   if v[0]==1 and v[1]&1:loads.append((v[2],v[3],v[5]))
 mappings=[]
 for line in (d/'maps.txt').read_text().splitlines():
  x=line.split(maxsplit=5)
  if len(x)!=6 or x[5]!=str(exe) or 'x' not in x[1]:continue
  lo,hi=[int(z,16) for z in x[0].split('-')];off=int(x[2],16)
  for po,pv,pz in loads:
   if po//4096*4096<=off<po+pz:
    mappings.append((lo,hi,lo-(pv+off-po)))
 assert mappings
 raw=subprocess.check_output(['nm','-n','-S','--defined-only',str(exe)],text=True)
 symbols=[]
 for line in raw.splitlines():
  z=line.split(maxsplit=3)
  if len(z)==4 and z[2] in 'tTwW':symbols.append((int(z[0],16),int(z[1],16),z[3]))
 symbols.sort();starts=[x[0] for x in symbols];cache={}
 def symbol(pc):
  if pc in cache:return cache[pc]
  for lo,hi,slide in mappings:
   if lo<=pc<hi:
    addr=pc-slide;i=bisect.bisect_right(starts,addr)-1
    if i>=0 and addr<symbols[i][0]+symbols[i][1]:cache[pc]=i;return i
  cache[pc]=None;return None
 cmd=['perf','script','-i',str(d/'perf.data'),'--no-itrace','--show-lost-events','-F','event,ip,period']
 q=subprocess.run(cmd,text=True,capture_output=True);(d/'pebs_decode.log').write_text(q.stderr);assert q.returncode==0
 heat=collections.Counter();pages=collections.Counter();total=0;outside=0
 for line in q.stdout.splitlines():
  m=re.match(r'\s*(\d+)\s+cpu/.+:\s+([0-9a-fA-F]+)\s*$',line)
  if not m:continue
  ip=int(m[2],16);total+=1;i=symbol(ip);pages[ip//4096]+=1
  if i is not None:heat[i]+=1
  else:outside+=1
 top=set(i for i,n in heat.most_common(32));histories={};correl=collections.Counter();trigger_counts=collections.Counter();lead={};calls=0;matched=0;decode_errors=0
 rx=re.compile(r'\s*(\d+)/(\d+)\s+([0-9]+\.[0-9]+):\s+branches(?::[a-z]+)?:\s+([0-9a-f]+)\s+=>\s+([0-9a-f]+)')
 cmd=['perf','script','-i',str(d/'perf.data'),'--ns','--itrace=ce','--show-lost-events','-F','pid,tid,time,event,ip,addr']
 with (d/'call_decode.log').open('w') as err:
  p=subprocess.Popen(cmd,text=True,stdout=subprocess.PIPE,stderr=err)
  for line in p.stdout:
   if 'error' in line.lower() or 'LOST' in line:decode_errors+=1
   m=rx.match(line)
   if not m:continue
   calls+=1;tid=int(m[2]);ns=int(m[3].replace('.',''));source=int(m[4],16);target=int(m[5],16)
   hist=histories.setdefault(tid,collections.deque(maxlen=256));idx=symbol(target)
   if idx in top:
    matched+=1
    for depth in [1,4,16,64,256]:
     if len(hist)<depth:continue
     prior,stamp=hist[-depth];key=(prior,idx,depth);delta=ns-stamp
     if delta<0:continue
     correl[key]+=1
     if key not in lead:lead[key]=[0,delta,delta]
     entry=lead[key];entry[0]+=delta;entry[1]=min(entry[1],delta);entry[2]=max(entry[2],delta)
   trigger_counts[source]+=1
   hist.append((source,ns))
  rc=p.wait()
 hot=[dict(symbol=symbols[i][2],elf_address=hex(symbols[i][0]),bytes=symbols[i][1],samples=n) for i,n in heat.most_common(100)]
 rows=[]
 for key,count in correl.most_common(2000):
  src,idx,depth=key;i=symbol(src);v=lead[key]
  rows.append(dict(trigger_runtime_ip=hex(src),trigger_elf_ip=next((hex(src-slide) for lo,hi,slide in mappings if lo<=src<hi),None),trigger_symbol=symbols[i][2] if i is not None else None,
      target_symbol=symbols[idx][2],target_elf_address=hex(symbols[idx][0]),preceding_calls=depth,
      trigger_total_calls=trigger_counts[src],cooccurrences=count,conditional_occurrence=count/trigger_counts[src],mean_trace_delta_ns=v[0]/count,min_trace_delta_ns=v[1],max_trace_delta_ns=v[2]))
 result=dict(aux_audit=audit,pebs_samples=total,pebs_outside_main_executable=outside,hot_functions=hot,
   pebs_code_pages=len(pages),decoded_calls=calls,hot_function_calls=matched,decoder_exit=rc,decode_error_records=decode_errors,
   candidates=rows,scope='Same capture PEBS function heat and full ordered PT calls. Timestamp deltas are PT timing estimates, not exact per-instruction cycle latency. No speedup or causal miss coverage claim.')
 (d/'path_analysis.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in ['hot_functions','candidates']}),flush=True)
 assert rc==0 and decode_errors==0 and audit['no_truncation_gaps_collision'],'Trace quality failure: retain diagnostics and do not use candidate results'
if __name__=='__main__':main()
