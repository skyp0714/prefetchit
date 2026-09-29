/* Same-address follow-up to prefetch_probe.c. Build HINT=0/1/2/3 as
 * NOP/IT0/IT1/T1: only the seven hint bytes may differ between executables.
 * Decode-pad variants probe frontend residency without flushing the hint.
 */
#include <immintrin.h>
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef HINT
#define HINT 0
#endif
#if HINT == 0
#define HINT_ASM ".byte 0x0f,0x1f,0x80,0,0,0,0\n"
#elif HINT == 1
#define HINT_ASM ".byte 0x0f,0x18,0x3d\n.long cold_target-.-4\n"
#elif HINT == 2
#define HINT_ASM ".byte 0x0f,0x18,0x35\n.long cold_target-.-4\n"
#elif HINT == 3
#define HINT_ASM ".byte 0x0f,0x18,0x15\n.long cold_target-.-4\n"
#else
#error Invalid HINT
#endif
extern void cold_target(void),hint_site(void),decode_pad(void),icache_pad(void);
__asm__(".text\n.p2align 12\n.globl hint_site\nhint_site:\n" HINT_ASM "ret\n"
    ".p2align 12\n.space 4096,0x90\n.globl cold_target\ncold_target:\nret\n.space 8191,0x90\n"
    ".p2align 12\n.globl decode_pad\ndecode_pad:\n.rept 8192\nnop\n.endr\nret\n"
    ".p2align 12\n.globl icache_pad\nicache_pad:\n.rept 65536\nnop\n.endr\nret\n");
static inline uint64_t stamp(void) {
    unsigned aux;_mm_lfence();uint64_t t=__rdtscp(&aux);_mm_lfence();return t;
}
int main(int argc,char **argv) {
    if(argc!=6)return 2;
    unsigned lead=atoi(argv[2]),demand=atoi(argv[3]),flush=atoi(argv[4]),iterations=atoi(argv[5]);
    if(!iterations || demand>1 || flush<2 || flush>5 || lead>100000)return 2;
    uint64_t total=0,x=1;
    for(unsigned i=0;i<iterations;i++) {
        _mm_clflush((const void *)cold_target);
        if(flush==3)_mm_clflush((const void *)hint_site);
        _mm_mfence();
        if(flush==4)decode_pad();
        if(flush==5)icache_pad();
        unsigned a,b,c,d;__cpuid(0,a,b,c,d);
        hint_site();
        for(unsigned j=0;j<lead;j++)__asm__ volatile("imul $3,%0,%0":"+r"(x));
        if(demand){uint64_t start=stamp();cold_target();total+=stamp()-start;}
        else _mm_lfence();
    }
    printf("{\"kind\":\"%s\",\"lead_iterations\":%u,\"demand\":%u,\"flush\":%u,\"iterations\":%u,\"mean_call_tsc\":%.5f,\"sink\":%llu}\n",
        argv[1],lead,demand,flush,iterations,(double)total/iterations,(unsigned long long)x);
    return 0;
}
