from pathlib import Path
import sys,json,gzip,re
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b,fullset as h
r=Path('/storage/prefetchit/class_b_coverage_20260928')
assert (r/'confirmation/complete.json').exists(),'No profiling/decoding during independent timing'
spec=json.load(open(r/'confirmation_spec.json'))
setting=dict(out=str(r/'selected_diagnostic'),overrides=spec['arms']['selected_it0']['overrides'],concurrency=4,seed=65001,rounds=0,sample=True,sample_s=12,sample_events={'l2':'cpu/event=0xc6,umask=0x3,config1=0x13,period=257,name=fe_l2/upp'})
b.save(r/'selected_diagnostic_spec.json',setting)
h.platform(r/'selected_diagnostic',['python3',repo/'llvm_prefetchit/scripts/class_b/dense_causes.py','trial',r/'selected_diagnostic_spec.json'])
from dense_cause_analysis import analyze_service
from dense_cause_report import sampling_summary
from e2e_lbr import remove_generated
from lean_profile import symbol_ranges
from make_nop_control_binary import executable_sections
from lbr_padding_prefetch import HEADER,mapping_bias
from collections import Counter
out={}
for key in b.SERVICES:
 folder=r/'selected_diagnostic'/key;out[key]=analyze_service(folder,kinds=('l2',))
 binary=Path(setting['overrides'][key]);ranges,cmd=symbol_ranges(binary);main=out[key]['main_dso'];bias=mapping_bias((folder/'maps.txt').read_text(),re.compile('^'+re.escape(main)+'$'),executable_sections(str(binary)))
 counts=Counter()
 for line in (folder/'l2/samples.txt').open():
  m=HEADER.match(line)
  if m and m[3][1:-1] in (main,Path(main).name):counts[int(m[2],16)-bias]+=1
 with gzip.open(folder/'all_main_ips.json.gz','wt') as f:json.dump(dict(binary_sha256=b.sha(binary),symbol_ranges=ranges,counts=[dict(va=hex(a),samples=n) for a,n in counts.most_common()],command=cmd),f,separators=(',',':'))
with gzip.open(r/'selected_diagnostic_analysis.json.gz','wt') as f:json.dump(out,f,separators=(',',':'))
b.save(r/'selected_diagnostic_summary.json',sampling_summary({'selected':out}))
paths=[r/'selected_diagnostic'/key/'l2/samples.txt' for key in b.SERVICES]
paths += [p for key in b.SERVICES for p in (r/'selected_diagnostic'/key/'dsos').iterdir() if p.is_file()]
remove_generated(paths,r/'selected_diagnostic_cleanup.json','Complete main-IP/symbol aggregates and miss/LBR path associations retained; decoded text and copied DSOs no longer needed. No inference of hardware fill success or exact issue-to-fetch time.')
print('Selected residual miss/LBR diagnostic complete.',flush=True)
