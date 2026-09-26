"""Fresh baseline PT captures of eligible interleaved services, never timing arms."""
from common import *
from media import Stack,TARGETS,BUILD
import argparse,gzip,re,collections

def sanitize(out):
 errors=(out/'decoder_errors.txt').read_text().strip();raw=out/'branches.txt'
 quality=dict(decoder_error_records=len(errors.splitlines()) if errors else 0,excluded_tids=[],raw_sha256=sha(raw),policy='All decoder errors reject the capture. Snapshot the target vDSO as well as file-backed mappings. Only complete switch-IN/OUT runs are planned.')
 save(out/'trace_quality.json',quality);assert not errors,errors[:500]
 return quality

def capture(stack,key,out):
 space();out.mkdir(parents=True,exist_ok=False);name,exe,_=stack.targets[key];build_root=stack.build_root;pid=stack.states[name]['State']['Pid'];proc=Path(f'/proc/{pid}')
 maps=(proc/'maps').read_text();(out/'maps.txt').write_text(maps);symfs=out/'symfs';symfs.mkdir();mapped=[]
 for line in maps.splitlines():
  row=line.split()
  if len(row)<6 or 'x' not in row[1] or not row[5].startswith('/'):continue
  path=row[5];target=symfs/path.lstrip('/')
  if target.exists():continue
  source=proc/'root'/path.lstrip('/');assert source.is_file();target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
  mapped.append(dict(path=path,bytes=target.stat().st_size,sha256=sha(target)))
 # vDSO is executable code supplied by the kernel, not a filesystem DSO.
 vdso_line=next(line for line in maps.splitlines() if '[vdso]' in line)
 lo,hi=[int(x,16) for x in vdso_line.split()[0].split('-')]
 with (proc/'mem').open('rb',buffering=0) as f:vdso=os.pread(f.fileno(),hi-lo,lo)
 assert len(vdso)==hi-lo and vdso.startswith(b'\x7fELF')
 (symfs/'[vdso]').write_bytes(vdso);mapped.append(dict(path='[vdso]',bytes=len(vdso),sha256=sha(symfs/'[vdso]')))
 assert sha(symfs/'custom'/exe)==sha(build_root/key/'base'/exe)
 group=str(Path(cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
 event=os.environ.get('CLASS_B_PT_EVENT','intel_pt//u');aux=os.environ.get('CLASS_B_PT_AUX','16M')
 command=['perf','record','--no-buildid-cache','-e',event,'--switch-events','--delay','100','-m','8M,'+aux,'-a','-C','32-39','-G',group,'-o',str(out/'pt.data'),'--','sleep','0.30']
 run(command,out/'record.log');record=(out/'record.log').read_text();assert not re.search(r'\b(lost|truncated)\b',record,re.I),record
 save(out/'capture_record.json',dict(pid=pid,exe=exe,build_root=build_root,key=key,mapped=mapped,record=record))
 return out

def decode(out):
 metadata=json.loads((out/'capture_record.json').read_text());pid=metadata['pid'];exe=metadata['exe'];build_root=Path(metadata['build_root']);key=metadata['key'];mapped=metadata['mapped'];record=metadata['record'];symfs=out/'symfs'
 assert not Path(f'/proc/{pid}').exists(),'Decode against the frozen symfs only after the recorded process exits'
 cmd=['perf','script','-i',str(out/'pt.data'),'--symfs='+str(symfs),'--pid='+str(pid),'--itrace=b','--show-switch-events','-F','tid,time,ip,addr,flags']
 save(out/'decode_command.json',cmd)
 with (out/'branches.txt').open('w') as f,(out/'decode.err').open('w') as err:subprocess.run(cmd,stdout=f,stderr=err,check=True)
 cmd=['perf','script','-i',str(out/'pt.data'),'--symfs='+str(symfs),'--pid='+str(pid),'--itrace=e']
 with (out/'decoder_errors.txt').open('w') as f,(out/'error_decode.err').open('w') as err:subprocess.run(cmd,stdout=f,stderr=err,check=True)
 quality=sanitize(out)
 # Branch order is an execution-order approximation, not a retired-miss oracle.
 counts=dict(branches=0,switch_in=0,switch_out=0,unparsed=0);rb=re.compile(r'^\s*\d+\s+\d+\.\d+:\s+.*?\s*[0-9a-f]+\s+=>\s+[0-9a-f]+\s*$');rs=re.compile(r'PERF_RECORD_SWITCH(?:_CPU_WIDE)?\s+(IN|OUT)')
 with (out/'branches.txt').open() as f:
  for line in f:
   if rb.match(line):counts['branches']+=1
   elif (match:=rs.search(line)):counts['switch_'+match[1].lower()]+=1
   elif line.strip():counts['unparsed']+=1
 assert counts['branches']>1000 and min(counts['switch_in'],counts['switch_out'])>=8,counts
 save(out/'capture.json',dict(pid=pid,binary_sha256=sha(build_root/key/'base'/exe),mapped=mapped,counts=counts,quality=quality,record_log=record,decode_stderr=(out/'decode.err').read_text(),scope='PT branch reconstruction and context switches; 0.30s workload with 100ms deferred enable; unmodified baseline at selected shared rate. No decoder errors accepted; incomplete boundary runs are excluded.'))
 ws=REPO/'flat_codegen/dsb_build/media/ws'
 run(['python3',B/'run_paths.py',out,'--symfs',symfs,'--exe','/custom/'+exe,'--instrumentable',build_root/key/'base/instrumentable.txt','--min-runs','8','--resume-context','--out',out/'runs'],out/'run_paths.log')
 return out

def main():
 out=S/'media_trace_stack';out.mkdir(exist_ok=False);selected=json.loads((S/'media_qualification_v2/audited_selected.json').read_text());eligible={k:v for k,v in selected.items() if 'rate' in v}
 if not eligible:save(out/'skipped.json',selected);return
 stack=Stack(out);client=None
 def interrupt(signum,frame):raise KeyboardInterrupt(signum)
 signal.signal(signal.SIGTERM,interrupt)
 try:
  stack.start();stack.layout('shared')
  for rate in sorted({v['rate'] for v in eligible.values()}):
   d=out/str(rate);d.mkdir();cmd=['python3',str(B/'load.py'),'--out',str(d),'--rate',str(rate),'--seconds','125','--seed','37']
   with (d/'client.log').open('w') as log:client=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   time.sleep(55);assert client.poll() is None
   for key,v in eligible.items():
    if v['rate']==rate:capture(stack,key,T/key)
   rc=client.wait(timeout=180);client=None;info=json.loads((d/'load.json').read_text());assert rc==0 and not info.get('steady_errors',info['errors']) and not info.get('steady_drops',info['dropped']);stack.check()
 finally:stop(client);stack.close()
 for key in eligible:decode(T/key)
 save(out/'completed.json',dict(services=list(eligible),status='all captures, full load validation and offline decodes passed'))

if __name__=='__main__':main()
