/* A known split instruction: its first cache line remains warm while only
 * the continuation line is flushed. All four variants have identical text
 * addresses and differ only in the two seven-byte hint slots. */
#include <immintrin.h>
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef HINT
#define HINT 0
#endif
#define NOP7 ".byte 0x0f,0x1f,0x80,0,0,0,0\n"
#if HINT == 1 || HINT == 3
#define FIRST ".byte 0x0f,0x18,0x15\n.long split_target-.-4\n"
#else
#define FIRST NOP7
#endif
#if HINT == 2 || HINT == 3
#define SECOND ".byte 0x0f,0x18,0x15\n.long split_next-.-4\n"
#else
#define SECOND NOP7
#endif
extern uint64_t split_target(void);
extern void split_hints(void);
extern const unsigned char split_line[],split_next[];
__asm__(".text\n.p2align 12\n.globl split_hints\nsplit_hints:\n"
        FIRST SECOND "ret\n.p2align 12\n.globl split_line\nsplit_line:\n"
        ".space 61,0x90\n.globl split_target\nsplit_target:\n"
        /* movabs $0x1122334455667788,%rax starts at offset 61, length 10. */
        ".byte 0x48,0xb8,0x88\n.globl split_next\nsplit_next:\n"
        ".byte 0x77,0x66,0x55,0x44,0x33,0x22,0x11\nret\n.space 4096,0x90\n");
static inline uint64_t stamp(void) {
    unsigned aux;_mm_lfence();uint64_t t=__rdtscp(&aux);_mm_lfence();return t;
}
int main(int argc,char **argv) {
    if(argc!=4)return 2;
    unsigned iterations=atoi(argv[2]),lead=atoi(argv[3]);
    if(iterations<1000 || lead>100000)return 2;
    uint64_t total=0,x=1;
    for(unsigned i=0;i<iterations;i++) {
        x+=(unsigned)*(const volatile unsigned char *)split_line;
        _mm_clflush(split_next);_mm_mfence();
        unsigned a,b,c,d;__cpuid(0,a,b,c,d);
        split_hints();
        for(unsigned j=0;j<lead;j++)__asm__ volatile("imul $3,%0,%0":"+r"(x));
        uint64_t start=stamp(),value=split_target();total+=stamp()-start;
        if(value!=UINT64_C(0x1122334455667788))return 3;
    }
    printf("{\"kind\":\"%s\",\"iterations\":%u,\"lead_imul\":%u,\"mean_call_tsc\":%.5f,\"sink\":%llu}\n",
           argv[1],iterations,lead,(double)total/iterations,(unsigned long long)x);
    return 0;
}
