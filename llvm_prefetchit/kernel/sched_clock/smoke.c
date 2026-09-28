#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
#include <x86intrin.h>

static volatile uint64_t *slots;
static void *check(void *unused)
{
    uint64_t last = 0, resets = 0;
    for (int i=0; i<40; i++) {
        usleep(1000);
        unsigned aux; uint64_t now=__rdtscp(&aux);
        volatile uint64_t *s=slots+(aux&4095)*8;
        uint64_t start=s[3], a=s[0], b=s[1], c=s[2];
        assert(start && now>=start && a>start && b>a && c>b);
        assert(b-start == 2*(a-start) && c-start == 4*(a-start));
        assert(now-start < 100*(c-start));
        resets += start!=last; last=start;
    }
    assert(resets==40);
    return NULL;
}
int main(void)
{
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
