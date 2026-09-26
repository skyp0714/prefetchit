#!/usr/bin/env python3
"""Private Thrift future-handler prototypes; immutable live iface, x86-64 ABI.

The resolved handler is hinted before argument decoding (early) or immediately
before the actual invocation (late). No future method is executed. Diagnostic
builds expose sampled lead histograms and are excluded from speedup comparisons.
"""
import argparse,hashlib,json,re,shutil,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HELPER=r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <x86intrin.h>
template<class Object, class Method>
static inline __attribute__((always_inline)) uintptr_t a3_target(Object* object, Method method) {
  struct Member { ptrdiff_t ptr, adjust; } member;
  static_assert(sizeof(method)==sizeof(member), "x86-64 Itanium member ABI required");
  __builtin_memcpy(&member, &method, sizeof member);
  uintptr_t code=static_cast<uintptr_t>(member.ptr);
  if (code & 1) {
    const char* table;
    __builtin_memcpy(&table, reinterpret_cast<const char*>(object)+member.adjust, sizeof table);
    __builtin_memcpy(&code, table+member.ptr-1, sizeof code);
  }
  return code;
}
static inline __attribute__((always_inline)) void a3_hint(uintptr_t code) {
  asm volatile("prefetcht1 (%0)" : : "r"(code));
}
'''
DIAGNOSTIC=r'''
struct A3Lead { uint64_t count, sum, bins[12]; };
extern "C" { __attribute__((visibility("default"))) A3Lead a3_lead_histogram[@COUNT@] = {}; }
static thread_local uint64_t a3_sampling_counters[@COUNT@];
static inline void a3_record(unsigned site, uint64_t ticks) {
  unsigned bin=0; uint64_t limit=64;
  while(bin<11 && ticks>=limit) { ++bin; limit*=2; }
  __atomic_fetch_add(&a3_lead_histogram[site].count, 1, __ATOMIC_RELAXED);
  __atomic_fetch_add(&a3_lead_histogram[site].sum, ticks, __ATOMIC_RELAXED);
  __atomic_fetch_add(&a3_lead_histogram[site].bins[bin], 1, __ATOMIC_RELAXED);
}
'''

def transform(text, service, mode):
    pattern=re.compile(r'void '+re.escape(service)+r'Processor::process_(\w+)\([^\n]*\)\n\{')
    methods=[m[1] for m in pattern.finditer(text)]
    assert methods
    if mode=='base':return text,methods
    helper=HELPER+(DIAGNOSTIC.replace('@COUNT@',str(len(methods))) if mode=='diagnostic' else '')
    text=helper+'\n'+text
    # Reverse positions keep earlier match offsets independent of edits.
    matches=list(pattern.finditer(text))
    for index,m in reversed(list(enumerate(matches))):
        end=matches[index+1].start() if index+1<len(matches) else len(text)
        body=text[m.end():end]
        call=re.search(r'(?m)^    iface_->'+re.escape(m[1])+r'\(',body)
        assert call,(service,m[1])
        hint=f'  a3_hint(a3_target(iface_.get(), &{service}If::{m[1]}));\n'
        if mode=='late':body=body[:call.start()]+hint+body[call.start():]
        elif mode=='early':body='\n'+hint+body
        elif mode=='diagnostic':
            marker=f'''  if (a3_sample) {{
    unsigned aux; uint64_t elapsed=__rdtscp(&aux)-a3_start;
    a3_record({index},elapsed);
  }}
'''
            body=body[:call.start()]+marker+body[call.start():]
            body=f'''\n  bool a3_sample=(++a3_sampling_counters[{index}] & 63)==0;
  uint64_t a3_start=0;
  if (a3_sample) {{ _mm_lfence(); a3_start=__rdtsc(); }}
'''+hint+body
        else:raise ValueError(mode)
        text=text[:m.end()]+body+text[end:]
    return text,methods

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--service',choices=['compose','movie'],required=True)
    p.add_argument('--mode',choices=['base','late','early','diagnostic'],required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=ROOT/'llvm_prefetchit/results/class_a2_20260923/media_rpc_production'
    private=out/'mediaMicroservices'
    if not private.exists():
        shutil.copytree(original/'mediaMicroservices',private,ignore=shutil.ignore_patterns('build'))
    for filename in ['ComposeReviewService.cpp','MovieIdService.cpp']:
        shutil.copy2(original/'mediaMicroservices/gen-cpp'/filename,private/'gen-cpp'/filename)
    service={'compose':'ComposeReviewService','movie':'MovieIdService'}[a.service]
    source=original/'mediaMicroservices/gen-cpp'/(service+'.cpp')
    code,methods=transform(source.read_text(),service,a.mode)
    target=private/'gen-cpp'/(service+'.cpp');target.write_text(code)
    d=out/a.service/a.mode;d.mkdir(parents=True,exist_ok=False)
    cmd=['docker','run','--rm','--cpuset-cpus','0-31','-v',str(private)+':/src',
         '-v',str(ROOT/'llvm_prefetchit/build')+':/pass:ro',
         '-v',str(ROOT/'flat_codegen/dsb_build')+':/dsb:ro',
         '-v',str(out)+':'+str(out),'-v',str(original/'build_service_once.sh')+':/a3_build.sh:ro',
         '-e','MAKE_TARGET='+service,'-e','BIN_GLOB='+service,'-e','FATSTATIC=1',
         '--entrypoint','bash','dsb-deps-jammy','/a3_build.sh',str(d),
         '-O3','-g','-Wno-enum-constexpr-conversion','-Wno-error']
    with (d/'build.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=d/service
    meta={'mode':a.mode,'service':service,'methods':methods,'source_sha256':hashlib.sha256(code.encode()).hexdigest(),
          'source_original_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'command':cmd,
          'assumptions':'immutable shared iface during RPC; live object; x86-64 Itanium member ABI; diagnostic timings are TSC ticks'}
    (d/'manifest.json').write_text(json.dumps(meta,indent=2))
    if a.mode in ['early','late']:
        subprocess.run(['python3',str(ROOT/'llvm_prefetchit/tools/make_nop_control_binary.py'),
                        '--input',str(binary),'--output',str(binary)+'.nop','--mnemonics','prefetcht1'],check=True)
    print(json.dumps({'service':service,'mode':a.mode,'methods':methods,'sha256':meta['binary_sha256']}),flush=True)

if __name__=='__main__':main()
