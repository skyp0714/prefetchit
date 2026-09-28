from pathlib import Path
import sys,json
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import fullset as h
r=Path('/storage/prefetchit/class_b_coverage_20260928')
assert (r/'screen/complete.json').exists()
h.platform(r/'indirect_capture',['python3',repo/'llvm_prefetchit/scripts/class_b/dense_causes.py','trial',r/'indirect_capture_spec.json'])
