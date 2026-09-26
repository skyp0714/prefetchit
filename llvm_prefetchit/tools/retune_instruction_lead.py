#!/usr/bin/env python3
"""Static instruction-count lead in existing audited sequential-prefetch slots.

The instruction count follows linear machine-code order, not a prediction of the
executed branch path or cycle latency. Original allocated addresses never move.
The supplied NOP binary must differ only at decoded prefetch instructions. Cached
indices are pinned to both input SHA256s. Non-sequential hints remain unchanged.
"""
from pathlib import Path
import argparse,bisect,hashlib,json,re,struct,subprocess
from make_nop_control_binary import executable_sections

def digest(data):return hashlib.sha256(data).hexdigest()
def index(source,control):
 data=source.read_bytes();nop=control.read_bytes();assert len(data)==len(nop)
 sections=executable_sections(str(source));groups=[];fn=[];hints=[];seq=[];name=''
 def flush():
  if not fn:return
  real=[addr for addr,raw,op in fn if not op.startswith('prefetch')]
  end=fn[-1][0]+len(fn[-1][1]);first=fn[0][0]
  for addr,raw,op in fn:
   if not op.startswith('prefetch'):continue
   matches=[off+addr-va for va,off,size in sections if va<=addr and addr+len(raw)<=va+size]
   assert len(matches)==1
   off=matches[0];assert data[off:off+len(raw)]==raw
   if data[off:off+len(raw)]==nop[off:off+len(raw)]:continue
   hints.append([off,len(raw)])
   if len(raw)==7 and raw[:3]==bytes.fromhex('0f1815') and struct.unpack_from('<i',raw,3)[0]==4096:
    seq.append([off,addr,bisect.bisect_right(real,addr),len(groups)])
  groups.append({'name':name,'start':first,'end':end,'instructions':real})
 proc=subprocess.Popen(['objdump','-d','--insn-width=16',str(source)],stdout=subprocess.PIPE,text=True)
 for line in proc.stdout:
  m=re.match(r'^([0-9a-f]+) <(.+)>:',line)
  if m:flush();fn=[];name=m[2];continue
  m=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$',line)
  if m:fn.append((int(m[1],16),bytes.fromhex(m[2]),m[3].strip()))
 flush();assert proc.wait()==0
 reconstructed=bytearray(data)
 for off,n in hints:reconstructed[off:off+n]=nop[off:off+n]
 assert reconstructed==nop,'control differs outside audited hints'
 assert seq,'no owned 4096-byte sequential hints'
 return {'source_sha256':digest(data),'control_sha256':digest(nop),'groups':groups,'seq':seq,'owned_hints':hints}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('control',type=Path);p.add_argument('out',type=Path);p.add_argument('--index',type=Path,required=True);p.add_argument('--lead',type=int,required=True);p.add_argument('--spacing',type=int,default=0);p.add_argument('--deduplicate',action='store_true');p.add_argument('--global-stream',action='store_true',help='linear code order may cross function boundaries');p.add_argument('--tail',choices=['drop','keep'],default='drop');p.add_argument('--bytes',action='store_true',help='lead is bytes; otherwise linear machine instructions');a=p.parse_args()
 assert a.lead>0 and a.spacing>=0 and not a.out.exists()
 if a.index.exists():ix=json.loads(a.index.read_text())
 else:ix=index(a.source,a.control);a.index.write_text(json.dumps(ix,separators=(',',':')))
 data=bytearray(a.source.read_bytes());nop=a.control.read_bytes();assert digest(data)==ix['source_sha256'] and digest(nop)==ix['control_sha256']
 global_instructions=sorted(addr for group in ix['groups'] for addr in group['instructions']) if a.global_stream else []
 seen={};last={};kept=0;tail=0;pruned=0;targets=[]
 for off,addr,pos,g in ix['seq']:
  group=ix['groups'][g];instructions=group['instructions']
  if a.global_stream:
   instructions=global_instructions;pos=bisect.bisect_right(instructions,addr);group={'start':instructions[0],'end':instructions[-1]+1}
  target=addr+7+a.lead if a.bytes else (instructions[pos+a.lead-1] if pos+a.lead<=len(instructions) else group['end'])
  within=target<group['end']
  target &= ~63
  valid=within and group['start']<=target<group['end'] and target>addr
  if not valid:
   tail+=1
   if a.tail=='keep':
    kept+=1;targets.append(addr+7+4096);continue
  elif (a.deduplicate and target in seen.get(g,set())) or addr-last.get(g,-10**12)<a.spacing:valid=False;pruned+=1
  if valid:
   struct.pack_into('<i',data,off+3,target-(addr+7));seen.setdefault(g,set()).add(target);last[g]=addr;kept+=1;targets.append(target)
  else:data[off:off+7]=nop[off:off+7]
 # Verify the resulting all-owned-hints NOP is exactly the supplied control.
 twin=bytearray(data)
 for off,n in ix['owned_hints']:twin[off:off+n]=nop[off:off+n]
 assert twin==nop
 a.out.write_bytes(data);a.out.chmod(0o755)
 meta={'source':str(a.source),'control':str(a.control),'source_sha256':ix['source_sha256'],'control_sha256':ix['control_sha256'],'sha256':digest(data),'lead':a.lead,'unit':'bytes' if a.bytes else 'linear machine instructions','spacing':a.spacing,'deduplicate':a.deduplicate,'seq_before':len(ix['seq']),'seq_after':kept,'tail_pruned':tail,'budget_pruned':pruned,'same_layout_nop_verified':True,'function_bounded_aligned_targets':not a.global_stream and a.tail=='drop','global_stream':a.global_stream,'tail_policy':a.tail,'tool_sha256':digest(Path(__file__).read_bytes()),'unique_target_lines':len(set(targets))}
 a.out.with_suffix('.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta),flush=True)
if __name__=='__main__':main()
