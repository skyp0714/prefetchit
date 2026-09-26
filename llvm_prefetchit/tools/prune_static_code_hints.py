#!/usr/bin/env python3
"""Prune static code hints by physical-line duplication and static target reuse.

No samples, symbols chosen by hand, or application edits. Static fan-in is the
number of distinct insertion functions that hint a target function; it is only a
reuse heuristic, not a measured frequency. Equal-size NOP replacement preserves
all code/data addresses and the exact all-hints-NOP control.
"""
import argparse,bisect,hashlib,json,re,struct,subprocess
from pathlib import Path
from make_nop_control_binary import executable_sections

def sha(x):return hashlib.sha256(x).hexdigest()
def make_index(source,control):
 data=source.read_bytes();nop=control.read_bytes();sections=executable_sections(str(source));symbols={}
 for line in subprocess.check_output(['nm','-S','--defined-only',str(source)],text=True).splitlines():
  v=line.split()
  if len(v)==4 and v[2] in 'TtWw':
   addr,size=int(v[0],16),int(v[1],16)
   if addr not in symbols or size>symbols[addr][0]:symbols[addr]=[size,v[3]]
 starts=sorted(symbols);records=[];fn=0
 proc=subprocess.Popen(['objdump','-d','--insn-width=16',str(source)],stdout=subprocess.PIPE,text=True)
 for line in proc.stdout:
  m=re.match(r'^([0-9a-f]+) <',line)
  if m:fn=int(m[1],16);continue
  if 'prefetcht1' not in line:continue
  m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*prefetcht1\s',line);assert m,line
  addr=int(m[1],16);raw=bytes.fromhex(m[2]);assert len(raw)==7 and raw[:3]==bytes.fromhex('0f1815')
  off=next(o+addr-v for v,o,n in sections if v<=addr and addr+7<=v+n);assert data[off:off+7]==raw
  target=addr+7+struct.unpack_from('<i',raw,3)[0];i=bisect.bisect_right(starts,target)-1;assert i>=0
  start=starts[i];size,name=symbols[start];assert target<start+size,(hex(target),name,size)
  records.append({'off':off,'site':addr,'source':fn,'target':target,'function':start,'relative':target-start})
 assert proc.wait()==0 and records
 control_check=bytearray(data)
 for x in records:control_check[x['off']:x['off']+7]=nop[x['off']:x['off']+7]
 assert control_check==nop,'NOP differs outside owned T1 instructions'
 incoming={}
 for x in records:incoming.setdefault(x['function'],set()).add(x['source'])
 for x in records:x['fan_in']=len(incoming[x['function']])
 return {'source_sha256':sha(data),'control_sha256':sha(nop),'records':records,'functions':{str(k):v for k,v in symbols.items()}}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('control',type=Path);p.add_argument('output',type=Path);p.add_argument('--index',type=Path,required=True);p.add_argument('--policy',choices=['dedup','adjacent_pair','fanin4','fanin8','entry_rare','rare_budget8'],required=True);a=p.parse_args();assert not a.output.exists()
 if a.index.exists():ix=json.loads(a.index.read_text())
 else:ix=make_index(a.source,a.control);a.index.write_text(json.dumps(ix,separators=(',',':')))
 data=bytearray(a.source.read_bytes());nop=a.control.read_bytes();assert sha(data)==ix['source_sha256'] and sha(nop)==ix['control_sha256']
 groups={}
 for x in ix['records']:groups.setdefault(x['source'],[]).append(x)
 kept=set()
 for xs in groups.values():
  seen=set();eligible=[]
  for x in xs:
   line=x['target']//64
   if line in seen:continue
   seen.add(line)
   ok=(a.policy=='dedup' or a.policy=='adjacent_pair' and line%2==0 or a.policy=='fanin4' and x['fan_in']<=4 or a.policy=='fanin8' and x['fan_in']<=8 or a.policy=='entry_rare' and (x['relative']<64 or x['fan_in']<=2) or a.policy=='rare_budget8')
   if ok:eligible.append(x)
  if a.policy=='rare_budget8':eligible=sorted(eligible,key=lambda x:(x['relative']//64,x['fan_in'],x['site']))[:8]
  kept.update(x['off'] for x in eligible)
 for x in ix['records']:
  off=x['off']
  if off not in kept:data[off:off+7]=nop[off:off+7]
 check=bytearray(data)
 for x in ix['records']:check[x['off']:x['off']+7]=nop[x['off']:x['off']+7]
 assert check==nop
 a.output.write_bytes(data);a.output.chmod(0o755)
 meta={'policy':a.policy,'source_sha256':ix['source_sha256'],'control_sha256':ix['control_sha256'],'sha256':sha(data),'hints_before':len(ix['records']),'hints_after':len(kept),'same_layout_control_verified':True,'profile_free':True}
 a.output.with_suffix('.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta),flush=True)
if __name__=='__main__':main()
