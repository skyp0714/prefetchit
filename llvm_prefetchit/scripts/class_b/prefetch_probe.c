/* Causal PMU calibration, not a service performance benchmark.
 * A single 64-byte code line is flushed before every hint. The no-call mode
 * separates hint-generated code traffic from demand instruction fetches.
 * All hints are RIP-relative and have identical seven-byte instruction size.
 */
#include <immintrin.h>
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern void cold_target(void), hint_nop(void), hint_it0(void), hint_it1(void), hint_t1(void);
__asm__(
    ".text\n.p2align 6\n"
    ".globl hint_nop\nhint_nop:\n.byte 0x0f,0x1f,0x80,0,0,0,0\nret\n"
    ".p2align 6\n.globl hint_it0\nhint_it0:\n.byte 0x0f,0x18,0x3d\n.long cold_target-.-4\nret\n"
    ".p2align 6\n.globl hint_it1\nhint_it1:\n.byte 0x0f,0x18,0x35\n.long cold_target-.-4\nret\n"
    ".p2align 6\n.globl hint_t1\nhint_t1:\n.byte 0x0f,0x18,0x15\n.long cold_target-.-4\nret\n"
    ".p2align 12\n.space 4096,0x90\n.globl cold_target\ncold_target:\nret\n.space 8191,0x90\n");

static inline uint64_t stamp(void) {
    unsigned aux;
    _mm_lfence();
    uint64_t t=__rdtscp(&aux);
    _mm_lfence();
    return t;
}
int main(int argc, char **argv) {
    if(argc!=6) return 2;
    void (*hint)(void)=NULL;
    if(!strcmp(argv[1],"nop")) hint=hint_nop;
    if(!strcmp(argv[1],"it0")) hint=hint_it0;
    if(!strcmp(argv[1],"it1")) hint=hint_it1;
    if(!strcmp(argv[1],"t1")) hint=hint_t1;
    if(!hint) return 2;
    unsigned lead=atoi(argv[2]), demand=atoi(argv[3]), flush=atoi(argv[4]);
    unsigned iterations=atoi(argv[5]);
    if(!iterations || demand>1 || flush>3 || lead>100000) return 2;
    uint64_t total=0, x=1;
    for(unsigned i=0;i<iterations;i++) {
        if(flush) _mm_clflush((const void *)cold_target);
        if(flush==3) _mm_clflush((const void *)hint);
        _mm_mfence();
        /* PREFETCHI is unordered with fences/CLFLUSH, but ordered with CPUID.
         * Mode 3 also invalidates the hint line to test front-end residency.
         */
        if(flush>=2) { unsigned a,b,c,d; __cpuid(0,a,b,c,d); }
        hint();
        for(unsigned j=0;j<lead;j++) __asm__ volatile("imul $3,%0,%0":"+r"(x));
        if(demand) {
            uint64_t start=stamp();
            cold_target();
            total+=stamp()-start;
        } else _mm_lfence();
    }
    printf("{\"kind\":\"%s\",\"lead_iterations\":%u,\"demand\":%u,\"flush\":%u,\"iterations\":%u,\"mean_call_tsc\":%.5f,\"sink\":%llu}\n",
           argv[1],lead,demand,flush,iterations,(double)total/iterations,(unsigned long long)x);
    return 0;
}
