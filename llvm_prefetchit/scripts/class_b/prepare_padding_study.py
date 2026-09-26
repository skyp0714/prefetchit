#!/usr/bin/env python3
"""Prepare exact-layout library-coverage candidates between timing stages."""
import argparse
import json
from pathlib import Path

import social_headroom as h
from retain_artifacts import cleanup


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--wide',action='store_true');a=p.parse_args()
    prior='padding_screen' if a.wide else 'screen'
    study='padding_wide_screen' if a.wide else 'padding_screen'
    assert (h.OUT/prior/'complete.json').exists(),'finish the active screen before builds/disassembly'
    h.c.space()
    h.c.run(['taskset','-c','84-85',h.REPO/'profiling/.venv/bin/python','-m','pytest','-q',
             h.REPO/'llvm_prefetchit/tests/test_wake_padding_stream.py'],h.OUT/(study+'_test.log'))
    base=h.c.S/'social_build/usertimeline/base'/h.EXE
    arms={'base':dict(binary=str(base))}
    hashes={}
    for cap in ((256,) if a.wide else (64,256)):
        name=f'padding_loop{cap}' if a.wide else f'padding{cap}'
        binary=h.OUT/name/h.EXE
        h.c.space()
        command=['taskset','-c','84-85','python3',h.REPO/'llvm_prefetchit/scripts/class_b/padding_stream.py',
            base,h.TRACE/'training/runs',binary,'--lead','8','--window','48','--cap',str(cap),
            '--per-function','2','--p-min','.5' if a.wide else '.8']
        if a.wide:command+=['--allow-loops']
        h.c.run(command,h.OUT/(name+'.log'))
        metadata=json.loads(binary.with_name(binary.name+'.json').read_text())
        if metadata['sha256'] in hashes:
            cleanup([binary],h.OUT/name/'duplicate_cleanup.json',
                    'Same binary as '+hashes[metadata['sha256']]+'; candidate count did not reach the lower cap')
            continue
        hashes[metadata['sha256']]=name
        arms[name]=dict(binary=str(binary),controls=['base'])
    manifest=dict(out=str(h.OUT/study),pool=4,rate=600,seedbase=8101,blocks=1,pmu=True,
        arms=arms,selection='Exploratory expansion of in-image library coverage; unchanged base is the exact NOP control. Select a frozen candidate for fresh-seed confirmation; do not pool screen data into confirmation.')
    h.c.save(h.OUT/(study+'_manifest.json'),manifest)
    h.c.run(['python3',h.REPO/'llvm_prefetchit/scripts/class_b/paired_study.py',
             h.OUT/(study+'_manifest.json')],h.OUT/(study+'.log'),timeout=3600)


if __name__=='__main__':main()
