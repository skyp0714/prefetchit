"""Native multithread pause/patch/resume and rollback before crossover timing."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from live_hints import LiveHints,transition
from lean_plan import sections

def test_native_threads_and_rollback(tmp_path):
    source=tmp_path/'probe.c'
    source.write_text(r'''
#include <pthread.h>
#include <stdio.h>
#include <unistd.h>
__attribute__((noinline)) int leaf(int x){volatile int v=x;return v*4;}
__attribute__((noinline)) void hint(void){__asm__ volatile(".globl hint_site\nhint_site:\nprefetcht1 leaf(%%rip)":::"memory");}
void *worker(void *unused){for(;;){hint();if(leaf(7)!=28)_exit(9);usleep(1000);}return 0;}
int main(void){pthread_t t;pthread_create(&t,0,worker,0);puts("ready");fflush(stdout);worker(0);}
''')
    t1=tmp_path/'t1';subprocess.run(['gcc','-O2','-pthread','-fno-pie','-no-pie',str(source),'-o',str(t1)],check=True)
    symbols={p[2]:int(p[0],16) for line in subprocess.check_output(['nm','-n',str(t1)],text=True).splitlines() if len(p:=line.split())==3}
    data=t1.read_bytes();sec=next(x for x in sections(data) if x['va']<=symbols['hint_site']<x['va']+x['size'] and x['flags']&4)
    off=sec['offset']+symbols['hint_site']-sec['va'];assert data[off:off+3]==b'\x0f\x18\x15'
    nop=tmp_path/'nop';modified=bytearray(data);modified[off:off+7]=b'\x0f\x1f\x80\0\0\0\0';nop.write_bytes(modified);nop.chmod(0o755)
    it0=tmp_path/'it0';modified=bytearray(data);modified[off+2]=0x3d;it0.write_bytes(modified);it0.chmod(0o755)
    child=subprocess.Popen([str(nop)],stdout=subprocess.PIPE,text=True);im=None
    try:
        assert child.stdout.readline().strip()=='ready'
        with pytest.raises(AssertionError):LiveHints(child.pid,t1,{'t1':t1},[symbols['hint_site']])
        im=LiveHints(child.pid,nop,{'t1':t1,'it0':it0},[symbols['hint_site']])
        cpu=min(os.sched_getaffinity(0))
        for kind in ['nop','t1','it0','nop']:
            result=transition({'probe':im},kind,patch_cpu=cpu)
            assert result['verified'] and child.poll() is None
            im.verify(kind)
        original=im.write
        def interrupted(kind):
            original(kind)
            if kind=='t1':raise RuntimeError('Injected after-write interruption')
        im.write=interrupted
        with pytest.raises(RuntimeError,match='Injected'):transition({'probe':im},'t1',patch_cpu=cpu)
        im.verify('nop');assert im.kind=='nop' and child.poll() is None
        assert nop.read_bytes()[off:off+7]==b'\x0f\x1f\x80\0\0\0\0','Original executable file must remain unchanged'
    finally:
        if im is not None:im.close()
        child.kill();child.wait(timeout=5)
