#!/usr/bin/env python3
"""Isolated dense Media builds, including statically linked dependency code."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import urllib.request

REPO = Path(__file__).resolve().parents[3]
PACKAGES = [
    ('mongo-c-driver-1.15.0', 'https://github.com/mongodb/mongo-c-driver/releases/download/1.15.0/mongo-c-driver-1.15.0.tar.gz'),
    ('thrift-0.12.0', 'https://codeload.github.com/apache/thrift/tar.gz/refs/tags/v0.12.0'),
    ('yaml-cpp-yaml-cpp-0.6.2', 'https://codeload.github.com/jbeder/yaml-cpp/tar.gz/refs/tags/yaml-cpp-0.6.2'),
    ('opentracing-cpp-1.5.1', 'https://codeload.github.com/opentracing/opentracing-cpp/tar.gz/refs/tags/v1.5.1'),
    ('jaeger-client-cpp-0.4.2', 'https://codeload.github.com/jaegertracing/jaeger-client-cpp/tar.gz/refs/tags/v0.4.2'),
]
ARMS = {
    'base': {},
    'callee8': {'PREFETCHIT_CALLEE_BURST_LINES': '8'},
    'seq4k': {'PREFETCHIT_SEQ_DISTANCE': '4096', 'PREFETCHIT_SEQ_STRIDE_INSNS': '20',
              'PREFETCHIT_CALLEE_BURST_LINES': '4'},
    'seq256': {'PREFETCHIT_SEQ_DISTANCE': '256', 'PREFETCHIT_SEQ_STRIDE_INSNS': '20',
               'PREFETCHIT_CALLEE_BURST_LINES': '4'},
}
POLICIES = dict(ARMS, dom_decay={'PREFETCHIT_DOMINATOR': '1', 'PREFETCHIT_DOM_LEAD': '24',
                                'PREFETCHIT_DOM_BATCH': '4', 'PREFETCHIT_DOM_CALLER_TARGETS': '4'})
POLICIES['lean_peak'] = dict(POLICIES['dom_decay'], PREFETCHIT_DOM_LEAN='1',
    PREFETCHIT_DOM_WINDOW='1', PREFETCHIT_DOM_BATCH='8', PREFETCHIT_DOM_CALLER_TARGETS='0',
    PREFETCHIT_DOM_MAX_SITES='2', PREFETCHIT_DOM_MIN_FUNCTION='64')
POLICIES['lean_outline'] = dict(POLICIES['lean_peak'], PREFETCHIT_DOM_OUTLINE='1')
POLICIES['lean_fast'] = dict(POLICIES['lean_outline'], PREFETCHIT_RELAXED_CLOCK='1')
POLICIES['lean_memo'] = dict(POLICIES['lean_fast'], PREFETCHIT_MEMO_GATE='1')
POLICIES['lean_meta'] = dict(POLICIES['lean_fast'], PREFETCHIT_DOM_METADATA='1')
POLICIES['lean_meta_memo'] = dict(POLICIES['lean_memo'], PREFETCHIT_DOM_METADATA='1')
POLICIES['lean_meta_one_far'] = dict(POLICIES['lean_meta'], PREFETCHIT_DOM_MAX_SITES='1',
                                    PREFETCHIT_DOM_LEAD='64')
POLICIES['lean_meta_ungated'] = dict(POLICIES['lean_meta_one_far'], PREFETCHIT_DOM_SCHED_GATE='0',
                                    PREFETCHIT_DOM_OUTLINE='0', PREFETCHIT_DOM_WINDOW='0')
POLICIES['lean_meta_callees'] = dict(POLICIES['lean_meta'], PREFETCHIT_DOM_MAX_SITES='1',
                                    PREFETCHIT_DOM_CALLEE_ONLY='1')
POLICIES['lean_meta_one_far_diag'] = dict(POLICIES['lean_meta_one_far'], PREFETCHIT_GATE_STATS='1')
POLICIES['lean_meta_callees_diag'] = dict(POLICIES['lean_meta_callees'], PREFETCHIT_GATE_STATS='1')
POLICIES['lean_meta_callees_static'] = dict(POLICIES['lean_meta_callees'], PREFETCHIT_COLD_DIRECT_IN_PIC='1')
POLICIES['lean_meta_callees_static_diag'] = dict(POLICIES['lean_meta_callees_static'], PREFETCHIT_GATE_STATS='1')
POLICIES['lean_meta_callees_static_ungated'] = dict(POLICIES['lean_meta_callees_static'],
    PREFETCHIT_DOM_SCHED_GATE='0', PREFETCHIT_DOM_OUTLINE='0', PREFETCHIT_DOM_WINDOW='0')
POLICIES['coverage_callees'] = dict(POLICIES['lean_meta_callees_static_ungated'],
    PREFETCHIT_DOM_MIN_FUNCTION='0', PREFETCHIT_DOM_SKIP_SHORT='0',
    PREFETCHIT_DOM_MAX_SITES='4', PREFETCHIT_DOM_BATCH='8')
POLICIES['coverage_indirect'] = dict(POLICIES['coverage_callees'])
SERVICES = {'movie': 'MovieIdService', 'compose': 'ComposeReviewService', 'rating': 'RatingService'}


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str)+'\n')


def space(root):
    assert shutil.disk_usage('/').free > 7*2**30
    assert shutil.disk_usage(root).free > 30*2**30


def run(command, log, **kwargs):
    save(log.with_suffix('.command.json'), command)
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT,
                       check=True, **kwargs)


def remove_build(directory, record):
    """Remove only this build's generated tree, after durable audit metadata."""
    if not directory.exists(): return
    assert directory.is_dir() and not directory.is_symlink()
    files = []
    for path in directory.rglob('*'):
        if path.is_symlink(): files.append(dict(path=str(path), symlink=os.readlink(path)))
        elif path.is_file(): files.append(dict(path=str(path), bytes=path.stat().st_size))
    data = dict(path=str(directory), files=files, bytes_removed=sum(r.get('bytes',0) for r in files),
                free_before=shutil.disk_usage(directory).free,
                reason='Generated dependency/service compile tree; source, commands, logs, installed library hashes and ELF retained')
    save(record, data)
    shutil.rmtree(directory)  # does not traverse directory symlinks
    data.update(complete=True, free_after=shutil.disk_usage(record.parent).free)
    save(record, data)


