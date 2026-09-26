#!/usr/bin/env python3
"""Fingerprint-checked x86-64 ELF research hooks; original load addresses stay fixed.

The caller supplies ABI-audited assembly for each site. This is deliberately not a
universal rewriter: stolen instructions must be straight-line, position-independent.
New PHDRs live in an appended RX mapping; optional zero-filled state has its own RW
mapping. Exact NOP twins retain all address computation, state and control flow.
"""
import argparse,hashlib,json,re,struct,subprocess,tempfile
from pathlib import Path
PH=struct.Struct('<IIQQQQQQ')
NOP={3:bytes.fromhex('0f1f00'),4:bytes.fromhex('0f1f4000'),5:bytes.fromhex('0f1f440000'),6:bytes.fromhex('660f1f440000'),7:bytes.fromhex('0f1f8000000000'),8:bytes.fromhex('0f1f840000000000'),9:bytes.fromhex('660f1f840000000000')}
def align(n,a=4096):return (n+a-1)//a*a
def sha(b):return hashlib.sha256(b).hexdigest()
def instructions(path,start=None,end=None):
 cmd=['objdump','-d','--insn-width=16']
 if start is not None:cmd += [f'--start-address={start}',f'--stop-address={end}']
 out=subprocess.check_output(cmd+[str(path)],text=True)
 return [(int(m[1],16),bytes.fromhex(m[2]),m[3].strip()) for line in out.splitlines() if (m:=re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)$',line))]
def build(binary,plan,output):
 original=Path(binary).read_bytes();b=bytearray(original)
 assert b[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',b,18)[0]==62,'requires little-endian ELF64 x86-64'
 assert sha(b)==plan['sha256'],'input fingerprint mismatch'
 phoff=struct.unpack_from('<Q',b,32)[0];ents,n=struct.unpack_from('<HH',b,54)
 assert ents==56 and n<128
 ph=[list(PH.unpack_from(b,phoff+i*56)) for i in range(n)]
 loads=[p for p in ph if p[0]==1]
 def fileoff(va,length):
  matches=[p for p in loads if p[3]<=va and va+length<=p[3]+p[5]]
  assert len(matches)==1,'hook outside unique file-backed LOAD'
  p=matches[0];assert p[1]&1,'hook not executable'
  return p[2]+va-p[3]
 data_size=align(plan.get('data_bytes',0))
 new_count=n+1+bool(data_size)+(not any(p[0]==6 for p in ph))
 table_size=new_count*56
 rxoff=align(len(b));rxva=align(max(p[3]+p[6] for p in loads));codeva=rxva+align(table_size,16)
 # Reserve a fixed 64 KiB RX range so assembly can reference final RW addresses.
 rwva=rxva+65536
 bodies=['.text']
 hooks=[]
 for i,h in enumerate(plan['hooks']):
  va=int(h['site'],0) if isinstance(h['site'],str) else h['site'];raw=bytes.fromhex(h['expected'])
  assert len(raw)>=5 and b[fileoff(va,len(raw)):fileoff(va,len(raw))+len(raw)]==raw,'site fingerprint mismatch'
  ins=instructions(binary,va,va+len(raw));assert b''.join(x[1] for x in ins)==raw,'not whole instruction boundaries'
  assert all(not re.search(r'\b(?:j\w*|call\w*|ret\w*|loop\w*)\b|%rip',x[2]) for x in ins),'cannot relocate PC-relative/control instructions'
  assert not any('endbr' in x[2] for x in ins),'preserve CET landing pad'
  name=f'a3_hook_{i}'
  bodies += [f'.balign 16\n.global {name}\n{name}:',h['assembly'],'.byte '+','.join(str(x) for x in raw),f'jmp 0x{va+len(raw):x}']
  hooks.append({'site':va,'size':len(raw),'label':h.get('label',name),'symbol':name,'original':raw.hex()})
 with tempfile.TemporaryDirectory(prefix='a3-elf-') as td:
  td=Path(td);src=td/'hooks.s';obj=td/'hooks.o';elf=td/'hooks.elf';rawbin=td/'hooks.bin'
  src.write_text('.extern a3_data\n'+'\n'.join(bodies)+'\n.section .note.GNU-stack,"",@progbits\n')
  subprocess.run(['clang-19','-c',str(src),'-o',str(obj)],check=True)
  definitions={'a3_data':rwva,**plan.get('symbols',{})}
  subprocess.run(['ld','--build-id=none',f'-Ttext=0x{codeva:x}',*[f'--defsym={k}=0x{v:x}' for k,v in definitions.items()],'-e','a3_hook_0',str(obj),'-o',str(elf)],check=True)
  rel=subprocess.check_output(['readelf','-r',str(elf)],text=True);assert 'There are no relocations' in rel
  subprocess.run(['objcopy','-O','binary','--only-section=.text',str(elf),str(rawbin)],check=True)
  code=rawbin.read_bytes();assert codeva-rxva+len(code)<=65536,'stub RX reservation exceeded'
  syms={s[2]:int(s[0],16) for line in subprocess.check_output(['nm',str(elf)],text=True).splitlines() if len(s:=line.split())==3}
  dis=instructions(elf);hints=[(va,raw,asm) for va,raw,asm in dis if re.search(r'\bprefetcht1\b',asm)]
  assert hints,'no T1 hints in hook assembly'
  disassembly=subprocess.check_output(['objdump','-d',str(elf)],text=True)
 rxsize=codeva-rxva+len(code)
 for p in ph:
  if p[0]==6:p[:]=[6,4,rxoff,rxva,rxva,table_size,table_size,8]
 if not any(p[0]==6 for p in ph):ph.insert(0,[6,4,rxoff,rxva,rxva,table_size,table_size,8])
 ph.append([1,5,rxoff,rxva,rxva,rxsize,rxsize,4096])
 if data_size:
  rwoff=align(rxoff+rxsize);ph.append([1,6,rwoff,rwva,rwva,4096,data_size,4096])
 b.extend(b'\0'*(rxoff+rxsize-len(b)))
 for i,p in enumerate(ph):PH.pack_into(b,rxoff+i*56,*p)
 struct.pack_into('<Q',b,32,rxoff);struct.pack_into('<H',b,56,len(ph))
 b[rxoff+codeva-rxva:rxoff+rxsize]=code
 if data_size:b.extend(b'\0'*(rwoff+4096-len(b)))
 for h in hooks:
  dest=syms[h['symbol']];off=fileoff(h['site'],h['size']);rel=dest-h['site']-5
  assert -(2**31)<=rel<2**31
  patch=b'\xe9'+struct.pack('<i',rel)+b'\x90'*(h['size']-5)
  b[off:off+h['size']]=patch;h.update(offset=off,stub=dest,patch=patch.hex())
 output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b);output.chmod(0o755)
 nop=bytearray(b);patches=[]
 for va,raw,asm in hints:
  off=rxoff+va-rxva;assert nop[off:off+len(raw)]==raw
  nop[off:off+len(raw)]=NOP[len(raw)];patches.append({'va':va,'offset':off,'original':raw.hex(),'nop':NOP[len(raw)].hex(),'asm':asm})
 twin=Path(str(output)+'.nop');twin.write_bytes(nop);twin.chmod(0o755)
 manifest={'input':str(binary),'input_sha256':sha(original),'output_sha256':sha(b),'nop_sha256':sha(nop),'hooks':hooks,'hint_patches':patches,'rx_va':rxva,'rw_va':rwva if data_size else None,'data_bytes':data_size,'phoff':rxoff,'phnum':len(ph),'original_build_id_retained':True,'perf_identity':'use recorded SHA and maps; original build ID does not distinguish variants','plan':plan}
 Path(str(output)+'.json').write_text(json.dumps(manifest,indent=2));Path(str(output)+'.asm').write_text(disassembly)
 return manifest
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('plan',type=Path);p.add_argument('output',type=Path);a=p.parse_args();build(a.binary,json.loads(a.plan.read_text()),a.output)
