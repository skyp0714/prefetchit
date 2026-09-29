#!/usr/bin/env python3
"""Advance from scarce executed padding to observed earlier call paths."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import dense_build as b
import fullset as h
from e2e_lbr import remove_generated
from mechanism_report import evaluate


def native_tests(root):
    work=root/'native_test_work';b.space(root)
    runner="import sys;sys.path.insert(0,'/home/hnpark2/prefetchit/profiling/.venv/lib/python3.12/site-packages');import pytest;raise SystemExit(pytest.main(sys.argv[1:]))"
    try:
        b.run(['python3','-c',runner,'-q',b.REPO/'llvm_prefetchit/tests/test_call_stub_prefetch.py',
            b.REPO/'llvm_prefetchit/tests/test_callpath_prefetch.py','--basetemp',work],root/'native_tests.log')
    finally:
        generated=[]
        if work.exists():
            for path in work.rglob('*'):
                if not path.is_file() or path.is_symlink():continue
                with path.open('rb') as f:header=f.read(4)
                if header==b'\x7fELF':generated.append(path)
        if generated:remove_generated(generated,root/'native_test_cleanup.json',
            'Native ABI/unwind/selector test finished; retain fixtures, assembly, commands, patches, hashes and output; remove generated ELF files.')


def smoke(root,prepared):
    previous=root.parent/'backend/profiles/train/backend_runtime.json'
    runtime=json.loads(previous.read_text());image=next(iter(runtime.values()))['image']
    outputs={}
    binaries={'original':prepared['reference']}
    for name,variant in prepared['candidates'].items():
        binaries[name]=variant['binary'];binaries[name+'_nop']=variant['nop']
    for name,path in binaries.items():
        binary=Path(path);b.space(root)
        cmd=['docker','run','--rm','--network','none','--cpuset-cpus','84','--entrypoint','/usr/bin/mongod',
            '-v',str(binary)+':/usr/bin/mongod:ro',image,'--version']
        b.run(cmd,root/('smoke_'+name+'.log'),timeout=30)
        outputs[name]=(root/('smoke_'+name+'.log')).read_text()
    assert len(set(outputs.values()))==1,'Call-stub variants changed --version behavior'
    b.save(root/'smoke.json',dict(valid=True,image=image,outputs=outputs,
        scope='Same original runtime image and --version output; full workload correctness checked separately by each fresh trial.'))


def run(parent):
    assert (parent/'backend/complete.json').exists(),'Finish active backend measurements before builds or tests'
    root=parent/'callpath';root.mkdir(exist_ok=False);b.space(root)
    from retire_backend import retire
    if not (parent/'backend/retired_artifacts.json').exists():retire(parent/'backend')
    base=json.loads((parent/'confirmation_spec.json').read_text())['arms']['base']['overrides']
    reference=parent/'backend/reference/mongod'
    services=['user-review-mongodb','movie-review-mongodb','review-storage-mongodb']
    b.save(root/'protocol.json',dict(source_sha256=b.sha(__file__),training_seeds=[78001,78002],screen_seedbase=79001,training_services=services,
        hypothesis='Long NOPs cover only about 2.4% of heldout Mongo main-image misses. Retain original call/return addresses and issue future-line prefetches at earlier observed direct calls.',
        selection='Train-only 50% sampled miss coverage goal. Primary <=256 call sites/1024 hints; if it misses 50%, consider <=1024 sites/4096 hints and include that separate density arm only for >=5 points added training cover. <=4 hints/site, gain >=8. This coverage is not promised hardware miss reduction.',
        measurement='Fresh full Media C4 stacks, matched 50s warmup +60s clean ROI, original copied Mongo control, same-layout call-stub NOP, T1. All MongoDBs share the same chosen ELF.',
        validation='Native PIE/non-PIE argument/flags/return-address/exception/unwind checks, exact original-byte reversal, direct branch operands, merged FDE preservation, full post-build decoding, container smoke.',
        sources=['https://refspecs.linuxfoundation.org/LSB_5.0.0/LSB-Core-generic/LSB-Core-generic.html',
                 'https://www.sourceware.org/binutils/docs/as/CFI-directives.html']))
    prior=parent/'callpath_native_preflight/complete.json'
    validated=json.loads(prior.read_text()) if prior.exists() else None
    if validated and validated['valid'] and all(b.sha(b.REPO/path)==digest for path,digest in validated['source_sha256'].items()):
        b.save(root/'native_validation.json',dict(reused=str(prior),record_sha256=b.sha(prior),
            reason='Exact builder, selector and native-test source hashes already passed between completed workload trials.',validation=validated))
    else:
        native_tests(root)
    attribution=root/'privilege';manifest=root/'privilege_spec.json'
    b.save(manifest,dict(out=str(attribution),overrides=base,seed=77501))
    h.platform(attribution,['python3',Path(__file__).with_name('privilege_frontend.py'),manifest])
    for phase,seed in [('train',78001),('heldout',78002)]:
        dest=root/'profiles'/phase;manifest=root/(phase+'_spec.json')
        b.save(manifest,dict(out=str(dest),reference=str(reference),overrides=base,seed=seed,services=services))
        h.platform(dest,['python3',Path(__file__).with_name('backend_prefetch.py'),'profile',manifest])
    manifest=root/'prepare_spec.json';b.save(manifest,dict(root=str(root),reference=str(reference),services=services))
    b.run(['python3',Path(__file__).with_name('callpath_prefetch.py'),manifest],root/'prepare.log')
    prepared=json.loads((root/'prepared.json').read_text());smoke(root,prepared)
    arms=dict(original=dict(overrides=base,mongo_binary=str(reference)))
    for name,variant in prepared['candidates'].items():
        arms[name+'_nop']=dict(overrides=base,mongo_binary=variant['nop'],controls=['original'])
        arms[name]=dict(overrides=base,mongo_binary=variant['binary'],controls=['original',name+'_nop'])
        if name!='call256':arms[name]['controls'].append('call256')
    from privilege_frontend import DECODE_EVENTS
    for settings in arms.values():settings['extra_events']={'decode':DECODE_EVENTS}
    manifest=root/'screen_spec.json';b.save(manifest,dict(out=str(root/'screen'),arms=arms,blocks=2,seedbase=79001,exploratory=True))
    b.run(['python3',Path(__file__).with_name('backend_study.py'),'campaign',manifest],root/'screen_driver.log')
    evaluate(root/'screen',root/'screen_evaluation.json')
    candidate=prepared['candidates'][prepared['residual_candidate']]
    dest=root/'residual';manifest=root/'residual_capture_spec.json'
    b.save(manifest,dict(out=str(dest),reference=candidate['binary'],mongo_binary=candidate['binary'],
        overrides=base,seed=80001,services=services))
    h.platform(dest,['python3',Path(__file__).with_name('backend_prefetch.py'),'profile',manifest])
    manifest=root/'residual_analysis_spec.json';b.save(manifest,dict(root=str(root),binary=candidate['binary'],services=services))
    b.run(['python3',Path(__file__).with_name('callpath_prefetch.py'),manifest,'--residual'],root/'residual_analysis.log')
    b.save(root/'complete.json',dict(clean_trials=2*len(arms),prepared=prepared,
        residual_analysis=str(root/'residual_analysis.json'),
        next='Inspect E2E first, then Mongo-specific misses/stalls and added-jump NOP cost. Continue with independent confirmation or a cause-based refinement.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('parent',type=Path);args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted);run(args.parent)
