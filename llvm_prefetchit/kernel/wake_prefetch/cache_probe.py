#!/usr/bin/env python3
"""Synthetic cache-warming diagnostic, NEVER an application speedup benchmark.

Flush one unused executable line, sleep, then time a data load from that line.
Compare kernel NOP/T1 with a user-space T1 positive control. This checks whether
the pinned physical alias warms a cache line; it does not test ITLB/BPU/L1I state.
Run only after real-service timing ends, through the fixed-platform wrapper.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess

import control

SOURCE=r'''
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <x86intrin.h>
extern unsigned char cold_line[];
__asm__(".pushsection .text\n.p2align 12\n.globl cold_line\n"
        ".type cold_line,@function\ncold_line:\n.fill 64,1,0x90\nret\n"
        ".size cold_line,.-cold_line\n.popsection\n");
static unsigned long long samples[500];
int main(int argc,char **argv) {
    int positive=argc>1 && atoi(argv[1]);
    struct timespec req={.tv_sec=0,.tv_nsec=1000000};
    puts("ready");fflush(stdout);if(getchar()!='g')return 2;
    for(int i=0;i<500;i++) {
        __asm__ volatile("clflush (%0)\n\tmfence"::"r"(cold_line):"memory");
        if(positive)__asm__ volatile("prefetcht1 (%0)"::"r"(cold_line):"memory");
        if(syscall(SYS_clock_nanosleep,CLOCK_MONOTONIC,0,&req,0))return 3;
        unsigned a,b;
        _mm_lfence();unsigned long long start=__rdtscp(&a);_mm_lfence();
        unsigned char value=*(volatile unsigned char*)cold_line;
        _mm_lfence();unsigned long long end=__rdtscp(&b);_mm_lfence();
        if(value!=0x90 || a!=b)return 4;
        samples[i]=end-start;
    }
    for(int i=0;i<500;i++)printf("%llu\n",samples[i]);
    return 0;
}
'''


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--cpu',type=int,default=42)
    a=p.parse_args()
    assert os.geteuid()==0 and not a.out.exists()
    assert not Path('/sys/module/wake_prefetch').exists()
    assert shutil.disk_usage(a.out.parent).free>1024**3
    a.out.mkdir(parents=True)
    source=a.out/'helper.c';binary=a.out/'helper';source.write_text(SOURCE)
    module=Path(__file__).resolve().parent/'wake_prefetch.ko'
    result=dict(kind='Synthetic cache-fill diagnostic, excluded from application performance results',
                cpu=a.cpu,iterations=500,rows=[],module_sha256=sha(module),source_sha256=sha(source),
                timing_unit='Invariant TSC ticks, not PMU core cycles',
                limitations='Timed data load detects cache warmth, not L1 instruction-cache, ITLB or BPU restoration.')
    proc=None;fd=None;loaded=False
    try:
        command=['cc','-O2','-fPIE','-pie',str(source),'-o',str(binary)]
        result['compile_command']=command;subprocess.run(command,check=True)
        (a.out/'helper_disassembly.txt').write_text(
            subprocess.check_output(['objdump','-d',str(binary)],text=True))
        symbols=subprocess.check_output(['nm','-n',str(binary)],text=True).splitlines()
        va=next(int(s.split()[0],16) for s in symbols if s.split()[-1]=='cold_line')
        assert not va%64
        plan=dict(profiles=[dict(syscall_nr=230,targets=[dict(path=str(binary.resolve()),
                            sha256=sha(binary),elf_va=hex(va))])])
        result['plan']=plan
        subprocess.run(['insmod',str(module)],check=True);loaded=True
        modes=[('kernel_nop',0,0),('kernel_t1',1,0),('user_t1_positive',0,1)]
        for block in range(3):
            for name,mode,positive in modes[block:]+modes[:block]:
                assert shutil.disk_usage(a.out).free>1024**3
                command=['taskset','-c',str(a.cpu),str(binary.resolve()),str(positive)]
                proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                assert proc.stdout.readline().strip()=='ready'
                profiles,audit=control.resolve(plan,proc.pid)
                fd=os.open('/dev/wake_prefetch',os.O_RDWR|os.O_CLOEXEC)
                fcntl.ioctl(fd,control.CONFIG_IOCTL,control.pack_config(proc.pid,mode,profiles),True)
                stdout,stderr=proc.communicate('g\n',timeout=15)
                assert proc.returncode==0,stderr
                values=sorted(map(int,stdout.splitlines()));assert len(values)==500
                stats=control.stats(fd);assert stats['matched_switches']>=450,stats
                result['rows'].append(dict(block=block,mode=name,command=command,stats=stats,
                    mapping_audit=audit,median_cycles=statistics.median(values),p10_cycles=values[50],
                    p90_cycles=values[450],min_cycles=values[0],max_cycles=values[-1],sorted_cycles=values))
                proc=None;os.close(fd);fd=None
        means={name:statistics.mean(r['median_cycles'] for r in result['rows'] if r['mode']==name) for name,_,_ in modes}
        result.update(mean_of_medians=means,protocol_passed=True,
                      kernel_warming_observed=means['kernel_t1']<.7*means['kernel_nop'],
                      positive_control_warming_observed=means['user_t1_positive']<.7*means['kernel_nop'])
    except BaseException as error:
        result.update(protocol_passed=False,error=repr(error));raise
    finally:
        if fd is not None:os.close(fd)
        if proc is not None and proc.poll() is None:proc.terminate();proc.wait(timeout=5)
        try:
            if loaded:subprocess.run(['rmmod','wake_prefetch'],check=True)
        finally:
            result['module_unloaded']=not Path('/sys/module/wake_prefetch').exists()
            before=shutil.disk_usage(a.out).free
            removed=[]
            if binary.exists():
                removed.append(dict(path=str(binary),bytes=binary.stat().st_size,sha256=sha(binary)));binary.unlink()
            result['cleanup']=dict(removed=removed,free_before=before,free_after=shutil.disk_usage(a.out).free)
            (a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in {
        'mean_of_medians','protocol_passed','kernel_warming_observed','positive_control_warming_observed','module_unloaded'}}))


if __name__=='__main__':main()
