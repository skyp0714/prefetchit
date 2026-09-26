"""Private source and generated build directories; no changes to benchmark sources."""
from common import *
import argparse,io,tarfile
EXES={'compose':'ComposeReviewService','rating':'RatingService','composepost':'ComposePostService','usertimeline':'UserTimelineService'}
def prepare(stack='media'):
 root=S/(stack+'_build');root.mkdir(parents=True,exist_ok=True)
 folder='mediaMicroservices' if stack=='media' else 'socialNetwork';source=root/folder
 if not source.exists():
  dsb=REPO/'benchmarks/DeathStarBench';paths=[folder+'/'+x for x in ['CMakeLists.txt','src','gen-cpp','cmake']]
  archive=subprocess.check_output(['git','-C',str(dsb),'archive','HEAD',*paths])
  with tarfile.open(fileobj=io.BytesIO(archive)) as tf:tf.extractall(root,filter='data')
  dep=dsb/folder/'third_party/PicoSHA2/picosha2.h'
  if dep.exists():
   target=source/'third_party/PicoSHA2';target.mkdir(parents=True);shutil.copy2(dep,target/dep.name)
  logger=source/'src/logger.h';original=logger.read_text();assert any('boost::log::trivial::severity >= boost::log::trivial::'+level in original for level in ['debug','info'])
  logger.write_text(original.replace('boost::log::trivial::severity >= boost::log::trivial::debug','boost::log::trivial::severity >= boost::log::trivial::info'))
  cmake=source/'CMakeLists.txt';cmake_original=cmake.read_text()
  cmake.write_text(cmake_original.replace('set(CMAKE_CXX_FLAGS "-O3")','set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3")'))
  save(root/'source.json',dict(commit=subprocess.check_output(['git','-C',str(dsb),'rev-parse','HEAD'],text=True).strip(),tree_paths=paths,archive_sha256=hashlib.sha256(archive).hexdigest(),logging='info identically for all modes',logger_before_sha256=hashlib.sha256(original.encode()).hexdigest(),logger_after_sha256=sha(logger)))
  save(root/'cmake_flags.json',dict(before=cmake_original,after=cmake.read_text(),reason='Preserve passed compiler flags including pass plugin; identical O3 and source for baseline/PF/NOP'))
 helper=root/'build_service.sh'
 helper.write_text((REPO/'flat_codegen/dsb_build/build_service.sh').read_text().replace('CC=clang-19 CXX="clang++-19 $EXTRA"','CC=clang-19 CXX=clang++-19').replace('make -j32','make -j16'))
 return root,source,helper
def build(key,arm='base',plan=None):
 space();stack='media' if key in ['compose','rating'] else 'social';root,source,helper=prepare(stack);out=root/key/arm;out.mkdir(parents=True,exist_ok=False);exe=EXES[key]
 envs=['-e','MAKE_TARGET='+exe,'-e','BIN_GLOB='+exe,'-e','FATSTATIC=1'];extra=[]
 if plan:
  envs+=['-e','PREFETCHIT_COLD_PLAN='+str(plan),'-e','PREFETCHIT_COLD_DIRECT_IN_PIC=1'];extra=['-fpass-plugin=/pass/PrefetchITPass.so']
 cmd=['docker','run','--rm','--cpuset-cpus','48-63','-v',str(source)+':/src','-v',str(REPO/'llvm_prefetchit/build')+':/pass:ro','-v',str(REPO/'flat_codegen/dsb_build')+':/dsb:ro','-v',str(root)+':'+str(root),'-v',str(T)+':'+str(T)+':ro',*envs,'--entrypoint','bash','dsb-deps-jammy',str(helper),str(out),'-O3','-g','-Wno-enum-constexpr-conversion','-Wno-error',*extra]
 success=False
 try:
  run(cmd,out/'build.log',timeout=2400)
  for name in ['make.log','cmake.log']:
   if (source/'build'/name).exists():shutil.copy2(source/'build'/name,out/name)
  symbols=set()
  for obj in (source/'build').rglob('*.o'):
   for line in subprocess.check_output(['nm','--defined-only',str(obj)],text=True).splitlines():
    row=line.split()
    if len(row)==3 and row[1] in 'TtWw':symbols.add(row[2])
  (out/'instrumentable.txt').write_text('\n'.join(sorted(symbols))+'\n')
  binary=out/exe;save(out/'binary.json',dict(path=str(binary),sha256=sha(binary),bytes=binary.stat().st_size,pass_sha256=sha(REPO/'llvm_prefetchit/build/PrefetchITPass.so'),source=json.loads((root/'source.json').read_text())))
  dis=subprocess.check_output(['objdump','-d',str(binary)],text=True);count=sum('prefetcht1' in line for line in dis.splitlines());save(out/'insertion_audit.json',dict(prefetcht1_count=count,plan=str(plan) if plan else None))
  assert count>0 if plan else count==0,'Unexpected baseline hints or no emitted hints; NOP control would not isolate inserted code'
  if plan:
   run(['python3',REPO/'llvm_prefetchit/tools/make_nop_control_binary.py','--input',binary,'--output',str(binary)+'.nop','--mnemonics','prefetcht1'],out/'nop.log')
   save(out/'nop.json',dict(sha256=sha(str(binary)+'.nop'),bytes=Path(str(binary)+'.nop').stat().st_size))
  print('Built',key,arm,flush=True)
  success=True
 finally:
  d=source/'build'
  if d.exists():
   for name in ['make.log','cmake.log']:
    if (d/name).exists():shutil.copy2(d/name,out/name)
   records=[dict(path=str(x),bytes=x.stat().st_size) for x in d.rglob('*') if x.is_file() and not x.is_symlink()];save(out/'build_cleanup.json',dict(removed=records,bytes_removed=sum(x['bytes'] for x in records),reason='Generated compile outputs; private source, binary hash, object symbol list, commands/logs retained'));shutil.rmtree(d)
  if not success:
   removed=[]
   for name in [exe,exe+'.nop']:
    p=out/name
    if p.exists():removed.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)));p.unlink()
   save(out/'failed_cleanup.json',dict(removed=removed,reason='Build/audit failed; logs, commands, source preserved'))
 return out/exe

def build_support(stack):
 space();root,source,helper=prepare(stack);out=root/'support';out.mkdir(exist_ok=False)
 cmd=['docker','run','--rm','--cpuset-cpus','48-63','-v',str(source)+':/src','-v',str(REPO/'llvm_prefetchit/build')+':/pass:ro','-v',str(REPO/'flat_codegen/dsb_build')+':/dsb:ro','-v',str(root)+':'+str(root),'-e','MAKE_TARGET=all','-e','FATSTATIC=0','--entrypoint','bash','dsb-deps-jammy',str(helper),str(out),'-O3','-g','-Wno-enum-constexpr-conversion','-Wno-error']
 try:
  run(cmd,out/'build.log',timeout=3600)
  save(out/'binaries.json',{p.name:dict(sha256=sha(p),bytes=p.stat().st_size) for p in out.glob('*Service')})
 finally:
  d=source/'build'
  if d.exists():
   for name in ['make.log','cmake.log']:
    if (d/name).exists():shutil.copy2(d/name,out/name)
   records=[dict(path=str(x),bytes=x.stat().st_size) for x in d.rglob('*') if x.is_file() and not x.is_symlink()];save(out/'build_cleanup.json',dict(removed=records,bytes_removed=sum(x['bytes'] for x in records)));shutil.rmtree(d)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('key',choices=list(EXES));p.add_argument('--arm',default='base');p.add_argument('--plan',type=Path);a=p.parse_args();build(a.key,a.arm,a.plan)
