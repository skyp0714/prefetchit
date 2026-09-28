#!/usr/bin/env python3
"""Independent PDIR/PDist sampling check after the primary diagnosis."""
from pathlib import Path
import sys,json,subprocess,shutil,re
import dense_build as b
import dense_causes as d
import fullset as h
from e2e_lbr import remove_generated
r=Path(sys.argv[1])
assert (r/'causes_c4/analysis.json.gz').exists()
# All three primary arms have now been fully decoded, mapped and aggregated.
paths=list((r/'causes_c4').glob('*/*/*/samples.txt'))+list((r/'causes_c4').glob('*/*/dsos/*'))
paths += [Path(str(r/'builds/cause_seq4k'/k/v)+suffix) for k,v in b.SERVICES.items() for suffix in ('','.nop')]
assert len(list((r/'causes_c4').glob('*/*/analysis.json')))==9
remove_generated(paths,r/'cause_primary_cleanup.json','Primary diagnostic complete; per-IP/line/function and branch/PF aggregates, quality, patches, hashes and commands retained; dense policy already failed independent promotion')
pre=r/'pdist_preflight';pre.mkdir();h.c.space()
events={'instructions_pdist':'instructions/period=100003,name=inst_pdist/uppp',
        'l2_pdist':d.SAMPLES['l2']+'p'}
for key,event in events.items():
 dest=pre/key;dest.mkdir()
 cmd=['perf','record','--no-buildid','--no-buildid-cache','-e',event,'-o',str(dest/'perf.data'),'--','python3','-c','sum(i*i for i in range(500000))']
 h.c.run(cmd,dest/'record.log')
 result=subprocess.run(['perf','evlist','-v','-i',str(dest/'perf.data')],capture_output=True,text=True,check=True)
 (dest/'attributes.txt').write_text(result.stdout)
 assert re.search(r'precise_ip\s*[:=]\s*3',result.stdout),result.stdout
 remove_generated([dest/'perf.data'],dest/'cleanup.json','Precise Distribution event support/attributes validated; preflight is not workload evidence')
arms=json.loads((r/'cause_arms.json').read_text())
spec=dict(out=str(r/'pdist_check'),overrides=arms['base']['overrides'],concurrency=4,seed=45002,rounds=0,sample=True,sample_s=8,
 sample_events={'l2':d.SAMPLES['l2'],**events},purpose='Resolve sampling-distribution concern: initial ANY_P pp instruction sample branch share exceeded retired branch/instruction count; new independent seed, separate pp/ppp L2 and ppp instruction reference, no performance promotion')
b.save(r/'pdist_check.json',spec)
h.platform(r/'pdist_check',['python3',Path(d.__file__),'trial',r/'pdist_check.json'])
print('PDIST validation capture completed')
