from pathlib import Path
import json,sys
sys.path.insert(0,'/home/hnpark2/prefetchit/llvm_prefetchit/scripts/class_b')
import dense_build as b
r=Path('/storage/prefetchit/class_b_coverage_20260928')
for name in ('indirect','lift','paths'):
 folder=r/('tests_'+name)
 assert 'passed' in (r/('tests_'+name+'.log')).read_text()
 if folder.exists():
  b.save(r/('test_'+name+'_artifact_hashes.json'),[{"path":str(p),"bytes":p.stat().st_size,"sha256":b.sha(p)} for p in folder.rglob('*') if p.is_file() and not p.is_symlink()])
  b.remove_build(folder,r/('test_'+name+'_cleanup.json'))