def prepare(root):
    root.mkdir(parents=True, exist_ok=False); space(root)
    source = root/'dependency_sources'; source.mkdir()
    archives = root/'original_packages'; archives.mkdir()
    manifest = []
    for name, url in PACKAGES:
        space(root)
        archive = archives/(name+'.tar.gz')
        with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        with tarfile.open(archive) as tf: tf.extractall(source, filter='data')
        assert (source/name).is_dir(), name
        manifest.append(dict(name=name, url=url, bytes=archive.stat().st_size, sha256=sha(archive)))
        save(root/'packages.json', manifest)
    benchmark = REPO/'benchmarks/DeathStarBench'
    paths = ['mediaMicroservices/'+name for name in ('CMakeLists.txt','src','gen-cpp','cmake')]
    data = subprocess.check_output(['git','-C',str(benchmark),'archive','HEAD',*paths])
    source = root/'benchmark_source'; source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data)) as tf: tf.extractall(source,filter='data')
    source = source/'mediaMicroservices'
    header = benchmark/'mediaMicroservices/third_party/PicoSHA2/picosha2.h'
    if header.exists():
        target=source/'third_party/PicoSHA2';target.mkdir(parents=True)
        shutil.copyfile(header,target/header.name)
    logger = source/'src/logger.h'; original = logger.read_text()
    logger.write_text(original.replace('boost::log::trivial::severity >= boost::log::trivial::debug',
                                       'boost::log::trivial::severity >= boost::log::trivial::info'))
    cmake = source/'CMakeLists.txt'
    cmake.write_text(cmake.read_text().replace('set(CMAKE_CXX_FLAGS "-O3")',
                                             'set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3")'))
    helper = (REPO/'flat_codegen/dsb_build/build_service.sh').read_text()
    helper = helper.replace('CC=clang-19 CXX="clang++-19 $EXTRA"','CC=clang-19 CXX=clang++-19').replace('make -j32','make -j16')
    (root/'build_service.sh').write_text(helper)
    save(root/'source.json',dict(commit=subprocess.check_output(['git','-C',str(benchmark),'rev-parse','HEAD'],text=True).strip(),
        archive_sha256=hashlib.sha256(data).hexdigest(),logger_before_sha256=hashlib.sha256(original.encode()).hexdigest(),
        logger_after_sha256=sha(logger),logging='info identically for every arm',helper_sha256=sha(root/'build_service.sh')))
    save(root/'protocol.json',dict(arms=ARMS,services=SERVICES,base_image='dsb-deps-jammy',
        scope='Rebuild Media sources plus mongo-c/bson, thrift, yaml-cpp, opentracing, jaeger. System libstdc++, libc and libmemcached remain uninstrumented.',
        plugin_sha256=sha(REPO/'llvm_prefetchit/build/PrefetchITPass.so'),
        primary='Whole-stack and individual-service user+kernel CPU/request; external mean and p99',
        controls='Fresh rebuilt no-prefetch baseline; each dense arm has an exact-layout NOP twin',
        selection='Three frozen dense policies, no trace ranking or existing-NOP site restriction'))


