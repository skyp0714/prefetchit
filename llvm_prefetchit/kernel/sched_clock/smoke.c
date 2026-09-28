#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
#include <x86intrin.h>

static volatile uint64_t *slots;
static uint64_t expected_begin[3], expected_end[3] = {10,20,40};
static void *check(void *unused)
{
    uint64_t last = 0, resets = 0;
    for (int i=0; i<40; i++) {
        usleep(1000);
        unsigned aux; uint64_t now=__rdtscp(&aux);
        volatile uint64_t *s=slots+(aux&4095)*8;
        uint64_t start=s[3], a=s[0], b=s[1], c=s[2];
        assert(start && now>=start && a>start && b>a && c>b);
        assert(s[7] == 2);
        for (int j=0;j<3;j++) {
            uint64_t end_delta=s[j]-start, begin_delta=s[j+4]-start;
            // Integer conversion in the module can round down by one tick.
            uint64_t end_scaled=end_delta*expected_end[0];
            uint64_t end_wanted=(a-start)*expected_end[j];
            assert(llabs((long long)end_scaled-(long long)end_wanted)<=2000);
            uint64_t begin_scaled=begin_delta*expected_end[0];
            uint64_t begin_wanted=(a-start)*expected_begin[j];
            assert(llabs((long long)begin_scaled-(long long)begin_wanted)<=2000);
        }
        assert(now-start < 100*(c-start));
        resets += start!=last; last=start;
    }
    assert(resets==40);
    return NULL;
}
int main(int argc, char **argv)
{
    assert(argc==1 || argc==7);
    if(argc==7)for(int j=0;j<3;j++){
        expected_begin[j]=strtoull(argv[1+j],NULL,10);
        expected_end[j]=strtoull(argv[4+j],NULL,10);
    }
    int fd=open("/dev/prefetchit_sched_clock",O_RDONLY); assert(fd>=0);
    assert(mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0)==MAP_FAILED);
    assert(mmap(NULL,4096*64,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0)==MAP_FAILED);
    slots=mmap(NULL,4096*64,PROT_READ,MAP_SHARED,fd,0);assert(slots!=MAP_FAILED);
    close(fd);
    assert(mprotect((void *)slots,4096*64,PROT_READ|PROT_WRITE)<0);
    assert(mprotect((void *)slots,4096*64,PROT_READ|PROT_EXEC)<0);
    pthread_t threads[4];
    for(int i=0;i<4;i++)assert(!pthread_create(&threads[i],NULL,check,NULL));
    for(int i=0;i<4;i++)assert(!pthread_join(threads[i],NULL));
    assert(!munmap((void *)slots,4096*64));
    puts("PASS: read-only mmap, mprotect rejection, four threads x 40 schedule-in resets");
}
