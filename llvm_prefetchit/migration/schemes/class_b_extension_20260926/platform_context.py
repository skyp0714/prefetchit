"""Retry only an asynchronous HWP restoration mismatch, preserving the first read."""
from common import *
import contextlib,sys
sys.path.insert(0,str(REPO/'llvm_prefetchit/scripts/static'))
from measure_class_a import platform as original

def recover(cpu,out,error):
 if str(error)!='platform restore mismatch':raise error
 before=json.loads((out/'platform_before.json').read_text());after=json.loads((out/'platform_restored.json').read_text())
 assert before==after,'Do not mask sysfs restoration failures'
 expected=json.loads((out/'hwp_before.json').read_text());initial=json.loads((out/'hwp_restored.json').read_text())
 assert expected!=initial,'Only HWP readback mismatches are retried'
 save(out/'hwp_first_restore_readback.json',initial);reads=[]
 with open(f'/dev/cpu/{cpu}/msr','r+b',buffering=0) as f:
  for attempt in range(5):
   time.sleep(.05);os.pwrite(f.fileno(),bytes.fromhex(expected['msr_0x774']),0x774);time.sleep(.05)
   reads.append(os.pread(f.fileno(),8,0x774).hex())
   if reads[-1]==expected['msr_0x774']:break
  time.sleep(.1);reads.append(os.pread(f.fileno(),8,0x774).hex())
 save(out/'hwp_restore_retry.json',dict(expected=expected,readbacks=reads,restored=reads[-1]==expected['msr_0x774']))
 assert reads[-1]==expected['msr_0x774'],'HWP restoration still differs after bounded retries'
 save(out/'hwp_restored.json',expected)

@contextlib.contextmanager
def platform(cpu,out):
 cm=original(cpu,out);cm.__enter__()
 try:yield
 except BaseException:
  info=sys.exc_info()
  try:suppressed=cm.__exit__(*info)
  except RuntimeError as error:recover(cpu,out,error);suppressed=False
  if not suppressed:raise
 else:
  try:cm.__exit__(None,None,None)
  except RuntimeError as error:recover(cpu,out,error)
