/* Test a warm versus explicitly cold hint line after a real same-CPU
 * blocking handoff. The helper is excluded by perf --no-inherit. */
#define _GNU_SOURCE
#include <immintrin.h>
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#ifndef HINT
#define HINT 0
#endif
#if HINT == 0
#define HINT_ASM ".byte 0x0f,0x1f,0x80,0,0,0,0\n"
#elif HINT == 1
#define HINT_ASM ".byte 0x0f,0x18,0x3d\n.long resume_target-.-4\n"
#elif HINT == 2
#define HINT_ASM ".byte 0x0f,0x18,0x15\n.long resume_target-.-4\n"
#else
#error Invalid HINT
#endif
extern void resume_hint(void),resume_target(void);
__asm__(".text\n.p2align 12\n.globl resume_hint\nresume_hint:\n" HINT_ASM "ret\n"
        ".p2align 12\n.space 4096,0x90\n.globl resume_target\nresume_target:\nret\n.space 4095,0x90\n");
static inline uint64_t stamp(void) {
    unsigned aux;_mm_lfence();uint64_t t=__rdtscp(&aux);_mm_lfence();return t;
}
int main(int argc,char **argv) {
    if(argc!=6)return 2;
    unsigned iterations=atoi(argv[2]),handoff=atoi(argv[3]),cold_hint=atoi(argv[4]),lead=atoi(argv[5]);
    if(iterations<1000 || handoff>1 || cold_hint>1 || lead>100000)return 2;
    int request[2],response[2],status=0;pid_t helper=-1;char byte=1;
    if(handoff) {
        if(pipe(request) || pipe(response))return 3;
        helper=fork();if(helper<0)return 3;
        if(!helper) {
            close(request[1]);close(response[0]);
            while(read(request[0],&byte,1)==1)if(write(response[1],&byte,1)!=1)_exit(4);
            close(request[0]);close(response[1]);_exit(0);
        }
        close(request[0]);close(response[1]);
    }
    uint64_t total=0,x=1;struct rusage before,after;
    resume_hint();resume_target();getrusage(RUSAGE_SELF,&before);
    for(unsigned i=0;i<iterations;i++) {
        _mm_clflush((const void *)resume_target);
        if(cold_hint)_mm_clflush((const void *)resume_hint);
        _mm_mfence();unsigned a,b,c,d;__cpuid(0,a,b,c,d);
        if(handoff) {
            if(write(request[1],&byte,1)!=1 || read(response[0],&byte,1)!=1)return 4;
        }
        resume_hint();
        for(unsigned j=0;j<lead;j++)__asm__ volatile("imul $3,%0,%0":"+r"(x));
        uint64_t start=stamp();resume_target();total+=stamp()-start;
    }
    getrusage(RUSAGE_SELF,&after);
    if(handoff) {
        close(request[1]);close(response[0]);
        if(waitpid(helper,&status,0)!=helper || !WIFEXITED(status) || WEXITSTATUS(status))return 5;
    }
    printf("{\"kind\":\"%s\",\"iterations\":%u,\"handoff\":%u,\"cold_hint\":%u,\"lead_imul\":%u,\"mean_call_tsc\":%.5f,\"voluntary_switches\":%ld,\"involuntary_switches\":%ld,\"sink\":%llu}\n",
        argv[1],iterations,handoff,cold_hint,lead,(double)total/iterations,
        after.ru_nvcsw-before.ru_nvcsw,after.ru_nivcsw-before.ru_nivcsw,(unsigned long long)x);
    return 0;
}
