"""Single-instruction detours plus in-place NOP hints; no instruction is split.

Detours accept only a conservative ordinary-instruction whitelist, no RIP/stack
operands or branches. The identical-layout NOP twin preserves every detour.
This preserves ordinary benchmark execution, not asynchronous unwind metadata
inside the new stubs. It is a research binary transformation, not a general ELF rewriter.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,struct
import lief
NOP=b'\x0f\x1f\x80\0\0\0\0'
def pref(at,target):return b'\x0f\x18\x15'+struct.pack('<i',target-at-7)
def jump(at,target):return b'\xe9'+struct.pack('<i',target-at-5)
def rewrite(source,out,plan):
 original=source.read_bytes();before=lief.parse(str(source));s0=before.get_section('.text');old_text_va=s0.virtual_address;old_text_size=s0.size
 sites=plan['sites'];assert sites and len({r['va'] for r in sites})==len(sites)
 total=sum(((7*len(r['targets'])+len(bytes.fromhex(r['bytes']))+5+15)//16)*16 for r in sites if r['kind']=='detour')
 if total:
  seg=lief.ELF.Segment();seg.type=lief.ELF.Segment.TYPE.LOAD;seg.flags=lief.ELF.Segment.FLAGS.R|lief.ELF.Segment.FLAGS.X;seg.alignment=4096;seg.content=list(b'\xcc'*total);before.add(seg);before.write(str(out))
 else:out.write_bytes(original)
 after=lief.parse(str(out));s1=after.get_section('.text');shift=s1.virtual_address-old_text_va
 assert s1.size==old_text_size
 segments=[s for s in after.segments if s.type==lief.ELF.Segment.TYPE.LOAD and int(s.flags)&1 and s.physical_size>=total and bytes(s.content[:16])==b'\xcc'*16] if total else []
 assert not total or len(segments)==1
 data=bytearray(out.read_bytes());twin=bytearray(data);cursor=segments[0].virtual_address if total else 0;patches=[]
 def offset(va):
  found=[s.file_offset+va-s.virtual_address for s in after.segments if s.type==lief.ELF.Segment.TYPE.LOAD and s.virtual_address<=va<s.virtual_address+s.physical_size];assert len(found)==1;return found[0]
 for r in sorted(sites,key=lambda x:x['va']):
  raw=bytes.fromhex(r['bytes']);site=r['va']+shift;off=offset(site);assert data[off:off+len(raw)]==raw
  targets=[t+shift for t in r['targets']];assert all(s1.virtual_address<=t<s1.virtual_address+s1.size for t in targets)
  if r['kind']=='nop':
   assert len(targets)==1 and len(raw)>=7
   code=b'\x66'*(len(raw)-7)+pref(site+len(raw)-7,targets[0]);data[off:off+len(raw)]=code
   # Both arms use one canonical NOP or one prefetch of the exact original length.
   twin[off:off+len(raw)]=raw;patches.append(dict(site=site,offset=off,original=raw.hex(),prefetch=code.hex(),nop=raw.hex(),targets=targets,kind='nop'))
  else:
   assert r['kind']=='detour' and len(raw)>=5 and not any(x in r['asm'] for x in ['%rip','%rsp','%rbp','%fs','%gs'])
   allowed=re.fullmatch(r'(?:mov(?:abs|s[bwlq]|z[bwlq])?[bwlq]?|lea[bwlq]?|cmp[bwlq]?|test[bwlq]?|and[bwlq]?|or[bwlq]?|xor[bwlq]?|add[bwlq]?|sub[bwlq]?|imul[bwlq]?|sh[lr][bwlq]?|sa[lr][bwlq]?)',r['asm'].split()[0]);assert allowed
   code=b''.join(pref(cursor+7*i,t) for i,t in enumerate(targets));nop=NOP*len(targets)
   code+=raw;nop+=raw;j=jump(cursor+len(code),site+len(raw));code+=j;nop+=j
   stuboff=offset(cursor);data[stuboff:stuboff+len(code)]=code;twin[stuboff:stuboff+len(nop)]=nop
   entry=jump(site,cursor)+b'\x90'*(len(raw)-5);data[off:off+len(raw)]=entry;twin[off:off+len(raw)]=entry
   patches.append(dict(site=site,offset=off,original=raw.hex(),entry=entry.hex(),stub_va=cursor,stub_offset=stuboff,prefetch=code.hex(),nop=nop.hex(),targets=targets,kind='detour'))
   cursor+=(len(code)+15)//16*16
 assert len(data)==len(twin)
 # Every arm difference must be exactly the recorded prefetch/NOP bytes.
 reconstructed=bytearray(twin)
 for p in patches:
  off=p.get('stub_offset',p['offset']);blob=bytes.fromhex(p['prefetch']);reconstructed[off:off+len(blob)]=blob
 assert reconstructed==data
 out.write_bytes(data);np=Path(str(out)+'.nop');np.write_bytes(twin);out.chmod(0o755);np.chmod(0o755)
 record=dict(source=str(source),source_sha256=hashlib.sha256(original).hexdigest(),prefetch_sha256=hashlib.sha256(data).hexdigest(),nop_sha256=hashlib.sha256(twin).hexdigest(),layout_shift=shift,stub_bytes=total,patches=patches,scope=__doc__)
 Path(str(out)+'.patches.json').write_text(json.dumps(record,indent=2));return record
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('out',type=Path);ap.add_argument('plan',type=Path);a=ap.parse_args();rewrite(a.source,a.out,json.loads(a.plan.read_text()))
