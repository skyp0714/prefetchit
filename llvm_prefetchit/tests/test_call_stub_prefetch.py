"""Native call ABI, original return addresses, and merged unwind-table checks."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import pytest

PATH = Path(__file__).resolve().parents[1]/'tools/call_stub_prefetch.py'
spec = importlib.util.spec_from_file_location('call_stubs', PATH)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.mark.parametrize('pie', [False, True])
@pytest.mark.parametrize('hybrid', [False, True])
def test_native_call_arguments_flags_return_and_unwind(tmp_path, pie, hybrid):
    source = tmp_path/'main.cc'; assembly = tmp_path/'calls.s'; base = tmp_path/'base'
    source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
extern "C" long invoke(long,long,long,long,long,long);
extern "C" long invoke_throw(long);
extern "C" char call_probe[], call_throw[], call_throw_again[];
struct bases { void *tbase, *dbase, *func; };
extern "C" void *_Unwind_Find_FDE(void *, struct bases *);
extern "C" __attribute__((noinline)) long thrower(long x) { if (x<0) throw x; return x+10; }
void clock_setup(const char *);
bool clock_check(const char *);
int main(int argc,char **argv) {
  const char *mode=argc>1?argv[1]:"zero";clock_setup(mode);
  if (invoke(1,2,3,4,5,6)!=22 || invoke_throw(9)!=29) return 1;
  bool caught=false; try { invoke_throw(-7); } catch (long x) { caught=x==-7; }
  if (!caught) return 2;
  for (char *site : {call_probe, call_throw, call_throw_again}) {
    int32_t displacement; memcpy(&displacement,site+1,4);
    void *destination=site+5+displacement;
    struct bases b={}; if (!_Unwind_Find_FDE(destination,&b)) return 3;
  }
  if(!clock_check(mode))return 4;
  puts("abi-and-unwind-ok");
}
'''.replace('#include <stdint.h>', '#include <stdint.h>\n#include <initializer_list>'))
    # Fake scheduler slots exercise both gated paths deterministically, without
    # loading a kernel module or interpreting attempted hints as cache fills.
    with source.open('a') as stream:
        stream.write(r'''
#include <elf.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/auxv.h>
#include <unistd.h>
#include <x86intrin.h>
static uint64_t *clock_words,*state_words;
static void exact(int f,void *p,size_t n,off_t o){if(pread(f,p,n,o)!=(ssize_t)n)abort();}
void clock_setup(const char *mode){
  int f=open("/proc/self/exe",O_RDONLY);Elf64_Ehdr e;exact(f,&e,sizeof(e),0);
  Elf64_Phdr ph[128];Elf64_Shdr sh[256];char names[65536];uintptr_t bias=0;
  if(e.e_phnum>128||e.e_shnum>256)abort();
  exact(f,ph,e.e_phnum*sizeof(*ph),e.e_phoff);exact(f,sh,e.e_shnum*sizeof(*sh),e.e_shoff);
  if(sh[e.e_shstrndx].sh_size>sizeof(names))abort();
  exact(f,names,sh[e.e_shstrndx].sh_size,sh[e.e_shstrndx].sh_offset);close(f);
  for(int i=0;i<e.e_phnum;i++)if(ph[i].p_type==PT_PHDR)bias=getauxval(AT_PHDR)-ph[i].p_vaddr;
  for(int i=0;i<e.e_shnum;i++){
    if(!strcmp(names+sh[i].sh_name,".prefetch_clock"))clock_words=(uint64_t *)(bias+sh[i].sh_addr);
    if(!strcmp(names+sh[i].sh_name,".prefetch_state"))state_words=(uint64_t *)(bias+sh[i].sh_addr);
  }
  if(!clock_words)return;
  unsigned aux;uint64_t now=__rdtscp(&aux);
  for(int cpu=0;cpu<4096;cpu++){
    clock_words[8*cpu]=!strcmp(mode,"early")?UINT64_MAX:1;
    clock_words[8*cpu+3]=!strcmp(mode,"zero")?0:now-10000;
    clock_words[8*cpu+7]=2;
  }
}
bool clock_check(const char *mode){
  if(!state_words)return true;
  uint64_t checks=0,bursts=0,late=0,race=0;
  for(int cpu=0;cpu<4096;cpu++){
    checks+=state_words[8*cpu+1];bursts+=state_words[8*cpu+2];
    late+=state_words[8*cpu+3];race+=state_words[8*cpu+4];
  }
  if(checks!=4)return false;
  if(!strcmp(mode,"early"))return bursts>=1 && bursts<=4 && late==0 && race==0;
  if(!strcmp(mode,"late"))return bursts==0 && late>=1 && late<=4 && race==0;
  return bursts==0 && late==0 && race==0;
}
''')
    assembly.write_text(r'''
.text
.globl invoke
.type invoke,@function
invoke:
.cfi_startproc
sub $8,%rsp
.cfi_adjust_cfa_offset 8
stc
.globl call_probe
call_probe:
call probe
.globl return_probe
return_probe:
add $8,%rsp
.cfi_adjust_cfa_offset -8
ret
.cfi_endproc
.size invoke,.-invoke
.globl probe
.type probe,@function
probe:
.cfi_startproc
mov %rdi,%rax
adc %rsi,%rax
add %rdx,%rax
add %rcx,%rax
add %r8,%rax
add %r9,%rax
lea return_probe(%rip),%r10
cmp %r10,(%rsp)
je 1f
mov $-1,%rax
1: ret
.cfi_endproc
.size probe,.-probe
.globl invoke_throw
.type invoke_throw,@function
invoke_throw:
.cfi_startproc
sub $8,%rsp
.cfi_adjust_cfa_offset 8
.globl call_throw
call_throw:
call thrower
mov %rax,%rdi
.globl call_throw_again
call_throw_again:
call thrower
add $8,%rsp
.cfi_adjust_cfa_offset -8
ret
.cfi_endproc
.size invoke_throw,.-invoke_throw
.section .note.GNU-stack,"",@progbits
''')
    subprocess.run(['clang++-19', '-O2', '-fasynchronous-unwind-tables', '-pie' if pie else '-no-pie',
                    str(source), str(assembly), '-o', str(base)], check=True)
    symbols = {s[2]:int(s[0],16) for line in subprocess.check_output(['nm', str(base)],text=True).splitlines() if len(s:=line.split())==3}
    raw = base.read_bytes(); elf = m.Elf(raw)
    calls = []
    for site, callee in [('call_probe','probe'), ('call_throw','thrower'), ('call_throw_again','thrower')]:
        va = symbols[site]; off = elf.offset(va,5,True)
        calls.append(dict(site=va, callee=symbols[callee], expected=raw[off:off+5].hex(), targets=[symbols['probe'], symbols['thrower']]))
    plan = dict(sha256=m.sha(raw), calls=calls)
    if hybrid:
        for row in calls:row['burst_targets']=row['targets']
    output = tmp_path/'with_hints'; record = m.build(base,plan,output,hybrid={'diagnostic':True} if hybrid else None)
    for path in (base, output, Path(str(output)+'.nop')):
        for mode in (['early','late','zero'] if hybrid else ['zero']):
            assert subprocess.check_output([str(path),mode],text=True)=='abi-and-unwind-ok\n'
    patched = output.read_bytes(); nop = Path(str(output)+'.nop').read_bytes()
    allowed = {i for h in record['hints'] for i in range(h['offset'],h['offset']+7)}
    assert len(patched)==len(nop)
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(patched,nop)))
    old = m.Elf(raw); new = m.Elf(patched)
    for name in ['.text','.rodata','.data','.eh_frame']:
        old_section, old_bytes=old.section(name); new_section,new_bytes=new.section(name)
        assert old_section[3:6]==new_section[3:6]
        if name!='.text': assert old_bytes==new_bytes
    old_header=next(p for p in old.ph if p[0]==m.EH_FRAME)
    new_header=next(p for p in new.ph if p[0]==m.EH_FRAME)
    _,original_entries=m.decode_eh_header(raw[old_header[2]:old_header[2]+old_header[5]],old_header[3])
    _,new_entries=m.decode_eh_header(patched[new_header[2]:new_header[2]+new_header[5]],new_header[3])
    assert set(original_entries)<=set(new_entries) and len(new_entries)==len(original_entries)+2
    assert record['original_return_addresses_preserved'] and record['added_fdes']==2
    assert record['unique_stubs']==2 and record['call_sites']==3
    assert record['patches'][1]['stub']==record['patches'][2]['stub']
    with pytest.raises(AssertionError,match='fingerprint'):
        m.build(base,dict(plan,sha256='0'*64),tmp_path/'bad')
    bad=dict(calls[0],expected='90'*5)
    with pytest.raises(AssertionError,match='fingerprinted'):
        m.build(base,dict(plan,calls=[bad]),tmp_path/'bad_call')


def test_unwind_header_rejects_unsupported_and_unsorted():
    with pytest.raises(AssertionError,match='encoding'):
        m.decode_eh_header(bytes(12),0)
    raw=bytes.fromhex('011b033b')+struct.pack('<iIiiii',0,2,100,120,50,80)
    with pytest.raises(AssertionError,match='Unsorted'):
        m.decode_eh_header(raw,0)
