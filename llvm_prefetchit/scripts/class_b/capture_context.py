#!/usr/bin/env python3
"""Capture two baseline PT windows plus actual syscall-return IPs, then decode offline."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import social_headroom as h


def capture(stack,dest):
    c=h.c
    c.space()
    pid=stack.states[h.NAME]['State']['Pid']
    group=str(Path(c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
    syscall_data=dest.with_name(dest.name+'.syscall.data')
    command=['perf','record','--no-buildid-cache','--clockid','mono',
             '-e','raw_syscalls:sys_exit','--user-regs=ip','-m','4M',
             '-a','-C','32-39','-G',group,'-o',str(syscall_data),'--','sleep','2']
    c.save(dest.with_name(dest.name+'.syscall.command.json'),command)
    with dest.with_name(dest.name+'.syscall.log').open('w') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        try:
            time.sleep(.2)
            assert child.poll() is None
            # Uses /proc/PID mappings and vDSO snapshot; baseline binary hash is checked.
            h.trace_media.capture(stack,h.SERVICE,dest)
            assert child.wait(timeout=10)==0
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=10)
    text=dest.with_name(dest.name+'.syscall.log').read_text()
    assert 'lost' not in text.lower() and 'truncated' not in text.lower(),text
    return syscall_data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--trace-out',type=Path,required=True)
    p.add_argument('--pool',type=int,required=True)
    p.add_argument('--rate',type=int,required=True)
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    a.trace_out.mkdir(parents=True,exist_ok=False)
    stack=None
    client=None
    outputs=[]
    try:
        binary=h.c.S/'social_build/usertimeline/base'/h.EXE
        stack=h.start_stack(a.out,binary,a.pool,False)
        client=h.load(a.out/'load',a.rate,7103,100)
        start=time.monotonic()
        for name,at in [('training',55),('validation',75)]:
            time.sleep(max(0,start+at-time.monotonic()))
            assert client.poll() is None
            dest=a.trace_out/name
            outputs.append((dest,capture(stack,dest)))
            if name=='training':
                time.sleep(max(0,start+62-time.monotonic()))
                pid=stack.states[h.NAME]['State']['Pid']
                group=str(Path(h.c.cpu(pid)['path']).parent.relative_to('/sys/fs/cgroup'))
                command=['perf','record','--no-buildid-cache','-e',
                         'cpu/event=0xc6,umask=0x03,config1=0x13/upp','-c','257',
                         '-m','4M','-a','-C','32-39','-G',group,
                         '-o',str(a.trace_out/'misses.data'),'--','sleep','10']
                h.c.run(command,a.trace_out/'misses_record.log')
                message=(a.trace_out/'misses_record.log').read_text().lower()
                assert 'lost' not in message and 'truncated' not in message,message
        rc=client.wait(timeout=90)
        client=None
        info=json.loads((a.out/'load/load.json').read_text())
        assert rc==0 and not info['steady_errors'] and not info['steady_drops']
        stack.check()
    finally:
        h.c.stop(client)
        if stack is not None:
            stack.close()
    for dest,syscalls in outputs:
        h.trace_media.decode(dest)
        # Preserve nanosecond diagnostics. Clock identity between independent
        # recorders is NOT assumed; training verifies the first return opcode.
        cmd=json.loads((dest/'decode_command.json').read_text())+['--ns']
        h.c.save(dest/'context_branch_decode_command.json',cmd)
        with (dest/'branches.txt').open('w') as f,(dest/'context_branch_decode.err').open('w') as err:
            subprocess.run(cmd,stdout=f,stderr=err,check=True)
        h.c.save(dest/'context_branch_decode.json',dict(sha256=h.c.sha(dest/'branches.txt'),
            clock='PT default clock; syscall recorder CLOCK_MONOTONIC; cross-recorder identity unverified',
            precision='nanoseconds',reason='Diagnostic only; do not widen time joins to infer wake context'))
        cmd=['perf','script','--ns','-i',str(syscalls),'-F','tid,time,event,trace,uregs']
        h.c.save(dest/'syscall_decode_command.json',cmd)
        with (dest/'syscall_context.txt').open('w') as f,(dest/'syscall_decode.err').open('w') as err:
            subprocess.run(cmd,stdout=f,stderr=err,check=True)
    with (a.trace_out/'misses.txt').open('w') as f,(a.trace_out/'misses_decode.err').open('w') as err:
        subprocess.run(['perf','script','--ns','-i',str(a.trace_out/'misses.data'),
                        '-F','tid,time,ip'],stdout=f,stderr=err,check=True)
    h.c.save(a.out/'completed.json',dict(outputs=[str(x[0]) for x in outputs],
        load=info,description='Two temporally separate PT + syscall-return-IP captures, same baseline process/load'))
    h.compact(a.out)


if __name__=='__main__':main()
