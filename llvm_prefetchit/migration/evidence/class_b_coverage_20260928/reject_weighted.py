from pathlib import Path
import sys,json
sys.path.insert(0,'/home/hnpark2/prefetchit/llvm_prefetchit/scripts/class_b')
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_coverage_20260928')
assert (r/'screen_decision.json').exists()
rows=json.load(open(r/'coverage_weighted1_build.json'))
remove_generated([Path(x['path']) for x in rows.values()],r/'weighted1_superseded_cleanup.json','Two-block screen: weighted density reduces primary summed FE_L2 only0.221% vs original, compared with1.287% for full. Retain full/NOP as next-stage reference; weighted E2E point improvement is exploratory and all results remain.')
