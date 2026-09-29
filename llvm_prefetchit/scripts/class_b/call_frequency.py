#!/usr/bin/env python3
"""Measure call execution cost independently of miss-conditioned LBR samples."""
import argparse
import collections
import json
from pathlib import Path
import re
import subprocess
import dense_build as b
import fullset as h
from dense_causes import decode
from dense_cause_analysis import HEADER,Code,category
from e2e_lbr import remove_generated
from lean_timeline import executable_maps,translate

EVENT='cpu/event=0xc4,umask=0x2,period=4093,name=near_calls/upp'


def preflight(root):
    """Require PEBS call IPs to identify known direct-call instruction starts."""
    root.mkdir(parents=True,exist_ok=False);b.space(root)
    source=root/'probe.s';binary=root/'probe'
    source.write_text('''.text
.global _start, call_a, call_b, leaf
_start:
 mov $5000000, %edx
again:
call_a: call leaf
call_b: call leaf
 dec %edx
 jnz again
 xor %edi, %edi
 mov $60, %eax
 syscall
leaf: ret
.section .note.GNU-stack,"",@progbits
''')
    outputs=[binary]
    try:
        b.run(['gcc','-nostdlib','-no-pie',source,'-o',binary],root/'build.log')
        symbols={r[2]:int(r[0],16) for line in subprocess.check_output(['nm',binary],text=True).splitlines()
                 if len(r:=line.split())==3}
        sites={symbols['call_a'],symbols['call_b']}
        (root/'probe.asm').write_text(subprocess.check_output(['objdump','-d',binary],text=True))
        b.space(root)
        b.run(['perf','record','--no-buildid','--no-buildid-cache','-m','8M','-e',EVENT,'-j','any,u',
               '-o',root/'perf.data','--','taskset','-c','84',binary],root/'record.log')
        decode(root)
        histogram=collections.Counter();all_samples=0
        for line in (root/'samples.txt').open():
            match=HEADER.match(line)
            if not match:continue
            all_samples+=1;histogram[int(match[2],16)]+=1
        types=json.loads((root/'record_types.json').read_text())
        assert all_samples==types['SAMPLE'] and all_samples>100
        matched=sum(histogram[s] for s in sites)
        result=dict(event=EVENT,sites=sorted(sites),samples=all_samples,matched=matched,
            fraction_at_call_instruction=matched/all_samples,
            histogram={hex(k):v for k,v in histogram.items()},source_sha256=b.sha(source),binary_sha256=b.sha(binary),
            commands_scope='Dedicated CPU 84, outside service measurement. No performance inference.',
            valid=matched/all_samples>=.99)
        b.save(root/'result.json',result)
        assert result['valid'],'Near-call PEBS did not identify exact known call sites; inspect before using frequency weights'
    except BaseException as error:
        b.save(root/'failure.json',dict(error=repr(error)));raise
    finally:
        outputs.extend(p for p in [root/'perf.data',root/'samples.txt'] if p.exists())
        outputs=[p for p in outputs if p.exists()]
        if outputs:remove_generated(outputs,root/'cleanup.json',
            'Call-IP preflight finished. Retain source, disassembly, counts, hashes, commands and validation; remove generated ELF and decoded/raw copies.')


def analyze(root,reference,services):
    assert json.loads((root/'complete.json').read_text())['valid'];b.space(root)
    assert json.loads((root/'protocol.json').read_text())['event']==EVENT
    code=Code(reference);records={}
    for name in services:
        folder=root/name;mappings=executable_maps(reference,(folder/'maps.txt').read_text())
        counts=collections.Counter();ips=collections.Counter()
        for line in (folder/'samples.txt').open():
            match=HEADER.match(line)
            if not match:continue
            counts['all_samples']+=1
            if match[3][1:-1] not in ('/usr/bin/mongod','mongod'):continue
            ip=translate(int(match[2],16),mappings)
            assert ip is not None
            counts['main_samples']+=1;ips[ip]+=1
            counts[category(code.get(ip)[1])]+=1
        expected=json.loads((folder/'record_types.json').read_text())['SAMPLE']
        assert expected==counts['all_samples'] and expected>100
        calls=counts['direct_call']+counts['indirect_call']
        valid=calls/counts['main_samples']>=.99
        requests=json.loads((folder/'request_window.json').read_text())
        record=dict(counts=dict(counts),valid=valid,request_window=requests,period=4093,
            exact_call_fraction=calls/counts['main_samples'],decoded_sha256=b.sha(folder/'samples.txt'),
            zero_sample_cost_floor_per_request=3*4093/requests['completed_requests'],
            cost_floor_meaning='Three-sample regularization for unseen sites; not a confidence interval or an execution bound.',
            histogram={str(ip):n for ip,n in sorted(ips.items())},
            direct_call_estimates={str(ip):n*4093/requests['completed_requests'] for ip,n in ips.items()
                                   if category(code.get(ip)[1])=='direct_call'})
        b.save(folder/'frequency.json',record);records[name]=record
        remove_generated([folder/'samples.txt'],folder/'frequency_cleanup.json',
            'Complete IP frequency histogram, class/quality counts, period, request denominator and trace hash retained.')
    valid=all(row['valid'] for row in records.values())
    b.save(root/'frequency_summary.json',dict(records=records,valid=valid,reference_sha256=b.sha(reference),source_sha256=b.sha(__file__),
        limitation='Retired near-call sampling estimates dynamic call frequency, not prefetch accuracy or accepted fills. '
                    'Zero samples do not imply zero executions; retain an uncertainty floor when using costs. '
                    'Request counts bracket perf startup/teardown. Captures are diagnostic, not E2E trials.'))
    assert valid,'Production near-call sample IP validation failed; do not use weights'


def run(parent):
    assert (parent/'callpath/complete.json').exists()
    root=parent/'call_frequency';root.mkdir(exist_ok=False);b.space(root)
    b.save(root/'protocol.json',dict(source_sha256=b.sha(__file__),seed=80501,event=EVENT,
        purpose='Price selected call sites by dynamic frequency, independently of miss-conditioned traces.',
        source='https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/'))
    runner="import sys;sys.path.insert(0,'/home/hnpark2/prefetchit/profiling/.venv/lib/python3.12/site-packages');import pytest;raise SystemExit(pytest.main(sys.argv[1:]))"
    b.run(['python3','-c',runner,'-q',b.REPO/'llvm_prefetchit/tests/test_call_cost_selector.py'],root/'selector_tests.log')
    preflight(root/'preflight')
    reference=parent/'backend/reference/mongod'
    services=json.loads((parent/'callpath/protocol.json').read_text())['training_services']
    base=json.loads((parent/'confirmation_spec.json').read_text())['arms']['base']['overrides']
    manifest=root/'capture_spec.json'
    b.save(manifest,dict(out=str(root/'capture'),reference=str(reference),overrides=base,
        seed=80501,services=services,capture_kind='calls'))
    h.platform(root/'capture',['python3',Path(__file__).with_name('backend_prefetch.py'),'profile',manifest])
    analyze(root/'capture',reference,services)
    b.save(root/'complete.json',dict(valid=True,summary=str(root/'capture/frequency_summary.json')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent',type=Path);a=p.parse_args();run(a.parent)
