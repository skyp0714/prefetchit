#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdatomic.h>
#include <cpuid.h>
#include <sys/mman.h>
#include <unistd.h>
#include <x86intrin.h>

__attribute__((visibility("hidden"))) void *__prefetchit_sched_slots;

#ifndef PREFETCHIT_RELAXED_CLOCK
#define PREFETCHIT_RELAXED_CLOCK 0
#endif
#ifndef PREFETCHIT_MEMO_GATE
#define PREFETCHIT_MEMO_GATE 0
#endif
#ifndef PREFETCHIT_GATE_STATS
#define PREFETCHIT_GATE_STATS 0
#endif
#if PREFETCHIT_GATE_STATS
/* Diagnostic-only counters. These perturb execution and must never be used
 * to claim E2E performance. Rows are isolated per CPU; relaxed atomic updates
 * remain valid if the calling thread migrates after reading its CPU number. */
struct stats_cpu { _Atomic uint64_t counts[3][4]; uint64_t padding[4]; };
struct stats_file { uint64_t header[8]; struct stats_cpu cpu[4096]; };
_Static_assert(sizeof(struct stats_cpu) == 128 && ATOMIC_LLONG_LOCK_FREE == 2,
               "gate diagnostic requires aligned lock-free counters");
static struct stats_file *gate_stats;
static void initialize_stats(void)
{
    const char *path = getenv("PREFETCHIT_GATE_STATS_PATH");
    if (!path) path = "/tmp/prefetchit_gate_stats.bin";
    int fd = open(path, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0 || ftruncate(fd, sizeof(struct stats_file))) {
        perror("prefetchit gate diagnostic file"); _exit(125);
    }
    void *p = mmap(NULL, sizeof(struct stats_file), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (p == MAP_FAILED) { perror("prefetchit gate diagnostic mmap"); _exit(125); }
    gate_stats = p;
    uint64_t header[8] = {0x5046474154453031ULL, 1, 4096, 3, 4,
                          (uint64_t)getpid(), sizeof(struct stats_file), 128};
    for (unsigned i = 0; i < 8; ++i) gate_stats->header[i] = header[i];
}
static __attribute__((always_inline)) inline void record_gate(unsigned cpu, unsigned tier, unsigned category)
{
    if (gate_stats) atomic_fetch_add_explicit(&gate_stats->cpu[cpu & 4095].counts[tier][category],
                                            1, memory_order_relaxed);
}
#else
#define record_gate(cpu, tier, category) ((void)0)
#endif
#if PREFETCHIT_MEMO_GATE && !PREFETCHIT_RELAXED_CLOCK
#error memoized gate requires the RDPID clock
#endif
#if PREFETCHIT_MEMO_GATE
/* Each process owns its cache. A hash collision can cause reissuance, so this
 * is best-effort suppression, not an exact once-per-schedule guarantee.
 * Atomic relaxed accesses avoid C data races when a thread is preempted or
 * migrates between RDPID and the cache access. Hints may be missed/repeated;
 * no application value or memory access depends on this cache. */
struct memo_entry { _Atomic uintptr_t site; _Atomic uint64_t epoch; };
_Static_assert(ATOMIC_POINTER_LOCK_FREE == 2 && ATOMIC_LLONG_LOCK_FREE == 2,
               "memo gate requires lock-free 64-bit atomics");
static _Alignas(64) struct memo_entry memo[4096][64];
#define CALLER_SITE ((uintptr_t)__builtin_return_address(0))
#else
#define CALLER_SITE ((uintptr_t)0)
#endif

static __attribute__((always_inline)) inline int in_window(unsigned tier, uintptr_t site)
{
    const volatile uint64_t *base = __prefetchit_sched_slots;
    if (!base) return 0;
#if PREFETCHIT_RELAXED_CLOCK
    uint64_t aux;
    __asm__ volatile("rdpid %0" : "=r"(aux) :: "memory");
    const volatile uint64_t *s = base + (aux & 4095) * 8;
#if PREFETCHIT_MEMO_GATE
    uint64_t epoch = s[3];
    // Image-relative hashing keeps the collision pattern independent of ASLR.
    uintptr_t relative = site - (uintptr_t)&__prefetchit_sched_slots;
    struct memo_entry *entry = &memo[aux & 4095][((relative >> 4) ^ (relative >> 10)) & 63];
    if (atomic_load_explicit(&entry->epoch, memory_order_relaxed) == epoch &&
        atomic_load_explicit(&entry->site, memory_order_relaxed) == site) {
        record_gate(aux, tier, 3); return 0;
    }
#endif
    /* Best-effort scheduling age for optional hints. Unlike RDTSCP this does
     * not wait for older instructions; migration can misclassify a hint. */
    uint64_t now = __rdtsc();
#else
    unsigned aux;
    uint64_t now = __rdtscp(&aux);
    const volatile uint64_t *s = base + (aux & 4095) * 8;
#endif
    uint64_t begin = s[4 + tier], end = s[tier];
    record_gate(aux, tier, now < begin ? 0 : now < end ? 1 : 2);
#if PREFETCHIT_MEMO_GATE
    // A pre-window rejection must remain eligible to be checked again later.
    // Remember either an issued group or an expired group for this epoch.
    if (now >= begin) {
        atomic_store_explicit(&entry->site, site, memory_order_relaxed);
        atomic_store_explicit(&entry->epoch, epoch, memory_order_relaxed);
    }
#endif
    // Read both bounds before combining predicates so code generation can
    // avoid a separate unpredictable branch for each side of the window.
    return (now >= begin) & (now < end);
}

/* LLVM emits real calls with this calling convention: stack alignment,
 * red-zone use and live registers remain the compiler's responsibility.
 * https://clang.llvm.org/docs/AttributeReference.html#preserve-all */
#define GATE(TIER) \
__attribute__((preserve_all, noinline, visibility("hidden"))) \
int __prefetchit_gate_##TIER(void) { return in_window(TIER, CALLER_SITE); }
GATE(0)
GATE(1)
GATE(2)
/* Linked once in the executable. Library probes without this object retain
 * the pass's weak NULL and skip prefetches. No per-thread registration needed. */
__attribute__((constructor(101))) static void initialize(void)
{
#if PREFETCHIT_GATE_STATS
    initialize_stats();
#endif
#if PREFETCHIT_RELAXED_CLOCK
    unsigned a,b,c,d;
    if (!__get_cpuid_count(7,0,&a,&b,&c,&d) || !(c & (1u << 22))) {
        if (getenv("PREFETCHIT_SCHED_REQUIRED")) {
            fputs("prefetchit RDPID clock unavailable\n", stderr); _exit(125);
        }
        return;
    }
#endif
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