def worker(arm, tag=None, drop_plan=None, functions_file=None, callees_file=None, indirect_file=None):
    tag=tag or arm;assert re.fullmatch('[a-z0-9_]+',tag)
    root = Path('/dense'); out = root/'builds'/tag; out.mkdir(parents=True,exist_ok=False)
    env = {k:v for k,v in os.environ.items() if not k.startswith('PREFETCHIT_')}; env.update(POLICIES[arm])
    if POLICIES[arm].get('PREFETCHIT_COLD_DIRECT_IN_PIC'):
        assert callees_file,'Static callee references require an explicit known-main-image target profile'
    if functions_file:
        assert POLICIES[arm]
        names = [line.strip() for line in Path(functions_file).read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        assert names and len(names) == len(set(names))
        env['PREFETCHIT_SEQ_FUNCTIONS_FILE'] = str(functions_file)
        save(out/'function_selection.json',dict(path=str(functions_file),sha256=sha(functions_file),names=names))
    if callees_file:
        assert POLICIES[arm].get('PREFETCHIT_DOM_CALLEE_ONLY') == '1'
        names=[line.strip() for line in Path(callees_file).read_text().splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
        assert names and len(names)==len(set(names))
        env['PREFETCHIT_DOM_CALLEE_PROFILE']=str(callees_file)
        save(out/'callee_selection.json',dict(path=str(callees_file),sha256=sha(callees_file),names=names))
    if indirect_file:
        assert callees_file and POLICIES[arm].get('PREFETCHIT_COLD_DIRECT_IN_PIC') == '1'
        env['PREFETCHIT_DOM_INDIRECT_TARGETS'] = str(indirect_file)
        save(out/'indirect_selection.json',dict(path=str(indirect_file),sha256=sha(indirect_file),
                                              profile=json.loads(Path(indirect_file).read_text())))
    if drop_plan:
        assert POLICIES[arm].get('PREFETCHIT_DOM_METADATA') == '1'
        plan = json.loads(Path(drop_plan).read_text())
        assert plan['schema'] == 'prefetchit.dom_drop.v1'
        env['PREFETCHIT_DOM_DROP_PLAN'] = str(drop_plan)
        save(out/'drop_plan.json', dict(path=str(drop_plan), sha256=sha(drop_plan), plan=plan))
    flags = '-fpass-plugin=/pass/PrefetchITPass.so' if POLICIES[arm] else ''
    definitions = {
        PACKAGES[0][0]: ['-DENABLE_TESTS=OFF','-DENABLE_EXAMPLES=OFF','-DENABLE_SHM_COUNTERS=OFF',
                         '-DENABLE_STATIC=ON','-DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined'],
        PACKAGES[1][0]: ['-DBUILD_COMPILER=OFF','-DWITH_SHARED_LIB=OFF','-DBUILD_TESTING=OFF',
                         '-DBUILD_TUTORIALS=OFF','-DBUILD_PYTHON=OFF','-DBUILD_JAVA=OFF',
                         '-DBUILD_JAVASCRIPT=OFF','-DBUILD_NODEJS=OFF'],
        PACKAGES[2][0]: ['-DYAML_CPP_BUILD_TESTS=OFF','-DYAML_CPP_BUILD_TOOLS=OFF','-DYAML_CPP_BUILD_CONTRIB=OFF'],
        PACKAGES[3][0]: ['-DBUILD_TESTING=OFF','-DBUILD_SHARED_LIBS=OFF'],
        PACKAGES[4][0]: ['-DHUNTER_ENABLED=OFF','-DBUILD_SHARED_LIBS=OFF','-DBUILD_TESTING=OFF',
                         '-DJAEGERTRACING_WITH_YAML_CPP=ON','-DJAEGERTRACING_BUILD_EXAMPLES=OFF'],
    }
    for name, _ in PACKAGES:
        space(root); source = Path('/opt/src')/name; build = source/'dense_build'
        assert not build.exists()
        cflags = ('-fPIC -Wno-error -Wno-enum-constexpr-conversion -Wno-deprecated-declarations -O2 -g '+flags).strip()
        command = ['cmake','-S',source,'-B',build,'-DCMAKE_C_COMPILER=clang-19',
            '-DCMAKE_CXX_COMPILER=clang++-19','-DCMAKE_BUILD_TYPE=RelWithDebInfo',
            '-DCMAKE_C_FLAGS='+cflags,'-DCMAKE_CXX_FLAGS='+cflags,*definitions[name]]
        try:
            run(command,out/(name+'_configure.log'),env=env)
            run(['cmake','--build',build,'-j','16'],out/(name+'_build.log'),env=env)
            run(['cmake','--install',build],out/(name+'_install.log'),env=env)
            installed = {str(p):sha(p) for p in Path('/usr/local/lib').glob('*.a')}
            save(out/(name+'_installed_hashes.json'),installed)
        finally:
            remove_build(build,out/(name+'_build_cleanup.json'))
    subprocess.run(['ldconfig'],check=True)
    source = root/'benchmark_source/mediaMicroservices'
    for key, exe in SERVICES.items():
        space(root); dest=out/key;dest.mkdir()
        service_env=dict(env,MAKE_TARGET=exe,BIN_GLOB=exe,FATSTATIC='1')
        if POLICIES[arm].get('PREFETCHIT_DOMINATOR') and POLICIES[arm].get('PREFETCHIT_DOM_SCHED_GATE','1') != '0':
            runtime = out/'sched_runtime.o'
            if not runtime.exists():
                runtime_defines=['-D'+name+'='+env[name] for name in
                                 ('PREFETCHIT_RELAXED_CLOCK','PREFETCHIT_MEMO_GATE','PREFETCHIT_GATE_STATS') if name in env]
                run(['clang-19','-O2','-fPIC',*runtime_defines,'-c',
                     '/repo/llvm_prefetchit/kernel/sched_clock/runtime.c','-o',runtime],
                    out/'runtime_build.log',env=env)
                save(out/'runtime.json',dict(source_sha256=sha('/repo/llvm_prefetchit/kernel/sched_clock/runtime.c'),
                                           object_sha256=sha(runtime),defines=runtime_defines))
            service_env['PREFETCHIT_RUNTIME_OBJECT'] = str(runtime)
        command=['bash',root/'build_service.sh',dest,'-O3','-g','-Wno-enum-constexpr-conversion','-Wno-error']
        if flags:command.append(flags)
        try:
            run(command,dest/'build.log',env=service_env)
            save(dest/'binary.json',dict(path=str(dest/exe),sha256=sha(dest/exe),bytes=(dest/exe).stat().st_size))
        finally:
            build=source/'build'
            for log in ('make.log','cmake.log'):
                if (build/log).exists():shutil.copyfile(build/log,dest/log)
            remove_build(build,dest/'build_cleanup.json')
    save(out/'complete.json',dict(arm=arm,tag=tag,settings=POLICIES[arm],installed_hashes={str(p):sha(p) for p in Path('/usr/local/lib').glob('*.a')}))


def build(root, arm, tag=None, plugin_dir=None, drop_plan=None, functions_file=None, callees_file=None, indirect_file=None):
    space(root)
    if POLICIES[arm].get('PREFETCHIT_COLD_DIRECT_IN_PIC'):
        assert callees_file,'Static callee references require an explicit known-main-image target profile'
    tag=tag or arm;assert re.fullmatch('[a-z0-9_]+',tag)
    name='codex-dense-build-20260927-'+tag
    assert not subprocess.check_output(['docker','ps','-aq','--filter','name=^/'+name+'$'],text=True).strip()
    image_id=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','dsb-deps-jammy'],text=True).strip()
    save(root/(tag+'_image.json'),dict(tag='dsb-deps-jammy',id=image_id))
    plugin_dir = plugin_dir or REPO/'llvm_prefetchit/build'
    if drop_plan:
        drop_plan = Path(drop_plan).resolve()
        drop_plan.relative_to(root.resolve())
        assert drop_plan.is_file() and not drop_plan.is_symlink()
    if functions_file:
        functions_file = Path(functions_file).resolve()
        functions_file.relative_to(root.resolve())
        assert functions_file.is_file() and not functions_file.is_symlink() and POLICIES[arm]
    if callees_file:
        callees_file=Path(callees_file).resolve();callees_file.relative_to(root.resolve())
        assert callees_file.is_file() and not callees_file.is_symlink()
        assert POLICIES[arm].get('PREFETCHIT_DOM_CALLEE_ONLY') == '1'
    if indirect_file:
        indirect_file = Path(indirect_file).resolve();indirect_file.relative_to(root.resolve())
        assert indirect_file.is_file() and not indirect_file.is_symlink() and callees_file
    save(root/(tag+'_implementation.json'),dict(settings=POLICIES[arm],
        plugin_sha256=sha(plugin_dir/'PrefetchITPass.so'),driver_sha256=sha(__file__),
        drop_plan_sha256=sha(drop_plan) if drop_plan else None,
        functions_file_sha256=sha(functions_file) if functions_file else None,
        callees_file_sha256=sha(callees_file) if callees_file else None,
        indirect_file_sha256=sha(indirect_file) if indirect_file else None,
        source_hashes={str(p.relative_to(REPO)):sha(p) for p in
                      (REPO/'llvm_prefetchit/lib').glob('*') if p.is_file()}))
    command=['docker','run','--rm','--name',name,'--label','prefetchit.dense=20260927',
        '--network=none','--cpuset-cpus','48-63',
        '-v',str(root)+':/dense','-v',str(root/'dependency_sources')+':/opt/src',
        '-v',str(root/'benchmark_source/mediaMicroservices')+':/src',
        '-v',str(REPO)+':/repo:ro','-v',str(plugin_dir)+':/pass:ro',
        '--entrypoint','python3',image_id,
        '/repo/llvm_prefetchit/scripts/class_b/dense_build.py','worker','/dense','--arm',arm,'--tag',tag]
    if drop_plan:
        command += ['--drop-plan', str(Path('/dense')/drop_plan.relative_to(root.resolve()))]
    if functions_file:
        command += ['--functions-file', str(Path('/dense')/functions_file.relative_to(root.resolve()))]
    if callees_file:
        command += ['--callees-file',str(Path('/dense')/callees_file.relative_to(root.resolve()))]
    if indirect_file:
        command += ['--indirect-file',str(Path('/dense')/indirect_file.relative_to(root.resolve()))]
    try:
        run(command,root/(tag+'_build.log'),timeout=7200)
    except BaseException as error:
        save(root/(tag+'_build_failure.json'),dict(error=repr(error)))
        inspect=subprocess.run(['docker','inspect','--format','{{index .Config.Labels "prefetchit.dense"}}',name],capture_output=True,text=True)
        if inspect.returncode==0:
            assert inspect.stdout.strip()=='20260927'
            subprocess.run(['docker','rm','-f',name],check=True,stdout=subprocess.DEVNULL)
        for source, _ in PACKAGES:
            remove_build(root/'dependency_sources'/source/'dense_build',root/(tag+'_'+source+'_failed_cleanup.json'))
        remove_build(root/'benchmark_source/mediaMicroservices/build',root/(tag+'_service_failed_cleanup.json'))
        removed=[]
        for exe in SERVICES.values():
            for binary in (root/'builds'/tag).glob('*/'+exe):
                assert not binary.is_symlink()
                removed.append(dict(path=str(binary),bytes=binary.stat().st_size,sha256=sha(binary)))
        save(root/(tag+'_failed_binaries_cleanup.json'),dict(files=removed,reason='Failed build; source and logs retained'))
        for row in removed:Path(row['path']).unlink()
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','worker','build']);p.add_argument('root',type=Path)
    p.add_argument('--arm',choices=list(POLICIES));p.add_argument('--tag');p.add_argument('--plugin-dir',type=Path)
    p.add_argument('--drop-plan',type=Path);p.add_argument('--functions-file',type=Path)
    p.add_argument('--callees-file',type=Path);p.add_argument('--indirect-file',type=Path);a=p.parse_args()
    def interrupted(signum,frame):raise KeyboardInterrupt(signum)
    if a.action!='worker':signal.signal(signal.SIGTERM,interrupted)
    if a.action=='prepare':prepare(a.root)
    elif a.action=='worker':worker(a.arm,a.tag,a.drop_plan,a.functions_file,a.callees_file,a.indirect_file)
    else:build(a.root,a.arm,a.tag,a.plugin_dir,a.drop_plan,a.functions_file,a.callees_file,a.indirect_file)


if __name__=='__main__':main()
