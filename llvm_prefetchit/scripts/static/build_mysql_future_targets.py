#!/usr/bin/env python3
"""Live storage-engine virtual targets from handler entry, package-pinned prototype."""
from pathlib import Path
import argparse,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from append_dispatch_hooks import build
SITES=[('ha_rnd_next',0xc0bb84,'554889e54155',0x1c8),('ha_write_row',0xc33404,'554889e54156',0x3c8),('ha_update_row',0xc9a124,'554889e54156',0x3d0),('ha_index_read_map',0xc3e1a4,'554589c24889e5',0x160)]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
 assert hashlib.sha256(a.binary.read_bytes()).hexdigest()=='b7fbad1d47baa9ed9ecaf4574d87a1f3c38ec279867502a3e5c9f9edf4ec3399','uninspected package; re-audit ABI and addresses first'
 hooks=[]
 for name,site,expected,slot in SITES:
  asm=f'mov (%rdi), %r11\nmov {slot}(%r11), %r11\n'
  if name=='ha_index_read_map':
   asm+='lea a3_default_map(%rip), %r10\ncmp %r10, %r11\njne 1f\nmov (%rdi), %r11\nmov 0x460(%r11), %r11\n1:\n'
  asm+='prefetcht1 (%r11)'
  hooks.append({'site':site,'expected':expected,'assembly':asm,'label':name})
 plan={'sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'symbols':{'a3_default_map':0xc3e810},'hooks':hooks,'mode':'early live engine targets','ABI':'entry after endbr64; nonvariadic SysV C++ methods; only dead R10/R11 and flags clobbered, args and stack preserved. index_read_map replicates compiler default-wrapper guard and resolves inner index_read slot only on that path. InnoDB OLTP setting.'}
 a.out.parent.mkdir(parents=True,exist_ok=True);a.out.with_suffix('.plan.json').write_text(json.dumps(plan,indent=2));build(a.binary,plan,a.out)
if __name__=='__main__':main()
