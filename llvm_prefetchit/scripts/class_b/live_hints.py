#!/usr/bin/env python3
"""Change only audited hint slots in stopped, experiment-owned processes.

The caller owns the processes and must tear them down on an unrecoverable
rollback error. No executable files are changed. Every process identity,
original instruction, write and rollback is checked. Transitions are excluded
from measurement; a fresh warmup follows every transition.
"""
import os
from pathlib import Path
import signal
import time
import re
from lean_plan import sections
from dense_cause_analysis import mapping_bias

def identity(pid):
    text=Path(f'/proc/{pid}/stat').read_text()
    start=text[text.rindex(')')+2:].split()[19]
    st=Path(f'/proc/{pid}/exe').stat()
    return (start,st.st_dev,st.st_ino)

class LiveHints:
    def __init__(self,pid,control,variants,sites):
        self.pid=pid;self.identity=identity(pid);st=control.stat()
        assert self.identity[1:]==(st.st_dev,st.st_ino),'Process must execute the specified control inode'
        self.kind='nop';self.data={'nop':control.read_bytes(),**{k:p.read_bytes() for k,p in variants.items()}}
        table=sections(self.data['nop']);executable=[s for s in table if s['flags']&4 and s['type']==1]
        name=os.readlink(f'/proc/{pid}/exe')
        bias=mapping_bias(Path(f'/proc/{pid}/maps').read_text(),re.compile('^'+re.escape(name)+'$'),
                          [(s['va'],s['offset'],s['size']) for s in executable])
        assert bias is not None
        self.slots=[]
        for site in sorted(set(sites)):
            sec=next(s for s in executable if s['va']<=site and site+7<=s['va']+s['size'])
            off=sec['offset']+site-sec['va']
            raw={k:d[off:off+7] for k,d in self.data.items()}
            assert raw['nop']==b'\x0f\x1f\x80\0\0\0\0'
            assert all(v[:3] in (b'\x0f\x1f\x80',b'\x0f\x18\x15',b'\x0f\x18\x3d',b'\x0f\x18\x35') for v in raw.values())
            self.slots.append((site+bias,off,raw))
        assert self.slots
        # Reject any variant that also changes program instructions elsewhere.
        for kind,data in self.data.items():
            normalized=bytearray(data)
            assert sections(data)==table
            for address,off,raw in self.slots:normalized[off:off+7]=raw['nop']
            for sec in executable:
                start=sec['offset'];end=start+sec['size']
                assert normalized[start:end]==self.data['nop'][start:end]
        self.fd=os.open(f'/proc/{pid}/mem',os.O_RDWR|os.O_CLOEXEC)
        try:self.verify('nop')
        except BaseException:os.close(self.fd);raise

    def verify(self,kind):
        assert identity(self.pid)==self.identity,'PID or executable identity changed'
        for address,off,raw in self.slots:
            assert os.pread(self.fd,7,address)==raw[kind],f'Unexpected code at {address:x}'

    def write(self,kind):
        assert identity(self.pid)==self.identity
        for address,off,raw in self.slots:assert os.pwrite(self.fd,raw[kind],address)==7
        self.verify(kind)

    def stopped(self):
        try:
            tasks=list(Path(f'/proc/{self.pid}/task').iterdir())
            return bool(tasks) and all(re.search(r'^State:\s+T\b',(p/'status').read_text(),re.M) for p in tasks)
        except FileNotFoundError:return False  # a short-lived worker exited during the snapshot

    def close(self):os.close(self.fd)

def transition(images,kind,patch_cpu=32):
    previous={key:im.kind for key,im in images.items()};stopped=[];safe=True
    affinity=os.sched_getaffinity(0);start=time.monotonic()
    try:
        os.sched_setaffinity(0,{patch_cpu})  # COW pages local to the measurement NUMA node
        for im in images.values():
            im.verify(im.kind);assert not im.stopped(),'Unexpected externally stopped process'
            os.kill(im.pid,signal.SIGSTOP);stopped.append(im)
        deadline=time.monotonic()+5
        while not all(im.stopped() for im in stopped):
            if time.monotonic()>deadline:raise RuntimeError('Process group stop timed out')
            time.sleep(.001)
        try:
            for im in images.values():im.write(kind)
        except BaseException:
            for key,im in images.items():
                try:im.write(previous[key])
                except BaseException:safe=False
            raise
        for im in images.values():im.kind=kind
        return dict(kind=kind,previous=previous,pids={k:im.pid for k,im in images.items()},
                    hint_slots={k:len(im.slots) for k,im in images.items()},paused_wall_s=time.monotonic()-start,
                    verified=True,patch_cpu=patch_cpu)
    finally:
        if safe:
            for im in stopped:
                try:os.kill(im.pid,signal.SIGCONT)
                except ProcessLookupError:pass
        os.sched_setaffinity(0,affinity)
