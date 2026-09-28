#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/mman.h>
#include <unistd.h>
#include <x86intrin.h>

__attribute__((visibility("hidden"))) void *__prefetchit_sched_slots;

static __attribute__((always_inline)) inline int in_window(unsigned tier)
{
    const volatile uint64_t *base = __prefetchit_sched_slots;
    if (!base) return 0;
    unsigned aux;
    uint64_t now = __rdtscp(&aux);
    const volatile uint64_t *s = base + (aux & 4095) * 8;
    uint64_t begin = s[4 + tier], end = s[tier];
    // Read both bounds before combining predicates so code generation can
    // avoid a separate unpredictable branch for each side of the window.
    return (now >= begin) & (now < end);
}

/* LLVM emits real calls with this calling convention: stack alignment,
 * red-zone use and live registers remain the compiler's responsibility.
 * https://clang.llvm.org/docs/AttributeReference.html#preserve-all */
#define GATE(TIER) \
__attribute__((preserve_all, noinline, visibility("hidden"))) \
int __prefetchit_gate_##TIER(void) { return in_window(TIER); }
GATE(0)
GATE(1)
GATE(2)
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
    if (((const uint64_t *)p)[7] != 2) {
        munmap(p, 4096 * 64);
        if (getenv("PREFETCHIT_SCHED_REQUIRED")) {
            fputs("prefetchit schedule clock ABI mismatch\n", stderr); _exit(125);
        }
        return;
    }
    __prefetchit_sched_slots = p;
    /* Map stays alive until process teardown; unloading while mapped fails. */
}
