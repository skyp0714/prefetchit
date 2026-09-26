"""Prepare exact native instruction windows; profile weights remain PEBS sample weights."""
from pathlib import Path
import collections,hashlib,json,os,re,shutil,struct,subprocess,sys
import lief
B=Path(__file__).resolve().parent;REPO=B.parents[2]
R=Path(os.environ.get('ASMDB_RESULT_DIR','/storage/prefetchit/class_a_expansion_20260925/asmdb_trace'))
T=Path('/trace/prefetchit/class_a_expansion_20260925/fleet_probe/l2');BASE=T.parent/'baseline'
sys.path.insert(0,str(REPO/'llvm_prefetchit/tools'))
from index_executable_padding import is_padding_nop
from audit_pt_paths import records
def save(p,x):p.write_text(json.dumps(x,indent=2))
def main():
 os.sched_setaffinity(0,{84,85});assert shutil.disk_usage(R).free>40*2**30
 meta=json.loads((T/'metadata.json').read_text());assert hashlib.sha256(BASE.read_bytes()).hexdigest()==meta['sha256']
 audit=records(T/'perf.data');assert audit['no_truncation_gaps_collision'];save(R/'aux_audit.json',audit)
 elf=lief.parse(str(BASE));text=elf.get_section('.text');lo=text.virtual_address;hi=lo+text.size;slide=None
 for line in (T/'maps.txt').read_text().splitlines():
  x=line.split(maxsplit=5)
  if len(x)==6 and x[5]==str(BASE) and 'x' in x[1]:
   ml,mh=[int(z,16) for z in x[0].split('-')];off=int(x[2],16)
   for seg in elf.segments:
    if seg.type==lief.ELF.Segment.TYPE.LOAD and seg.file_offset//4096*4096<=off<seg.file_offset+seg.physical_size:slide=ml-(seg.virtual_address+off-seg.file_offset)
 assert slide is not None
 cmd=['objdump','-d','-j','.text','--insn-width=16',str(BASE)]
 raw=subprocess.check_output(cmd,text=True);ins=[];eligible=collections.Counter()
 safe=re.compile(r'^(?:mov(?:abs|s[bwlq]|z[bwlq])?[bwlq]?|lea[bwlq]?|cmp[bwlq]?|test[bwlq]?|and[bwlq]?|or[bwlq]?|xor[bwlq]?|add[bwlq]?|sub[bwlq]?|imul[bwlq]?|sh[lr][bwlq]?|sa[lr][bwlq]?)$')
 for line in raw.splitlines():
  parts=line.split('\t')
  if len(parts)<3:continue
  try:va=int(parts[0].strip().rstrip(':'),16);code=bytes.fromhex(parts[1])
  except ValueError:continue
  if not code or not lo<=va<hi:continue
  asm=parts[2].strip();kind='none'
  if is_padding_nop(code):kind='nop'
  elif len(code)>=5 and safe.fullmatch(asm.split()[0]) and not any(s in asm for s in ['%rip','%rsp','%rbp','%fs','%gs']):kind='detour'
  ins.append(dict(id=len(ins)+1,va=va,offset=text.offset+va-lo,bytes=code.hex(),asm=asm,kind=kind));eligible[kind]+=1
 save(R/'instructions.json',ins);save(R/'image.json',dict(base=str(BASE),sha256=meta['sha256'],text_va=lo,text_size=text.size,text_offset=text.offset,slide=slide,instructions=len(ins),eligible=dict(eligible)))
 cmd=['perf','script','-i',str(T/'perf.data'),'--no-itrace','--ns','-F','time,event,ip,period'];p=subprocess.run(cmd,text=True,capture_output=True);assert p.returncode==0
 heat=collections.Counter();times=[]
 rx=re.compile(r'\s*(\d+\.\d+):\s+(\d+)\s+cpu/.+:\s+([0-9a-fA-F]+)\s*$')
 for line in p.stdout.splitlines():
  m=rx.match(line)
  if not m:continue
  stamp=float(m[1]);pc=int(m[3],16)-slide
  if lo<=pc<hi:heat[pc&~63]+=1;times.append(stamp)
 assert len(times)>100,'PEBS parser/coverage failure'
 save(R/'pebs_heat.json',dict(samples=len(times),lines={str(k):v for k,v in heat.items()},time_first=min(times),time_last=max(times),command=cmd,stderr=p.stderr,scope='static line miss-sample weights, not individual dynamic miss labels'))
 # Four predeclared 10ms windows spread through the original baseline capture.
 # Endpoints derive only from capture time, never from performance results.
 a,b=min(times),max(times);span=b-a;assert span>.06
 windows=[(a+span*f,a+span*f+.01) for f in [.1,.3,.5,.7]]
 save(R/'windows.json',dict(windows=windows,selection='four10ms uniformly spaced windows at10/30/50/70% of original baseline PEBS time range',decode='i1i: every instruction, no quick decode; time stamps used only to select windows, distance is instruction count'))
 # Write a small format probe before running the full streaming decoder.
 cmd=['perf','script','-i',str(T/'perf.data'),'--ns','--itrace=i1ie','--time',f'{windows[0][0]:.9f},{windows[0][0]+.00001:.9f}','-F','pid,tid,event,ip']
 p=subprocess.run(cmd,text=True,capture_output=True);save(R/'format_probe.json',dict(command=cmd,exit=p.returncode,stdout_first_lines=p.stdout.splitlines()[:12],stderr=p.stderr,lines=len(p.stdout.splitlines())))
 assert p.returncode==0
 print(json.dumps(dict(eligible=dict(eligible),pebs_samples=len(times),windows=windows,probe_lines=len(p.stdout.splitlines()))),flush=True)
if __name__=='__main__':main()
