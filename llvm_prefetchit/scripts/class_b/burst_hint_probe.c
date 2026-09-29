#define _GNU_SOURCE
#include <immintrin.h>
#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
extern uint64_t burst_hints(uint64_t);
#define DECLARE(N) extern unsigned burst_target_##N(void);
DECLARE(0) DECLARE(1) DECLARE(2) DECLARE(3)
DECLARE(4) DECLARE(5) DECLARE(6) DECLARE(7)
static unsigned (*const targets[])(void)={burst_target_0,burst_target_1,burst_target_2,burst_target_3,
    burst_target_4,burst_target_5,burst_target_6,burst_target_7};
static inline uint64_t stamp(void) {
    unsigned aux;_mm_lfence();uint64_t t=__rdtscp(&aux);_mm_lfence();return t;
}
int main(int argc,char **argv) {
    if(argc!=5)return 2;
    unsigned iterations=atoi(argv[2]),handoff=atoi(argv[3]),dependent=atoi(argv[4]);
    if(iterations<1000 || handoff>1 || dependent>1)return 2;
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
    uint64_t total=0,body=0,per_target[8]={0},counts[8]={0},state=0x517cc1b727220a95ULL;
    struct rusage before,after;
    burst_hints(1);for(unsigned j=0;j<8;j++)if(targets[j]()!=j)return 6;
    getrusage(RUSAGE_SELF,&before);
    for(unsigned i=0;i<iterations;i++) {
        for(unsigned j=0;j<8;j++)_mm_clflush((const void *)targets[j]);
        _mm_mfence();unsigned a,b,c,d;__cpuid(0,a,b,c,d);
        if(handoff && (write(request[1],&byte,1)!=1 || read(response[0],&byte,1)!=1))return 4;
        state^=state<<13;state^=state>>7;state^=state<<17;
        uint64_t start=stamp();uint64_t choice=burst_hints(state);
        unsigned first=dependent?(choice&7):0,last=dependent?first+1:8;
        for(unsigned j=first;j<last;j++) {
            uint64_t at=stamp();unsigned result=targets[j]();uint64_t spent=stamp()-at;
            if(result!=j)return 6;
            per_target[j]+=spent;counts[j]++;total+=spent;
        }
        body+=stamp()-start;
    }
    getrusage(RUSAGE_SELF,&after);
    if(handoff) {
        close(request[1]);close(response[0]);
        if(waitpid(helper,&status,0)!=helper || !WIFEXITED(status) || WEXITSTATUS(status))return 5;
    }
    printf("{\"kind\":\"%s\",\"iterations\":%u,\"handoff\":%u,\"dependent\":%u,\"mean_calls_tsc\":%.5f,\"mean_body_tsc\":%.5f,\"voluntary_switches\":%ld,\"involuntary_switches\":%ld,\"target_tsc\":[",
        argv[1],iterations,handoff,dependent,(double)total/iterations,(double)body/iterations,
        after.ru_nvcsw-before.ru_nvcsw,after.ru_nivcsw-before.ru_nivcsw);
    for(unsigned j=0;j<8;j++)printf("%s%.5f",j?",":"",counts[j]?(double)per_target[j]/counts[j]:0.);
    printf("],\"target_counts\":[");
    for(unsigned j=0;j<8;j++)printf("%s%llu",j?",":"",(unsigned long long)counts[j]);
    puts("]}");return 0;
}
