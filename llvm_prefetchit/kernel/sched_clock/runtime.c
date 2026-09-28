#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

__attribute__((visibility("hidden"))) void *__prefetchit_sched_slots;
/* Linked once in the executable. Library probes without this object retain
 * the pass's weak NULL and skip prefetches. No per-thread registration needed. */
__attribute__((constructor(101))) static void initialize(void)
{
    int fd = open("/dev/prefetchit_sched_clock", O_RDONLY | O_CLOEXEC);
    void *p = fd < 0 ? MAP_FAILED : mmap(NULL, 4096 * 64, PROT_READ, MAP_SHARED, fd, 0);
    if (fd >= 0) close(fd);
    if (p == MAP_FAILED) {
        if (getenv("PREFETCHIT_SCHED_REQUIRED")) {
            perror("prefetchit schedule clock required"); _exit(125);
        }
        return;
    }
    __prefetchit_sched_slots = p;
    /* Map stays alive until process teardown; unloading while mapped fails. */
}
