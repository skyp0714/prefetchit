"""Check decoding against real ELF bytes, including an unresolved register hint."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts/class_b'
sys.path.insert(0,str(SCRIPTS))
import dense_cause_analysis as a
import dense_causes as d


def test_real_elf_prefetch_targets_and_branch_kinds(tmp_path):
    source=tmp_path/'probe.s'
    source.write_text('''.text
.global _start
_start:
 prefetcht1 destination(%rip)
 lea destination(%rip),%rax
 prefetcht1 64(%rax)
 prefetcht1 (%r11)
 call destination
 call *%rax
 jz destination
 jmp *%rax
.balign 64
destination:
 ret
 .fill 128,1,0x90
''')
    subprocess.run(['as',str(source),'-o',str(tmp_path/'probe.o')],check=True)
    subprocess.run(['ld','-o',str(tmp_path/'probe'),str(tmp_path/'probe.o')],check=True)
    code=a.Code(tmp_path/'probe')
    destination=next(va for va,row in code.instructions.items() if row[1]=='ret')
    assert sorted(code.raw_targets.values())==[destination,destination+64]
    assert len(code.unresolved)==1
    first=min(code.instructions);call=next(va for va,row in code.instructions.items() if a.category(row[1])=='direct_call')
    assert code.straight(first,call)
    assert not code.straight(first,destination)
    classes=[a.category(row[1]) for row in code.instructions.values()]
    assert all(x in classes for x in ['direct_call','indirect_call','conditional_branch','indirect_jump','return'])


def test_counter_csv_detects_multiplexing(tmp_path):
    p=tmp_path/'stats.csv'
    p.write_text('1000,,instructions:u,10000,100.00,,\n2000,,cycles:u,10000,100.00,,\n50,,FE_L2,docker/test,5000,50.00,,\n')
    result=d.counters(p)
    assert not result['fully_scheduled']
    assert result['counters']['FE_L2']==50
    assert result['scheduled_pct']['FE_L2']==50


def test_branch_stack_distinguishes_prediction_flags():
    line=' 42 401010 (/custom/Probe) 0x401002 (/custom/Probe)/0x401010 (/custom/Probe)/M/-/-/37/CALL/ 0x401000 (/custom/Probe)/0x401001 (/custom/Probe)/P/-/-/20/COND/\n'
    assert a.HEADER.match(line)[2]=='401010'
    edges=a.EDGE.findall(line)
    assert len(edges)==2
    assert edges[0][4:]==('M','37','CALL')
    assert edges[1][4]=='P'


def test_platform_interrupt_allows_wrapper_cleanup(tmp_path):
    import os
    import signal
    import time
    wrapper=tmp_path/'run_platform.py'
    wrapper.write_text('''import argparse,json,signal,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path);p.add_argument('--cpus');p.add_argument('command',nargs='*');a=p.parse_args()
a.out.mkdir();(a.out/'ready').write_text('ready')
def stop(*args):raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,stop)
try:time.sleep(30)
finally:(a.out/'restored').write_text('restored')
''')
    controller=tmp_path/'controller.py'
    controller.write_text(f'''import sys
from pathlib import Path
sys.path.insert(0,{str(SCRIPTS)!r})
import fullset as h
h.HARNESS=Path({str(tmp_path)!r})
h.c.space=lambda:None
h.platform(Path({str(tmp_path/'trial')!r}),['true'])
''')
    with (tmp_path/'controller.log').open('w') as log:
        process=subprocess.Popen([sys.executable,str(controller)],stdout=log,stderr=log,start_new_session=True)
        try:
            deadline=time.monotonic()+8
            while not (tmp_path/'trial_platform/ready').exists():
                assert process.poll() is None
                assert time.monotonic()<deadline
                time.sleep(.02)
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=8)!=0
            assert (tmp_path/'trial_platform/restored').read_text()=='restored'
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
