from pathlib import Path
import json,sys,shutil,subprocess,os
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
r=Path('/storage/prefetchit/class_b_coverage_20260928');b.space(r)
assert (r/'screen_indirect/complete.json').exists()
assert not subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project=codex-b-fullset-media'],text=True).strip()
(r/'plugin_paths').mkdir(exist_ok=False)
image=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','dsb-deps-jammy'],text=True).strip()
command=['docker','run','--rm','--network=none','--cpuset-cpus','48-51','-v',str(repo/'llvm_prefetchit')+':/source:ro','-v','/opt/llvm-19.1.7/include:/llvm-include:ro','-v',str(r)+':/out','--entrypoint','bash',image,'-c','clang++-19 -shared -fPIC -O2 -std=c++17 -fno-exceptions -fno-rtti -I/llvm-include /source/lib/PrefetchITPass.cpp -o /out/plugin_paths/PrefetchITPass.so']
paths=list((repo/'llvm_prefetchit/lib').glob('*'))+[repo/'llvm_prefetchit/scripts/class_b/dense_build.py',repo/'llvm_prefetchit/scripts/class_b/indirect_profile.py',Path(__file__),r/'build_paths.py']
for path in paths:
 if path.is_file():
  relative=path.relative_to(repo) if path.is_relative_to(repo) else Path(path.name)
  dest=r/'sources_paths'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
b.save(r/'sources_paths.json',{str(p):b.sha(p) for p in paths if p.is_file()})
b.run(command,r/'plugin_paths_build.log')
b.save(r/'plugin_paths_hash.json',dict(sha256=b.sha(r/'plugin_paths/PrefetchITPass.so'),image=image))
command=[str(repo/'profiling/.venv/bin/python'),'-m','pytest','-q','llvm_prefetchit/tests/test_dominator_prefetch.py','llvm_prefetchit/tests/test_lean_it0.py','llvm_prefetchit/tests/test_lean_plan.py','llvm_prefetchit/tests/test_lean_profile.py','llvm_prefetchit/tests/test_coverage_plan.py','llvm_prefetchit/tests/test_indirect_profile.py','llvm_prefetchit/tests/test_path_prefetch.py','--basetemp='+str(r/'tests_paths'),'-o','cache_dir='+str(r/'test_cache_paths')]
b.run(command,r/'tests_paths.log',env=dict(os.environ,DOMINATOR_TEST_PLUGIN=str(r/'plugin_paths/PrefetchITPass.so')),cwd=repo)
print('Plugin and compiler integration tests passed.',flush=True)
