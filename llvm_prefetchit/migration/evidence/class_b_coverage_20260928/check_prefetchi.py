"""Read-only CPUID probe copied from the earlier retained ISA audit."""
from pathlib import Path
import ctypes, hashlib, json, mmap, os, platform
r=Path('/storage/prefetchit/class_b_coverage_20260928')
source=Path('/home/hnpark2/prefetchit/llvm_prefetchit/migration/evidence/class_b_e2e_20260927/prefetchi_cpuid.json')
prior=json.loads(source.read_text())
code=bytes.fromhex(prior['probe_machine_code'])
assert code.hex()=='f30f1efa53b807000000b9010000000fa28907895f04894f0889570c5bc3'
os.sched_setaffinity(0,{84})
memory=mmap.mmap(-1,len(code),prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
memory.write(code)
address=ctypes.addressof(ctypes.c_char.from_buffer(memory))
call=ctypes.CFUNCTYPE(None,ctypes.POINTER(ctypes.c_uint32))(address)
values=(ctypes.c_uint32*4)();call(values)
registers=dict(zip(('eax','ebx','ecx','edx'),map(hex,values)))
supported=bool(values[3] & (1<<14));assert supported
result=dict(leaf=7,subleaf=1,registers=registers,prefetchi_enumerated=supported,
    cpu_affinity=sorted(os.sched_getaffinity(0)),kernel=platform.release(),
    probe_machine_code=code.hex(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    previous_probe_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    specification='https://cdrdv2-public.intel.com/819680/architecture-instruction-set-extensions-programming-reference.pdf',
    semantics='Read-only CPUID only, no prefetch and no benchmark timing. Feature enumeration does not establish successful cache fills.')
(r/'prefetchi_cpuid.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(registers=registers,prefetchi_enumerated=supported)))
