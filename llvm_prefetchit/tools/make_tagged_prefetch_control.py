#!/usr/bin/env python3
"""NOP only prefetch sites listed by non-allocated linker-resolved address tags."""
from pathlib import Path
import argparse,hashlib,json,re,struct,subprocess
from make_nop_control_binary import executable_sections,disassemble,selected_prefetch,MULTI_NOP

def build(source,output,symbol,section='.a3_prologue_sites'):
 data=bytearray(source.read_bytes());original=bytes(data)
 line=next(x for x in subprocess.check_output(['readelf','-SW',str(source)],text=True).splitlines() if re.search(r'\]\s+'+re.escape(section)+r'\s',x))
 m=re.search(r'PROGBITS\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)',line);assert m
 va,offset,size=(int(x,16) for x in m.groups());assert va==0 and size>0 and size%8==0
 tags=list(struct.unpack_from('<'+'Q'*(size//8),data,offset));assert len(tags)==len(set(tags))
 decoded={}
 for line in disassemble(str(source),symbol).splitlines():
  if not selected_prefetch(line,['prefetcht1']):continue
  parts=line.split('\t');decoded[int(parts[0].strip().rstrip(':'),16)]=bytes.fromhex(parts[1])
 sections=executable_sections(str(source));patches=[]
 for addr in tags:
  raw=decoded[addr];assert len(raw) in MULTI_NOP
  off=next(o+addr-v for v,o,n in sections if v<=addr and addr+len(raw)<=v+n);assert data[off:off+len(raw)]==raw
  data[off:off+len(raw)]=MULTI_NOP[len(raw)];patches.append({'address':addr,'offset':off,'before':raw.hex(),'after':MULTI_NOP[len(raw)].hex()})
 reverse=bytearray(data)
 for x in patches:raw=bytes.fromhex(x['before']);reverse[x['offset']:x['offset']+len(raw)]=raw
 assert reverse==original
 output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(data);output.chmod(0o755)
 meta={'source_sha256':hashlib.sha256(original).hexdigest(),'sha256':hashlib.sha256(data).hexdigest(),'removed_tagged_hints':len(tags),'remaining_scope_T1':len(decoded)-len(tags),'section':section,'same_layout':True,'patches':patches};output.with_suffix('.control.json').write_text(json.dumps(meta,indent=2));return meta

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);p.add_argument('--symbol',required=True);a=p.parse_args();assert not a.output.exists();print(json.dumps(build(a.source,a.output,a.symbol)),flush=True)
if __name__=='__main__':main()
