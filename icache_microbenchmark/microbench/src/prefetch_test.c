// prefetch_test.c
// Build: clang -O1 -march=graniterapids -m64 -no-pie -fno-plt -mprefetchi prefetch_test.c utils.c -o prefetch_test
// Check: objdump -d -Mintel prefetch_test | grep -E 'prefetch|<bar>|<foo>|<baz>'
#define _GNU_SOURCE

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>
#include <x86intrin.h>

#include "utils.h"

typedef int (*TargetFn)(int);

static volatile int g_sink;
static volatile uint64_t g_state = 0x9e3779b97f4a7c15ull;
static uint32_t *g_chase;
static size_t g_chase_len;
static uint32_t g_chase_idx;
static int g_flush_targets_each_iter;
static int g_flush_call_path_each_iter;
static int g_measure_one_target;

extern int bar(int);
extern int foo(int);
extern int baz(int);

static int call_measured_targets(int seed);

__attribute__((used))
static TargetFn volatile g_targets[3] = {bar, foo, baz};

#define PREFETCHI_T0_TARGETS()              \
    do {                                    \
        __builtin_ia32_prefetchi(bar, 3);   \
        __builtin_ia32_prefetchi(foo, 3);   \
        __builtin_ia32_prefetchi(baz, 3);   \
    } while (0)

#define PREFETCHI_T0_LINE(symbol, offset) \
    __builtin_ia32_prefetchi((const char *)(const void *)(symbol) + (offset), 3)

#define PREFETCHI_T0_TARGET_LINES()         \
    do {                                    \
        PREFETCHI_T0_LINE(bar, 0);          \
        PREFETCHI_T0_LINE(bar, 64);         \
        PREFETCHI_T0_LINE(bar, 128);        \
        PREFETCHI_T0_LINE(bar, 192);        \
        PREFETCHI_T0_LINE(bar, 256);        \
        PREFETCHI_T0_LINE(bar, 320);        \
        PREFETCHI_T0_LINE(bar, 384);        \
        PREFETCHI_T0_LINE(bar, 448);        \
        PREFETCHI_T0_LINE(foo, 0);          \
        PREFETCHI_T0_LINE(foo, 64);         \
        PREFETCHI_T0_LINE(foo, 128);        \
        PREFETCHI_T0_LINE(foo, 192);        \
        PREFETCHI_T0_LINE(foo, 256);        \
        PREFETCHI_T0_LINE(foo, 320);        \
        PREFETCHI_T0_LINE(foo, 384);        \
        PREFETCHI_T0_LINE(foo, 448);        \
        PREFETCHI_T0_LINE(baz, 0);          \
        PREFETCHI_T0_LINE(baz, 64);         \
        PREFETCHI_T0_LINE(baz, 128);        \
        PREFETCHI_T0_LINE(baz, 192);        \
        PREFETCHI_T0_LINE(baz, 256);        \
        PREFETCHI_T0_LINE(baz, 320);        \
        PREFETCHI_T0_LINE(baz, 384);        \
        PREFETCHI_T0_LINE(baz, 448);        \
    } while (0)

#define PREFETCHI_T1_TARGETS()              \
    do {                                    \
        __builtin_ia32_prefetchi(bar, 2);   \
        __builtin_ia32_prefetchi(foo, 2);   \
        __builtin_ia32_prefetchi(baz, 2);   \
    } while (0)

#define PREFETCHI_T1_LINE(symbol, offset) \
    __builtin_ia32_prefetchi((const char *)(const void *)(symbol) + (offset), 2)

#define PREFETCHI_T1_TARGET_LINES()         \
    do {                                    \
        PREFETCHI_T1_LINE(bar, 0);          \
        PREFETCHI_T1_LINE(bar, 64);         \
        PREFETCHI_T1_LINE(bar, 128);        \
        PREFETCHI_T1_LINE(bar, 192);        \
        PREFETCHI_T1_LINE(bar, 256);        \
        PREFETCHI_T1_LINE(bar, 320);        \
        PREFETCHI_T1_LINE(bar, 384);        \
        PREFETCHI_T1_LINE(bar, 448);        \
        PREFETCHI_T1_LINE(foo, 0);          \
        PREFETCHI_T1_LINE(foo, 64);         \
        PREFETCHI_T1_LINE(foo, 128);        \
        PREFETCHI_T1_LINE(foo, 192);        \
        PREFETCHI_T1_LINE(foo, 256);        \
        PREFETCHI_T1_LINE(foo, 320);        \
        PREFETCHI_T1_LINE(foo, 384);        \
        PREFETCHI_T1_LINE(foo, 448);        \
        PREFETCHI_T1_LINE(baz, 0);          \
        PREFETCHI_T1_LINE(baz, 64);         \
        PREFETCHI_T1_LINE(baz, 128);        \
        PREFETCHI_T1_LINE(baz, 192);        \
        PREFETCHI_T1_LINE(baz, 256);        \
        PREFETCHI_T1_LINE(baz, 320);        \
        PREFETCHI_T1_LINE(baz, 384);        \
        PREFETCHI_T1_LINE(baz, 448);        \
    } while (0)

#define PREFETCHI_T0_TIMED_PATH()                       \
    do {                                                \
        __builtin_ia32_prefetchi(call_targets_indirect, 3); \
        PREFETCHI_T0_TARGETS();                         \
    } while (0)

#define PREFETCHT0_TARGET(symbol) \
    asm volatile("prefetcht0 " #symbol "(%%rip)" ::: "memory")

#define PREFETCHT0_TARGET_OFFSET(symbol, offset) \
    asm volatile("prefetcht0 " #symbol "+" #offset "(%%rip)" ::: "memory")

#define PREFETCHT0_TARGETS()                \
    do {                                    \
        PREFETCHT0_TARGET(bar);             \
        PREFETCHT0_TARGET(foo);             \
        PREFETCHT0_TARGET(baz);             \
    } while (0)

#define PREFETCHT0_TARGET_LINES()           \
    do {                                    \
        PREFETCHT0_TARGET_OFFSET(bar, 0);   \
        PREFETCHT0_TARGET_OFFSET(bar, 64);  \
        PREFETCHT0_TARGET_OFFSET(bar, 128); \
        PREFETCHT0_TARGET_OFFSET(bar, 192); \
        PREFETCHT0_TARGET_OFFSET(bar, 256); \
        PREFETCHT0_TARGET_OFFSET(bar, 320); \
        PREFETCHT0_TARGET_OFFSET(bar, 384); \
        PREFETCHT0_TARGET_OFFSET(bar, 448); \
        PREFETCHT0_TARGET_OFFSET(foo, 0);   \
        PREFETCHT0_TARGET_OFFSET(foo, 64);  \
        PREFETCHT0_TARGET_OFFSET(foo, 128); \
        PREFETCHT0_TARGET_OFFSET(foo, 192); \
        PREFETCHT0_TARGET_OFFSET(foo, 256); \
        PREFETCHT0_TARGET_OFFSET(foo, 320); \
        PREFETCHT0_TARGET_OFFSET(foo, 384); \
        PREFETCHT0_TARGET_OFFSET(foo, 448); \
        PREFETCHT0_TARGET_OFFSET(baz, 0);   \
        PREFETCHT0_TARGET_OFFSET(baz, 64);  \
        PREFETCHT0_TARGET_OFFSET(baz, 128); \
        PREFETCHT0_TARGET_OFFSET(baz, 192); \
        PREFETCHT0_TARGET_OFFSET(baz, 256); \
        PREFETCHT0_TARGET_OFFSET(baz, 320); \
        PREFETCHT0_TARGET_OFFSET(baz, 384); \
        PREFETCHT0_TARGET_OFFSET(baz, 448); \
    } while (0)

#define PREFETCHT1_TARGET(symbol) \
    asm volatile("prefetcht1 " #symbol "(%%rip)" ::: "memory")

#define PREFETCHT1_TARGET_OFFSET(symbol, offset) \
    asm volatile("prefetcht1 " #symbol "+" #offset "(%%rip)" ::: "memory")

#define PREFETCHT1_TARGETS()                \
    do {                                    \
        PREFETCHT1_TARGET(bar);             \
        PREFETCHT1_TARGET(foo);             \
        PREFETCHT1_TARGET(baz);             \
    } while (0)

#define PREFETCHT1_TARGET_LINES()           \
    do {                                    \
        PREFETCHT1_TARGET_OFFSET(bar, 0);   \
        PREFETCHT1_TARGET_OFFSET(bar, 64);  \
        PREFETCHT1_TARGET_OFFSET(bar, 128); \
        PREFETCHT1_TARGET_OFFSET(bar, 192); \
        PREFETCHT1_TARGET_OFFSET(bar, 256); \
        PREFETCHT1_TARGET_OFFSET(bar, 320); \
        PREFETCHT1_TARGET_OFFSET(bar, 384); \
        PREFETCHT1_TARGET_OFFSET(bar, 448); \
        PREFETCHT1_TARGET_OFFSET(foo, 0);   \
        PREFETCHT1_TARGET_OFFSET(foo, 64);  \
        PREFETCHT1_TARGET_OFFSET(foo, 128); \
        PREFETCHT1_TARGET_OFFSET(foo, 192); \
        PREFETCHT1_TARGET_OFFSET(foo, 256); \
        PREFETCHT1_TARGET_OFFSET(foo, 320); \
        PREFETCHT1_TARGET_OFFSET(foo, 384); \
        PREFETCHT1_TARGET_OFFSET(foo, 448); \
        PREFETCHT1_TARGET_OFFSET(baz, 0);   \
        PREFETCHT1_TARGET_OFFSET(baz, 64);  \
        PREFETCHT1_TARGET_OFFSET(baz, 128); \
        PREFETCHT1_TARGET_OFFSET(baz, 192); \
        PREFETCHT1_TARGET_OFFSET(baz, 256); \
        PREFETCHT1_TARGET_OFFSET(baz, 320); \
        PREFETCHT1_TARGET_OFFSET(baz, 384); \
        PREFETCHT1_TARGET_OFFSET(baz, 448); \
    } while (0)

#define NOP7_TARGETS()                                      \
    do {                                                    \
        asm volatile(".byte 0x0f,0x1f,0x80,0,0,0,0\n\t"     \
                     ".byte 0x0f,0x1f,0x80,0,0,0,0\n\t"     \
                     ".byte 0x0f,0x1f,0x80,0,0,0,0\n\t"     \
                     ::: "memory");                         \
    } while (0)

#define NOP7_TARGET_LINES()                                 \
    do {                                                    \
        asm volatile(".rept 24\n\t"                         \
                     ".byte 0x0f,0x1f,0x80,0,0,0,0\n\t"     \
                     ".endr"                                \
                     ::: "memory");                         \
    } while (0)

static inline uint64_t rdtsc_begin(void) {
    unsigned lo, hi;
    asm volatile("lfence\n\trdtsc" : "=a"(lo), "=d"(hi) :: "memory");
    return ((uint64_t)hi << 32) | lo;
}

static inline uint64_t rdtsc_end(void) {
    unsigned lo, hi;
    asm volatile("rdtscp\n\tlfence" : "=a"(lo), "=d"(hi) :: "rcx", "memory");
    return ((uint64_t)hi << 32) | lo;
}

static inline uint64_t xorshift64(uint64_t x) {
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return x;
}

__attribute__((noinline, used))
static void serialize_cpuid(void) {
    unsigned eax = 0, ebx, ecx, edx;
    __asm__ volatile("cpuid"
                     : "+a"(eax), "=b"(ebx), "=c"(ecx), "=d"(edx)
                     :
                     : "memory");
}

__attribute__((noinline, used, aligned(4096), section(".text.target.bar")))
int bar(int a) {
    asm volatile(".rept 512\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a + 1;
}

__attribute__((noinline, used, aligned(4096), section(".text.target.foo")))
int foo(int a) {
    asm volatile(".rept 512\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a + 3;
}

__attribute__((noinline, used, aligned(4096), section(".text.target.baz")))
int baz(int a) {
    asm volatile(".rept 512\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a + 7;
}

__attribute__((noinline, used))
static int call_targets_indirect(int seed) {
    unsigned order = (unsigned)seed % 3u;
    TargetFn f0 = g_targets[(order + 0u) % 3u];
    TargetFn f1 = g_targets[(order + 1u) % 3u];
    TargetFn f2 = g_targets[(order + 2u) % 3u];
    int v = seed;
    v = f0(v);
    v = f1(v);
    v = f2(v);
    g_sink = v;
    return v;
}

__attribute__((noinline, used))
static int call_one_target_indirect(int seed) {
    unsigned which = (unsigned)(xorshift64((uint64_t)(uint32_t)seed) % 3u);
    TargetFn f = g_targets[which];
    int v = f(seed);
    g_sink = v;
    return v;
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetch.direct")))
static void prefetchi_targets_direct(void) {
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetch.far")))
static void prefetchi_targets_far(void) {
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.t1")))
static void prefetchi_targets_t1(void) {
    PREFETCHI_T1_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetch.shape_nop")))
static void nofetch_targets_burst_shape(void) {
    NOP7_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetch.lines_shape")))
static void nofetch_target_lines_shape(void) {
    NOP7_TARGET_LINES();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t0")))
static void prefetchi_target_lines_t0(void) {
    PREFETCHI_T0_TARGET_LINES();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t1")))
static void prefetchi_target_lines_t1(void) {
    PREFETCHI_T1_TARGET_LINES();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.burst")))
static void prefetchi_targets_burst(void) {
    PREFETCHI_T0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.t1_burst")))
static void prefetchi_targets_t1_burst(void) {
    PREFETCHI_T1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.timed_path")))
static void prefetchi_timed_path_direct(void) {
    PREFETCHI_T0_TIMED_PATH();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.timed_path_burst")))
static void prefetchi_timed_path_burst(void) {
    PREFETCHI_T0_TIMED_PATH();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TIMED_PATH();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TIMED_PATH();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.coldpath")))
static void prefetchi_targets_after_cold_path(void) {
    asm volatile(".rept 32768\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht.direct")))
static void prefetcht_targets_direct(void) {
    PREFETCHT0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht.burst")))
static void prefetcht_targets_burst(void) {
    PREFETCHT0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht1.direct")))
static void prefetcht1_targets_direct(void) {
    PREFETCHT1_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht1.burst")))
static void prefetcht1_targets_burst(void) {
    PREFETCHT1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht.lines")))
static void prefetcht_target_lines(void) {
    PREFETCHT0_TARGET_LINES();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht1.lines")))
static void prefetcht1_target_lines(void) {
    PREFETCHT1_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_small_shape")))
static void farcall_small_shape(void) {
    NOP7_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_small")))
static void farcall_prefetchit0_small(void) {
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_small")))
static void farcall_prefetchit1_small(void) {
    PREFETCHI_T1_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_burst")))
static void farcall_prefetchit0_burst(void) {
    PREFETCHI_T0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_shape_burst")))
static void farcall_burst_shape(void) {
    NOP7_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_burst")))
static void farcall_prefetchit1_burst(void) {
    PREFETCHI_T1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_dt0_burst")))
static void farcall_prefetcht0_burst(void) {
    PREFETCHT0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_dt1_burst")))
static void farcall_prefetcht1_burst(void) {
    PREFETCHT1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGETS();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_shape_late")))
static void farcall_late_shape(void) {
    asm volatile(".rept 4096\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_late")))
static void farcall_prefetchit0_late(void) {
    asm volatile(".rept 4096\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_late")))
static void farcall_prefetchit1_late(void) {
    asm volatile(".rept 4096\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGETS();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_lines_shape")))
static void farcall_lines_shape(void) {
    NOP7_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_lines")))
static void farcall_prefetchit0_lines(void) {
    PREFETCHI_T0_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_lines")))
static void farcall_prefetchit1_lines(void) {
    PREFETCHI_T1_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_lines_repeat_shape")))
static void farcall_lines_repeat_shape(void) {
    NOP7_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    NOP7_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_lines_repeat")))
static void farcall_prefetchit0_lines_repeat(void) {
    PREFETCHI_T0_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_lines_repeat")))
static void farcall_prefetchit1_lines_repeat(void) {
    PREFETCHI_T1_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T1_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_dt0_lines_repeat")))
static void farcall_prefetcht0_lines_repeat(void) {
    PREFETCHT0_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT0_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_dt1_lines_repeat")))
static void farcall_prefetcht1_lines_repeat(void) {
    PREFETCHT1_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGET_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHT1_TARGET_LINES();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetcht.far")))
static void prefetcht_targets_far(void) {
    PREFETCHT0_TARGETS();
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_prefetchi")))
static void branch_prefetchi_targets(int branch_taken, uint64_t seed) {
    int take_path = ((seed ^ (seed >> 17)) & 1) == 0;
    if (branch_taken) {
        take_path = 1;
    } else if (seed & 2) {
        take_path = 0;
    }

    if (take_path) {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
        PREFETCHI_T0_TARGETS();
    } else {
        asm volatile(".rept 2048\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
        if (!branch_taken) {
            PREFETCHI_T0_TARGETS();
        }
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_prefetchi_deep")))
static void branch_prefetchi_deep_targets(int branch_taken, uint64_t seed) {
    int take_path = ((seed ^ (seed >> 11)) & 1) == 0;
    if (branch_taken) {
        take_path = 1;
    } else if (seed & 2) {
        take_path = 0;
    }

    if (take_path) {
        asm volatile(".rept 4096\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
        PREFETCHI_T0_TARGETS();
    } else {
        asm volatile(".rept 16384\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
        if (!branch_taken) {
            PREFETCHI_T0_TARGETS();
            asm volatile(".rept 64\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
            PREFETCHI_T0_TARGETS();
        }
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_prefetcht")))
static void branch_prefetcht_targets(int branch_taken, uint64_t seed) {
    int take_path = ((seed ^ (seed >> 17)) & 1) == 0;
    if (branch_taken) {
        take_path = 1;
    } else if (seed & 2) {
        take_path = 0;
    }

    if (take_path) {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
        PREFETCHT0_TARGETS();
    } else {
        asm volatile(".rept 2048\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
        if (!branch_taken) {
            PREFETCHT0_TARGETS();
        }
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_shape")))
static void trained_branch_shape_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        NOP7_TARGETS();
    } else {
        asm volatile(".rept 128\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_t0")))
static void trained_branch_prefetchit0_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        PREFETCHI_T0_TARGETS();
    } else {
        asm volatile(".rept 128\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_t1")))
static void trained_branch_prefetchit1_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        PREFETCHI_T1_TARGETS();
    } else {
        asm volatile(".rept 128\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used))
static void trained_branch_shape(void) {
    for (int i = 0; i < 64; ++i) {
        trained_branch_shape_once(0);
    }
    trained_branch_shape_once(1);
}

__attribute__((noinline, used))
static void trained_branch_prefetchit0(void) {
    for (int i = 0; i < 64; ++i) {
        trained_branch_prefetchit0_once(0);
    }
    trained_branch_prefetchit0_once(1);
}

__attribute__((noinline, used))
static void trained_branch_prefetchit1(void) {
    for (int i = 0; i < 64; ++i) {
        trained_branch_prefetchit1_once(0);
    }
    trained_branch_prefetchit1_once(1);
}

__attribute__((noinline, used, aligned(4096), section(".text.far_pressure_a")))
static int far_pressure_a(int seed) {
    asm volatile(".rept 4096\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return seed + 11;
}

__attribute__((noinline, used, aligned(4096), section(".text.far_pressure_b")))
static int far_pressure_b(int seed) {
    asm volatile(".rept 8192\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return seed * 3 + 17;
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_far_pressure_c")))
static int far_pressure_c(int seed) {
    asm volatile("" ::: "memory");
    return (seed ^ 0x5a5a) + 23;
}

__attribute__((noinline, used))
static void delay_nops_64(void) {
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_nops_256(void) {
    asm volatile(".rept 256\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_nops_1024(void) {
    asm volatile(".rept 1024\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_nops_2048(void) {
    asm volatile(".rept 2048\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_nops_4096(void) {
    asm volatile(".rept 4096\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_nops_8192(void) {
    asm volatile(".rept 8192\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_nops_16384(void) {
    asm volatile(".rept 16384\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used))
static void delay_spin(int count) {
    asm volatile("1:\n\t"
                 "decl %[count]\n\t"
                 "jnz 1b\n\t"
                 : [count] "+r"(count)
                 :
                 : "cc", "memory");
}

__attribute__((noinline, used))
static int delay_arith(int seed, int rounds) {
    uint64_t x = (uint64_t)seed + g_state;
    for (int i = 0; i < rounds; ++i) {
        x = x * 2862933555777941757ull + 3037000493ull;
        x ^= x >> 29;
        x += (uint64_t)i * 0x9e3779b1u;
    }
    g_state = x;
    g_sink = (int)x;
    return (int)x;
}

__attribute__((noinline, used))
static int delay_mul_dep(int seed, int rounds) {
    uint64_t x = (uint64_t)(uint32_t)seed + 0x9e3779b97f4a7c15ull;
    for (int i = 0; i < rounds; ++i) {
        x = x * 6364136223846793005ull + 1442695040888963407ull;
        asm volatile("" : "+r"(x) :: "memory");
    }
    g_state ^= x;
    g_sink = (int)x;
    return (int)x;
}

__attribute__((noinline, used))
static int delay_div_dep(int seed, int rounds) {
    uint64_t x = ((uint64_t)(uint32_t)seed << 32) | 0xfedcba9876543211ull;
    for (int i = 0; i < rounds; ++i) {
        uint64_t d = ((x >> 8) & 0x3ffu) | 3u;
        x = (x * 2862933555777941757ull + 3037000493ull) / d;
        x += (uint64_t)i + 0x9e3779b97f4a7c15ull;
        asm volatile("" : "+r"(x) :: "memory");
    }
    g_state ^= x;
    g_sink = (int)x;
    return (int)x;
}

__attribute__((noinline, used))
static int delay_branchy(int seed, int rounds) {
    int x = seed | 1;
    for (int i = 0; i < rounds; ++i) {
        x = x * 1664525 + 1013904223;
        if (x & 1) {
            asm volatile("" ::: "memory");
            x ^= (x >> 7) + i;
        } else {
            asm volatile("" ::: "memory");
            x += (x << 3) ^ (i * 17);
        }

        if (x & 0x100) {
            asm volatile("" ::: "memory");
            x = x * 3 + 0x5a5a;
        } else {
            asm volatile("" ::: "memory");
            x = (x >> 1) ^ 0x33cc77aa;
        }
    }
    g_sink = x;
    return x;
}

__attribute__((noinline, used))
static void delay_pause_loop(int count) {
    asm volatile("1:\n\t"
                 "pause\n\t"
                 "decl %[count]\n\t"
                 "jnz 1b\n\t"
                 : [count] "+r"(count)
                 :
                 : "cc", "memory");
}

__attribute__((noinline, used))
static int delay_chase(int steps) {
    uint32_t idx = g_chase_idx;
    if (!g_chase || g_chase_len == 0) {
        return (int)idx;
    }
    for (int i = 0; i < steps; ++i) {
        idx = g_chase[idx];
        asm volatile("" : "+r"(idx) :: "memory");
    }
    g_chase_idx = idx;
    g_sink = (int)idx;
    return (int)idx;
}

__attribute__((noinline, used, aligned(4096), section(".text.delay_complex_light")))
static int delay_complex_light(int seed) {
    int result = seed;
    for (int i = 0; i < 24; ++i) {
        result = result * 1103515245 + 12345;
        if (result & 0x40000000) {
            result ^= (result >> 7) + i;
        } else {
            result += (result << 3) ^ (i * 17);
        }
    }
    g_sink = result;
    return result;
}

__attribute__((noinline, used, aligned(4096), section(".text.delay_complex_heavy")))
static int delay_complex_heavy(int seed) {
    int result = seed;
    for (int i = 0; i < 64; ++i) {
        result = result * 1664525 + 1013904223;
        if (result & 0x80000000) {
            result ^= far_pressure_a(result);
            if (result & 0x10000000) {
                result += far_pressure_b(result);
            }
        } else {
            result += far_pressure_a(result >> 3);
            if (result & 0x08000000) {
                result ^= far_pressure_c(result);
            }
        }
    }
    g_sink = result;
    return result;
}

typedef enum {
    DELAY_NONE,
    DELAY_NOP64,
    DELAY_NOP256,
    DELAY_NOP1024,
    DELAY_NOP2048,
    DELAY_NOP4096,
    DELAY_NOP8192,
    DELAY_NOP16384,
    DELAY_SPIN128,
    DELAY_SPIN256,
    DELAY_SPIN512,
    DELAY_SPIN1K,
    DELAY_SPIN2K,
    DELAY_SPIN5K,
    DELAY_SPIN10K,
    DELAY_SPIN20K,
    DELAY_ARITH64,
    DELAY_ARITH256,
    DELAY_ARITH512,
    DELAY_ARITH1024,
    DELAY_ARITH2048,
    DELAY_MUL64,
    DELAY_MUL256,
    DELAY_MUL512,
    DELAY_MUL1024,
    DELAY_MUL2048,
    DELAY_MUL4096,
    DELAY_DIV8,
    DELAY_DIV16,
    DELAY_DIV32,
    DELAY_DIV64,
    DELAY_DIV128,
    DELAY_BRANCH64,
    DELAY_BRANCH256,
    DELAY_BRANCH1024,
    DELAY_PAUSE8,
    DELAY_PAUSE16,
    DELAY_PAUSE32,
    DELAY_PAUSE48,
    DELAY_PAUSE64,
    DELAY_PAUSE96,
    DELAY_PAUSE128,
    DELAY_PAUSE160,
    DELAY_PAUSE192,
    DELAY_PAUSE224,
    DELAY_PAUSE256,
    DELAY_PAUSE384,
    DELAY_PAUSE512,
    DELAY_PAUSE768,
    DELAY_PAUSE1024,
    DELAY_PAUSE1536,
    DELAY_PAUSE2048,
    DELAY_PAUSE4096,
    DELAY_PAUSE8192,
    DELAY_PAUSE16384,
    DELAY_CHASE256,
    DELAY_CHASE1024,
    DELAY_CHASE4096,
    DELAY_COMPLEX_LIGHT,
    DELAY_COMPLEX_HEAVY,
    DELAY_COUNT
} DelayKind;

typedef enum {
    STRATEGY_BASELINE,
    STRATEGY_PREFETCHI_DIRECT,
    STRATEGY_PREFETCHT_DIRECT,
    STRATEGY_PREFETCHI_FARFUNC,
    STRATEGY_PREFETCHT_FARFUNC,
    STRATEGY_ACTUAL_EXEC,
    STRATEGY_PREFETCHI_FAR_BEFORE,
    STRATEGY_PREFETCHT_FAR_BEFORE,
    STRATEGY_PREFETCHI_FAR_AFTER,
    STRATEGY_PREFETCHT_FAR_AFTER,
    STRATEGY_PREFETCHI_BRANCH_TAKEN,
    STRATEGY_PREFETCHT_BRANCH_TAKEN,
    STRATEGY_PREFETCHI_BRANCH_NOTTAKEN,
    STRATEGY_PREFETCHT_BRANCH_NOTTAKEN,
    STRATEGY_PREFETCHI_SERIAL_DIRECT,
    STRATEGY_PREFETCHI_SERIAL_FAR_AFTER,
    STRATEGY_PREFETCHI_T1_DIRECT,
    STRATEGY_PREFETCHI_T1_FAR_AFTER,
    STRATEGY_PREFETCHI_BURST,
    STRATEGY_PREFETCHI_BURST_FAR_AFTER,
    STRATEGY_PREFETCHI_COLDPATH,
    STRATEGY_PREFETCHI_COLDPATH_FAR_AFTER,
    STRATEGY_PREFETCHI_BRANCH_DEEP_NOTTAKEN,
    STRATEGY_PREFETCHI_BRANCH_DEEP_FAR_AFTER,
    STRATEGY_PREFETCHI_TIMED_PATH_DIRECT,
    STRATEGY_PREFETCHI_TIMED_PATH_FAR_AFTER,
    STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_DIRECT,
    STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_FAR_AFTER,
    STRATEGY_PREFETCHI_TIMED_PATH_BURST,
    STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_BURST_FAR_AFTER,
    STRATEGY_PREFETCHI_SERIAL_WAIT_DIRECT,
    STRATEGY_PREFETCHI_SERIAL_WAIT_FAR_AFTER,
    STRATEGY_PREFETCHI_SERIAL_WAIT_TIMED_PATH_FAR_AFTER,
    STRATEGY_PREFETCHI_SERIAL_WAIT_BURST_FAR_AFTER,
    STRATEGY_PREFETCHI_AB_C0_T0_B0_F0,
    STRATEGY_PREFETCHI_AB_C0_T0_B0_F1,
    STRATEGY_PREFETCHI_AB_C0_T0_B1_F0,
    STRATEGY_PREFETCHI_AB_C0_T0_B1_F1,
    STRATEGY_PREFETCHI_AB_C0_T1_B0_F0,
    STRATEGY_PREFETCHI_AB_C0_T1_B0_F1,
    STRATEGY_PREFETCHI_AB_C0_T1_B1_F0,
    STRATEGY_PREFETCHI_AB_C0_T1_B1_F1,
    STRATEGY_PREFETCHI_AB_C1_T0_B0_F0,
    STRATEGY_PREFETCHI_AB_C1_T0_B0_F1,
    STRATEGY_PREFETCHI_AB_C1_T0_B1_F0,
    STRATEGY_PREFETCHI_AB_C1_T0_B1_F1,
    STRATEGY_PREFETCHI_AB_C1_T1_B0_F0,
    STRATEGY_PREFETCHI_AB_C1_T1_B0_F1,
    STRATEGY_PREFETCHI_AB_C1_T1_B1_F0,
    STRATEGY_PREFETCHI_AB_C1_T1_B1_F1,
    STRATEGY_PREFETCHI_TEST_P,
    STRATEGY_PREFETCHI_TEST_CP,
    STRATEGY_PREFETCHI_TEST_CPF,
    STRATEGY_PREFETCHI_TEST_FPF,
    STRATEGY_APPLES_ACTUAL_EXEC,
    STRATEGY_APPLES_BASE,
    STRATEGY_APPLES_PREFETCHT0,
    STRATEGY_APPLES_PREFETCHT1,
    STRATEGY_APPLES_PREFETCHIT0,
    STRATEGY_APPLES_PREFETCHIT1,
    STRATEGY_APPLES_BASE_BURST_SHAPE,
    STRATEGY_APPLES_PREFETCHT0_BURST,
    STRATEGY_APPLES_PREFETCHT1_BURST,
    STRATEGY_APPLES_PREFETCHIT0_BURST,
    STRATEGY_APPLES_PREFETCHIT1_BURST,
    STRATEGY_APPLES_BASE_LINES_SHAPE,
    STRATEGY_APPLES_PREFETCHT0_LINES,
    STRATEGY_APPLES_PREFETCHT1_LINES,
    STRATEGY_APPLES_PREFETCHIT0_LINES,
    STRATEGY_APPLES_PREFETCHIT1_LINES,
    STRATEGY_APPLES_BASE_BRANCH_MISP,
    STRATEGY_APPLES_PREFETCHIT0_BRANCH_MISP,
    STRATEGY_APPLES_PREFETCHIT1_BRANCH_MISP,
    STRATEGY_APPLES_BASE_FARCALL_SMALL,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_SMALL,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_SMALL,
    STRATEGY_APPLES_BASE_FARCALL_BURST,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_BURST,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_BURST,
    STRATEGY_APPLES_BASE_FARCALL_LATE,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LATE,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LATE,
    STRATEGY_APPLES_BASE_FARCALL_LINES,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES,
    STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT,
    STRATEGY_APPLES_BASE_FARCALL_LINES_HOT2_NOF,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_HOT2_NOF,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_HOT2_NOF,
    STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT_NOF,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT_NOF,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT_NOF,
    STRATEGY_APPLES_BASE_FARCALL_BURST_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_BURST_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_BURST_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHT0_FARCALL_BURST_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHT1_FARCALL_BURST_REPEAT2_NOF,
    STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2,
    STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_NOCPUID,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_NOCPUID,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_NOCPUID,
    STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHT0_FARCALL_LINES_REPEAT2_NOF,
    STRATEGY_APPLES_PREFETCHT1_FARCALL_LINES_REPEAT2_NOF,
    STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_MIN,
    STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_MIN,
    STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_MIN,
    STRATEGY_COUNT
} StrategyKind;

typedef struct {
    uint64_t *cycles;
    int count;
    double mean;
    uint64_t min;
    uint64_t p05;
    uint64_t p25;
    uint64_t p50;
    uint64_t p75;
    uint64_t p95;
    uint64_t p99;
    uint64_t max;
} Stats;

static const char *delay_name(DelayKind kind) {
    switch (kind) {
    case DELAY_NONE: return "none";
    case DELAY_NOP64: return "nop64";
    case DELAY_NOP256: return "nop256";
    case DELAY_NOP1024: return "nop1024";
    case DELAY_NOP2048: return "nop2048";
    case DELAY_NOP4096: return "nop4096";
    case DELAY_NOP8192: return "nop8192";
    case DELAY_NOP16384: return "nop16384";
    case DELAY_SPIN128: return "spin128";
    case DELAY_SPIN256: return "spin256";
    case DELAY_SPIN512: return "spin512";
    case DELAY_SPIN1K: return "spin1k";
    case DELAY_SPIN2K: return "spin2k";
    case DELAY_SPIN5K: return "spin5k";
    case DELAY_SPIN10K: return "spin10k";
    case DELAY_SPIN20K: return "spin20k";
    case DELAY_ARITH64: return "arith64";
    case DELAY_ARITH256: return "arith256";
    case DELAY_ARITH512: return "arith512";
    case DELAY_ARITH1024: return "arith1024";
    case DELAY_ARITH2048: return "arith2048";
    case DELAY_MUL64: return "mul64";
    case DELAY_MUL256: return "mul256";
    case DELAY_MUL512: return "mul512";
    case DELAY_MUL1024: return "mul1024";
    case DELAY_MUL2048: return "mul2048";
    case DELAY_MUL4096: return "mul4096";
    case DELAY_DIV8: return "div8";
    case DELAY_DIV16: return "div16";
    case DELAY_DIV32: return "div32";
    case DELAY_DIV64: return "div64";
    case DELAY_DIV128: return "div128";
    case DELAY_BRANCH64: return "branch64";
    case DELAY_BRANCH256: return "branch256";
    case DELAY_BRANCH1024: return "branch1024";
    case DELAY_PAUSE8: return "pause8";
    case DELAY_PAUSE16: return "pause16";
    case DELAY_PAUSE32: return "pause32";
    case DELAY_PAUSE48: return "pause48";
    case DELAY_PAUSE64: return "pause64";
    case DELAY_PAUSE96: return "pause96";
    case DELAY_PAUSE128: return "pause128";
    case DELAY_PAUSE160: return "pause160";
    case DELAY_PAUSE192: return "pause192";
    case DELAY_PAUSE224: return "pause224";
    case DELAY_PAUSE256: return "pause256";
    case DELAY_PAUSE384: return "pause384";
    case DELAY_PAUSE512: return "pause512";
    case DELAY_PAUSE768: return "pause768";
    case DELAY_PAUSE1024: return "pause1024";
    case DELAY_PAUSE1536: return "pause1536";
    case DELAY_PAUSE2048: return "pause2048";
    case DELAY_PAUSE4096: return "pause4096";
    case DELAY_PAUSE8192: return "pause8192";
    case DELAY_PAUSE16384: return "pause16384";
    case DELAY_CHASE256: return "chase256";
    case DELAY_CHASE1024: return "chase1024";
    case DELAY_CHASE4096: return "chase4096";
    case DELAY_COMPLEX_LIGHT: return "complex_light";
    case DELAY_COMPLEX_HEAVY: return "complex_heavy";
    case DELAY_COUNT: break;
    }
    return "unknown";
}

static const char *strategy_name(StrategyKind kind) {
    switch (kind) {
    case STRATEGY_BASELINE: return "baseline";
    case STRATEGY_PREFETCHI_DIRECT: return "prefetchi_direct";
    case STRATEGY_PREFETCHT_DIRECT: return "prefetcht_direct";
    case STRATEGY_PREFETCHI_FARFUNC: return "prefetchi_farfunc";
    case STRATEGY_PREFETCHT_FARFUNC: return "prefetcht_farfunc";
    case STRATEGY_ACTUAL_EXEC: return "actual_exec_warm";
    case STRATEGY_PREFETCHI_FAR_BEFORE: return "prefetchi_far_before";
    case STRATEGY_PREFETCHT_FAR_BEFORE: return "prefetcht_far_before";
    case STRATEGY_PREFETCHI_FAR_AFTER: return "prefetchi_far_after";
    case STRATEGY_PREFETCHT_FAR_AFTER: return "prefetcht_far_after";
    case STRATEGY_PREFETCHI_BRANCH_TAKEN: return "prefetchi_branch_taken";
    case STRATEGY_PREFETCHT_BRANCH_TAKEN: return "prefetcht_branch_taken";
    case STRATEGY_PREFETCHI_BRANCH_NOTTAKEN: return "prefetchi_branch_nottaken";
    case STRATEGY_PREFETCHT_BRANCH_NOTTAKEN: return "prefetcht_branch_nottaken";
    case STRATEGY_PREFETCHI_SERIAL_DIRECT: return "prefetchi_serial_direct";
    case STRATEGY_PREFETCHI_SERIAL_FAR_AFTER: return "prefetchi_serial_far_after";
    case STRATEGY_PREFETCHI_T1_DIRECT: return "prefetchi_t1_direct";
    case STRATEGY_PREFETCHI_T1_FAR_AFTER: return "prefetchi_t1_far_after";
    case STRATEGY_PREFETCHI_BURST: return "prefetchi_burst";
    case STRATEGY_PREFETCHI_BURST_FAR_AFTER: return "prefetchi_burst_far_after";
    case STRATEGY_PREFETCHI_COLDPATH: return "prefetchi_coldpath";
    case STRATEGY_PREFETCHI_COLDPATH_FAR_AFTER: return "prefetchi_coldpath_far_after";
    case STRATEGY_PREFETCHI_BRANCH_DEEP_NOTTAKEN: return "prefetchi_branch_deep_nottaken";
    case STRATEGY_PREFETCHI_BRANCH_DEEP_FAR_AFTER: return "prefetchi_branch_deep_far_after";
    case STRATEGY_PREFETCHI_TIMED_PATH_DIRECT: return "prefetchi_timed_path_direct";
    case STRATEGY_PREFETCHI_TIMED_PATH_FAR_AFTER: return "prefetchi_timed_path_far_after";
    case STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_DIRECT: return "prefetchi_serial_timed_path_direct";
    case STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_FAR_AFTER: return "prefetchi_serial_timed_path_far_after";
    case STRATEGY_PREFETCHI_TIMED_PATH_BURST: return "prefetchi_timed_path_burst";
    case STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_BURST_FAR_AFTER: return "prefetchi_serial_timed_path_burst_far_after";
    case STRATEGY_PREFETCHI_SERIAL_WAIT_DIRECT: return "prefetchi_serial_wait_direct";
    case STRATEGY_PREFETCHI_SERIAL_WAIT_FAR_AFTER: return "prefetchi_serial_wait_far_after";
    case STRATEGY_PREFETCHI_SERIAL_WAIT_TIMED_PATH_FAR_AFTER: return "prefetchi_serial_wait_timed_path_far_after";
    case STRATEGY_PREFETCHI_SERIAL_WAIT_BURST_FAR_AFTER: return "prefetchi_serial_wait_burst_far_after";
    case STRATEGY_PREFETCHI_AB_C0_T0_B0_F0: return "prefetchi_ab_c0_t0_b0_f0";
    case STRATEGY_PREFETCHI_AB_C0_T0_B0_F1: return "prefetchi_ab_c0_t0_b0_f1";
    case STRATEGY_PREFETCHI_AB_C0_T0_B1_F0: return "prefetchi_ab_c0_t0_b1_f0";
    case STRATEGY_PREFETCHI_AB_C0_T0_B1_F1: return "prefetchi_ab_c0_t0_b1_f1";
    case STRATEGY_PREFETCHI_AB_C0_T1_B0_F0: return "prefetchi_ab_c0_t1_b0_f0";
    case STRATEGY_PREFETCHI_AB_C0_T1_B0_F1: return "prefetchi_ab_c0_t1_b0_f1";
    case STRATEGY_PREFETCHI_AB_C0_T1_B1_F0: return "prefetchi_ab_c0_t1_b1_f0";
    case STRATEGY_PREFETCHI_AB_C0_T1_B1_F1: return "prefetchi_ab_c0_t1_b1_f1";
    case STRATEGY_PREFETCHI_AB_C1_T0_B0_F0: return "prefetchi_ab_c1_t0_b0_f0";
    case STRATEGY_PREFETCHI_AB_C1_T0_B0_F1: return "prefetchi_ab_c1_t0_b0_f1";
    case STRATEGY_PREFETCHI_AB_C1_T0_B1_F0: return "prefetchi_ab_c1_t0_b1_f0";
    case STRATEGY_PREFETCHI_AB_C1_T0_B1_F1: return "prefetchi_ab_c1_t0_b1_f1";
    case STRATEGY_PREFETCHI_AB_C1_T1_B0_F0: return "prefetchi_ab_c1_t1_b0_f0";
    case STRATEGY_PREFETCHI_AB_C1_T1_B0_F1: return "prefetchi_ab_c1_t1_b0_f1";
    case STRATEGY_PREFETCHI_AB_C1_T1_B1_F0: return "prefetchi_ab_c1_t1_b1_f0";
    case STRATEGY_PREFETCHI_AB_C1_T1_B1_F1: return "prefetchi_ab_c1_t1_b1_f1";
    case STRATEGY_PREFETCHI_TEST_P: return "prefetchi_test_p";
    case STRATEGY_PREFETCHI_TEST_CP: return "prefetchi_test_cp";
    case STRATEGY_PREFETCHI_TEST_CPF: return "prefetchi_test_cpf";
    case STRATEGY_PREFETCHI_TEST_FPF: return "prefetchi_test_fpf";
    case STRATEGY_APPLES_ACTUAL_EXEC: return "apples_actual_exec";
    case STRATEGY_APPLES_BASE: return "apples_base";
    case STRATEGY_APPLES_PREFETCHT0: return "apples_prefetcht0";
    case STRATEGY_APPLES_PREFETCHT1: return "apples_prefetcht1";
    case STRATEGY_APPLES_PREFETCHIT0: return "apples_prefetchit0";
    case STRATEGY_APPLES_PREFETCHIT1: return "apples_prefetchit1";
    case STRATEGY_APPLES_BASE_BURST_SHAPE: return "apples_base_burst_shape";
    case STRATEGY_APPLES_PREFETCHT0_BURST: return "apples_prefetcht0_burst";
    case STRATEGY_APPLES_PREFETCHT1_BURST: return "apples_prefetcht1_burst";
    case STRATEGY_APPLES_PREFETCHIT0_BURST: return "apples_prefetchit0_burst";
    case STRATEGY_APPLES_PREFETCHIT1_BURST: return "apples_prefetchit1_burst";
    case STRATEGY_APPLES_BASE_LINES_SHAPE: return "apples_base_lines_shape";
    case STRATEGY_APPLES_PREFETCHT0_LINES: return "apples_prefetcht0_lines";
    case STRATEGY_APPLES_PREFETCHT1_LINES: return "apples_prefetcht1_lines";
    case STRATEGY_APPLES_PREFETCHIT0_LINES: return "apples_prefetchit0_lines";
    case STRATEGY_APPLES_PREFETCHIT1_LINES: return "apples_prefetchit1_lines";
    case STRATEGY_APPLES_BASE_BRANCH_MISP: return "apples_base_branch_misp";
    case STRATEGY_APPLES_PREFETCHIT0_BRANCH_MISP: return "apples_prefetchit0_branch_misp";
    case STRATEGY_APPLES_PREFETCHIT1_BRANCH_MISP: return "apples_prefetchit1_branch_misp";
    case STRATEGY_APPLES_BASE_FARCALL_SMALL: return "apples_base_farcall_small";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_SMALL: return "apples_prefetchit0_farcall_small";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_SMALL: return "apples_prefetchit1_farcall_small";
    case STRATEGY_APPLES_BASE_FARCALL_BURST: return "apples_base_farcall_burst";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_BURST: return "apples_prefetchit0_farcall_burst";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_BURST: return "apples_prefetchit1_farcall_burst";
    case STRATEGY_APPLES_BASE_FARCALL_LATE: return "apples_base_farcall_late";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LATE: return "apples_prefetchit0_farcall_late";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LATE: return "apples_prefetchit1_farcall_late";
    case STRATEGY_APPLES_BASE_FARCALL_LINES: return "apples_base_farcall_lines";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES: return "apples_prefetchit0_farcall_lines";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES: return "apples_prefetchit1_farcall_lines";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT: return "apples_base_farcall_lines_repeat";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT: return "apples_prefetchit0_farcall_lines_repeat";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT: return "apples_prefetchit1_farcall_lines_repeat";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_HOT2_NOF: return "apples_base_farcall_lines_hot2_nof";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_HOT2_NOF: return "apples_prefetchit0_farcall_lines_hot2_nof";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_HOT2_NOF: return "apples_prefetchit1_farcall_lines_hot2_nof";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT_NOF: return "apples_base_farcall_lines_repeat_nof";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT_NOF: return "apples_prefetchit0_farcall_lines_repeat_nof";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT_NOF: return "apples_prefetchit1_farcall_lines_repeat_nof";
    case STRATEGY_APPLES_BASE_FARCALL_BURST_REPEAT2_NOF: return "apples_base_farcall_burst_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_BURST_REPEAT2_NOF: return "apples_prefetchit0_farcall_burst_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_BURST_REPEAT2_NOF: return "apples_prefetchit1_farcall_burst_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHT0_FARCALL_BURST_REPEAT2_NOF: return "apples_prefetcht0_farcall_burst_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHT1_FARCALL_BURST_REPEAT2_NOF: return "apples_prefetcht1_farcall_burst_repeat2_nof";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2: return "apples_base_farcall_lines_repeat2";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2: return "apples_prefetchit0_farcall_lines_repeat2";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2: return "apples_prefetchit1_farcall_lines_repeat2";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_NOCPUID: return "apples_base_farcall_lines_repeat2_nocpuid";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_NOCPUID: return "apples_prefetchit0_farcall_lines_repeat2_nocpuid";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_NOCPUID: return "apples_prefetchit1_farcall_lines_repeat2_nocpuid";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_NOF: return "apples_base_farcall_lines_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_NOF: return "apples_prefetchit0_farcall_lines_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_NOF: return "apples_prefetchit1_farcall_lines_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHT0_FARCALL_LINES_REPEAT2_NOF: return "apples_prefetcht0_farcall_lines_repeat2_nof";
    case STRATEGY_APPLES_PREFETCHT1_FARCALL_LINES_REPEAT2_NOF: return "apples_prefetcht1_farcall_lines_repeat2_nof";
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_MIN: return "apples_base_farcall_lines_repeat2_min";
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_MIN: return "apples_prefetchit0_farcall_lines_repeat2_min";
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_MIN: return "apples_prefetchit1_farcall_lines_repeat2_min";
    case STRATEGY_COUNT: break;
    }
    return "unknown";
}

static void run_delay(DelayKind delay, int seed) {
    switch (delay) {
    case DELAY_NONE:
        break;
    case DELAY_NOP64:
        delay_nops_64();
        break;
    case DELAY_NOP256:
        delay_nops_256();
        break;
    case DELAY_NOP1024:
        delay_nops_1024();
        break;
    case DELAY_NOP2048:
        delay_nops_2048();
        break;
    case DELAY_NOP4096:
        delay_nops_4096();
        break;
    case DELAY_NOP8192:
        delay_nops_8192();
        break;
    case DELAY_NOP16384:
        delay_nops_16384();
        break;
    case DELAY_SPIN128:
        delay_spin(128);
        break;
    case DELAY_SPIN256:
        delay_spin(256);
        break;
    case DELAY_SPIN512:
        delay_spin(512);
        break;
    case DELAY_SPIN1K:
        delay_spin(1000);
        break;
    case DELAY_SPIN2K:
        delay_spin(2000);
        break;
    case DELAY_SPIN5K:
        delay_spin(5000);
        break;
    case DELAY_SPIN10K:
        delay_spin(10000);
        break;
    case DELAY_SPIN20K:
        delay_spin(20000);
        break;
    case DELAY_ARITH64:
        (void)delay_arith(seed, 64);
        break;
    case DELAY_ARITH256:
        (void)delay_arith(seed, 256);
        break;
    case DELAY_ARITH512:
        (void)delay_arith(seed, 512);
        break;
    case DELAY_ARITH1024:
        (void)delay_arith(seed, 1024);
        break;
    case DELAY_ARITH2048:
        (void)delay_arith(seed, 2048);
        break;
    case DELAY_MUL64:
        (void)delay_mul_dep(seed, 64);
        break;
    case DELAY_MUL256:
        (void)delay_mul_dep(seed, 256);
        break;
    case DELAY_MUL512:
        (void)delay_mul_dep(seed, 512);
        break;
    case DELAY_MUL1024:
        (void)delay_mul_dep(seed, 1024);
        break;
    case DELAY_MUL2048:
        (void)delay_mul_dep(seed, 2048);
        break;
    case DELAY_MUL4096:
        (void)delay_mul_dep(seed, 4096);
        break;
    case DELAY_DIV8:
        (void)delay_div_dep(seed, 8);
        break;
    case DELAY_DIV16:
        (void)delay_div_dep(seed, 16);
        break;
    case DELAY_DIV32:
        (void)delay_div_dep(seed, 32);
        break;
    case DELAY_DIV64:
        (void)delay_div_dep(seed, 64);
        break;
    case DELAY_DIV128:
        (void)delay_div_dep(seed, 128);
        break;
    case DELAY_BRANCH64:
        (void)delay_branchy(seed, 64);
        break;
    case DELAY_BRANCH256:
        (void)delay_branchy(seed, 256);
        break;
    case DELAY_BRANCH1024:
        (void)delay_branchy(seed, 1024);
        break;
    case DELAY_PAUSE8:
        delay_pause_loop(8);
        break;
    case DELAY_PAUSE16:
        delay_pause_loop(16);
        break;
    case DELAY_PAUSE32:
        delay_pause_loop(32);
        break;
    case DELAY_PAUSE48:
        delay_pause_loop(48);
        break;
    case DELAY_PAUSE64:
        delay_pause_loop(64);
        break;
    case DELAY_PAUSE96:
        delay_pause_loop(96);
        break;
    case DELAY_PAUSE128:
        delay_pause_loop(128);
        break;
    case DELAY_PAUSE160:
        delay_pause_loop(160);
        break;
    case DELAY_PAUSE192:
        delay_pause_loop(192);
        break;
    case DELAY_PAUSE224:
        delay_pause_loop(224);
        break;
    case DELAY_PAUSE256:
        delay_pause_loop(256);
        break;
    case DELAY_PAUSE384:
        delay_pause_loop(384);
        break;
    case DELAY_PAUSE512:
        delay_pause_loop(512);
        break;
    case DELAY_PAUSE768:
        delay_pause_loop(768);
        break;
    case DELAY_PAUSE1024:
        delay_pause_loop(1024);
        break;
    case DELAY_PAUSE1536:
        delay_pause_loop(1536);
        break;
    case DELAY_PAUSE2048:
        delay_pause_loop(2048);
        break;
    case DELAY_PAUSE4096:
        delay_pause_loop(4096);
        break;
    case DELAY_PAUSE8192:
        delay_pause_loop(8192);
        break;
    case DELAY_PAUSE16384:
        delay_pause_loop(16384);
        break;
    case DELAY_CHASE256:
        (void)delay_chase(256);
        break;
    case DELAY_CHASE1024:
        (void)delay_chase(1024);
        break;
    case DELAY_CHASE4096:
        (void)delay_chase(4096);
        break;
    case DELAY_COMPLEX_LIGHT:
        (void)delay_complex_light(seed);
        break;
    case DELAY_COMPLEX_HEAVY:
        (void)delay_complex_heavy(seed);
        break;
    case DELAY_COUNT:
        break;
    }
}

static void run_prefetchi_ablation(int seed, int use_cpuid, int use_timed_path,
                                   int use_burst, int use_far_after);
static void flush_code_range(const void *ptr, size_t bytes);

static void call_cold_prefetch_func(void (*fn)(void), size_t bytes) {
    flush_code_range((const void *)fn, bytes);
    asm volatile("mfence\n\tlfence" ::: "memory");
    fn();
}

static void run_strategy(StrategyKind strategy, int seed) {
    switch (strategy) {
    case STRATEGY_BASELINE:
        break;
    case STRATEGY_PREFETCHI_DIRECT:
        prefetchi_targets_direct();
        break;
    case STRATEGY_PREFETCHT_DIRECT:
        prefetcht_targets_direct();
        break;
    case STRATEGY_PREFETCHI_FARFUNC:
        prefetchi_targets_far();
        break;
    case STRATEGY_PREFETCHT_FARFUNC:
        prefetcht_targets_far();
        break;
    case STRATEGY_ACTUAL_EXEC:
        (void)call_targets_indirect(seed);
        break;
    case STRATEGY_PREFETCHI_FAR_BEFORE:
        g_sink = far_pressure_b(seed);
        prefetchi_targets_direct();
        break;
    case STRATEGY_PREFETCHT_FAR_BEFORE:
        g_sink = far_pressure_b(seed);
        prefetcht_targets_direct();
        break;
    case STRATEGY_PREFETCHI_FAR_AFTER:
        prefetchi_targets_direct();
        g_sink = far_pressure_b(seed);
        break;
    case STRATEGY_PREFETCHT_FAR_AFTER:
        prefetcht_targets_direct();
        g_sink = far_pressure_b(seed);
        break;
    case STRATEGY_PREFETCHI_BRANCH_TAKEN:
        branch_prefetchi_targets(1, (uint64_t)seed);
        break;
    case STRATEGY_PREFETCHT_BRANCH_TAKEN:
        branch_prefetcht_targets(1, (uint64_t)seed);
        break;
    case STRATEGY_PREFETCHI_BRANCH_NOTTAKEN:
        branch_prefetchi_targets(0, (uint64_t)seed | 2u);
        break;
    case STRATEGY_PREFETCHT_BRANCH_NOTTAKEN:
        branch_prefetcht_targets(0, (uint64_t)seed | 2u);
        break;
    case STRATEGY_PREFETCHI_SERIAL_DIRECT:
        serialize_cpuid();
        prefetchi_targets_direct();
        break;
    case STRATEGY_PREFETCHI_SERIAL_FAR_AFTER:
        serialize_cpuid();
        prefetchi_targets_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_T1_DIRECT:
        prefetchi_targets_t1();
        break;
    case STRATEGY_PREFETCHI_T1_FAR_AFTER:
        prefetchi_targets_t1();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_BURST:
        prefetchi_targets_burst();
        break;
    case STRATEGY_PREFETCHI_BURST_FAR_AFTER:
        prefetchi_targets_burst();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_COLDPATH:
        prefetchi_targets_after_cold_path();
        break;
    case STRATEGY_PREFETCHI_COLDPATH_FAR_AFTER:
        prefetchi_targets_after_cold_path();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_BRANCH_DEEP_NOTTAKEN:
        branch_prefetchi_deep_targets(0, (uint64_t)seed | 2u);
        break;
    case STRATEGY_PREFETCHI_BRANCH_DEEP_FAR_AFTER:
        branch_prefetchi_deep_targets(0, (uint64_t)seed | 2u);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_TIMED_PATH_DIRECT:
        prefetchi_timed_path_direct();
        break;
    case STRATEGY_PREFETCHI_TIMED_PATH_FAR_AFTER:
        prefetchi_timed_path_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_DIRECT:
        serialize_cpuid();
        prefetchi_timed_path_direct();
        break;
    case STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_FAR_AFTER:
        serialize_cpuid();
        prefetchi_timed_path_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_TIMED_PATH_BURST:
        prefetchi_timed_path_burst();
        break;
    case STRATEGY_PREFETCHI_SERIAL_TIMED_PATH_BURST_FAR_AFTER:
        serialize_cpuid();
        prefetchi_timed_path_burst();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_SERIAL_WAIT_DIRECT:
        serialize_cpuid();
        prefetchi_targets_direct();
        serialize_cpuid();
        break;
    case STRATEGY_PREFETCHI_SERIAL_WAIT_FAR_AFTER:
        serialize_cpuid();
        prefetchi_targets_direct();
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_SERIAL_WAIT_TIMED_PATH_FAR_AFTER:
        serialize_cpuid();
        prefetchi_timed_path_direct();
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_SERIAL_WAIT_BURST_FAR_AFTER:
        serialize_cpuid();
        prefetchi_targets_burst();
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T0_B0_F0:
        run_prefetchi_ablation(seed, 0, 0, 0, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T0_B0_F1:
        run_prefetchi_ablation(seed, 0, 0, 0, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T0_B1_F0:
        run_prefetchi_ablation(seed, 0, 0, 1, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T0_B1_F1:
        run_prefetchi_ablation(seed, 0, 0, 1, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T1_B0_F0:
        run_prefetchi_ablation(seed, 0, 1, 0, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T1_B0_F1:
        run_prefetchi_ablation(seed, 0, 1, 0, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T1_B1_F0:
        run_prefetchi_ablation(seed, 0, 1, 1, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C0_T1_B1_F1:
        run_prefetchi_ablation(seed, 0, 1, 1, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T0_B0_F0:
        run_prefetchi_ablation(seed, 1, 0, 0, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T0_B0_F1:
        run_prefetchi_ablation(seed, 1, 0, 0, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T0_B1_F0:
        run_prefetchi_ablation(seed, 1, 0, 1, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T0_B1_F1:
        run_prefetchi_ablation(seed, 1, 0, 1, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T1_B0_F0:
        run_prefetchi_ablation(seed, 1, 1, 0, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T1_B0_F1:
        run_prefetchi_ablation(seed, 1, 1, 0, 1);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T1_B1_F0:
        run_prefetchi_ablation(seed, 1, 1, 1, 0);
        break;
    case STRATEGY_PREFETCHI_AB_C1_T1_B1_F1:
        run_prefetchi_ablation(seed, 1, 1, 1, 1);
        break;
    case STRATEGY_PREFETCHI_TEST_P:
        prefetchi_targets_direct();
        break;
    case STRATEGY_PREFETCHI_TEST_CP:
        serialize_cpuid();
        prefetchi_targets_direct();
        break;
    case STRATEGY_PREFETCHI_TEST_CPF:
        serialize_cpuid();
        prefetchi_targets_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_PREFETCHI_TEST_FPF:
        g_sink = far_pressure_c(seed);
        prefetchi_targets_direct();
        g_sink = far_pressure_c(seed + g_sink);
        break;
    case STRATEGY_APPLES_ACTUAL_EXEC:
        serialize_cpuid();
        (void)call_measured_targets(seed);
        break;
    case STRATEGY_APPLES_BASE:
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHT0:
        serialize_cpuid();
        prefetcht_targets_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHT1:
        serialize_cpuid();
        prefetcht1_targets_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0:
        serialize_cpuid();
        prefetchi_targets_direct();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1:
        serialize_cpuid();
        prefetchi_targets_t1();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_BURST_SHAPE:
        serialize_cpuid();
        nofetch_targets_burst_shape();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHT0_BURST:
        serialize_cpuid();
        prefetcht_targets_burst();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHT1_BURST:
        serialize_cpuid();
        prefetcht1_targets_burst();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_BURST:
        serialize_cpuid();
        prefetchi_targets_burst();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_BURST:
        serialize_cpuid();
        prefetchi_targets_t1_burst();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_LINES_SHAPE:
        serialize_cpuid();
        nofetch_target_lines_shape();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHT0_LINES:
        serialize_cpuid();
        prefetcht_target_lines();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHT1_LINES:
        serialize_cpuid();
        prefetcht1_target_lines();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_LINES:
        serialize_cpuid();
        prefetchi_target_lines_t0();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_LINES:
        serialize_cpuid();
        prefetchi_target_lines_t1();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_BRANCH_MISP:
        serialize_cpuid();
        trained_branch_shape();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_BRANCH_MISP:
        serialize_cpuid();
        trained_branch_prefetchit0();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_BRANCH_MISP:
        serialize_cpuid();
        trained_branch_prefetchit1();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_SMALL:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_small_shape, 256);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_SMALL:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_small, 256);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_SMALL:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_small, 256);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_BURST:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_burst_shape, 1024);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_BURST:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_burst, 1024);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_BURST:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_burst, 1024);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LATE:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_late_shape, 8192);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LATE:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_late, 8192);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LATE:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_late, 8192);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_lines_shape, 1024);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_lines, 1024);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_lines, 1024);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_lines_repeat_shape, 4096);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_lines_repeat, 4096);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_HOT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_lines_shape, 1024);
        farcall_lines_shape();
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_HOT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_lines, 1024);
        farcall_prefetchit0_lines();
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_HOT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_lines, 1024);
        farcall_prefetchit1_lines();
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_lines_repeat_shape, 4096);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_lines_repeat, 4096);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_BURST_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_burst_shape, 4096);
        farcall_burst_shape();
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_BURST_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_burst, 4096);
        farcall_prefetchit0_burst();
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_BURST_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_burst, 4096);
        farcall_prefetchit1_burst();
        break;
    case STRATEGY_APPLES_PREFETCHT0_FARCALL_BURST_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetcht0_burst, 4096);
        farcall_prefetcht0_burst();
        break;
    case STRATEGY_APPLES_PREFETCHT1_FARCALL_BURST_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetcht1_burst, 4096);
        farcall_prefetcht1_burst();
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_lines_repeat_shape, 4096);
        farcall_lines_repeat_shape();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        farcall_prefetchit0_lines_repeat();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_lines_repeat, 4096);
        farcall_prefetchit1_lines_repeat();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_NOCPUID:
        call_cold_prefetch_func(farcall_lines_repeat_shape, 4096);
        farcall_lines_repeat_shape();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_NOCPUID:
        call_cold_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        farcall_prefetchit0_lines_repeat();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_NOCPUID:
        call_cold_prefetch_func(farcall_prefetchit1_lines_repeat, 4096);
        farcall_prefetchit1_lines_repeat();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_lines_repeat_shape, 4096);
        farcall_lines_repeat_shape();
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        farcall_prefetchit0_lines_repeat();
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetchit1_lines_repeat, 4096);
        farcall_prefetchit1_lines_repeat();
        break;
    case STRATEGY_APPLES_PREFETCHT0_FARCALL_LINES_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetcht0_lines_repeat, 4096);
        farcall_prefetcht0_lines_repeat();
        break;
    case STRATEGY_APPLES_PREFETCHT1_FARCALL_LINES_REPEAT2_NOF:
        serialize_cpuid();
        call_cold_prefetch_func(farcall_prefetcht1_lines_repeat, 4096);
        farcall_prefetcht1_lines_repeat();
        break;
    case STRATEGY_APPLES_BASE_FARCALL_LINES_REPEAT2_MIN:
        call_cold_prefetch_func(farcall_lines_repeat_shape, 4096);
        farcall_lines_repeat_shape();
        break;
    case STRATEGY_APPLES_PREFETCHIT0_FARCALL_LINES_REPEAT2_MIN:
        call_cold_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        farcall_prefetchit0_lines_repeat();
        break;
    case STRATEGY_APPLES_PREFETCHIT1_FARCALL_LINES_REPEAT2_MIN:
        call_cold_prefetch_func(farcall_prefetchit1_lines_repeat, 4096);
        farcall_prefetchit1_lines_repeat();
        break;
    case STRATEGY_COUNT:
        break;
    }
}

static void run_prefetchi_ablation(int seed, int use_cpuid, int use_timed_path,
                                   int use_burst, int use_far_after) {
    if (use_cpuid) {
        serialize_cpuid();
    }

    if (use_burst) {
        if (use_timed_path) {
            prefetchi_timed_path_burst();
        } else {
            prefetchi_targets_burst();
        }
    } else if (use_timed_path) {
        prefetchi_timed_path_direct();
    } else {
        prefetchi_targets_direct();
    }

    if (use_far_after) {
        g_sink = far_pressure_c(seed);
    }
}

static void *g_evict_code;
static size_t g_evict_bytes;

static void setup_evictor(size_t bytes) {
    g_evict_bytes = bytes;
    if (bytes == 0) {
        return;
    }

    g_evict_code = mmap(NULL, bytes, PROT_READ | PROT_WRITE | PROT_EXEC,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (g_evict_code == MAP_FAILED) {
        fprintf(stderr, "failed to allocate I-cache evictor: %s\n", strerror(errno));
        exit(1);
    }

    unsigned char *code = (unsigned char *)g_evict_code;
    memset(code, 0x90, bytes);
    for (size_t i = 0; i + 4 < bytes; i += 4) {
        code[i + 0] = 0x90;
        code[i + 1] = 0x90;
        code[i + 2] = 0x66;
        code[i + 3] = 0x90;
    }
    code[bytes - 1] = 0xc3;
    __builtin___clear_cache((char *)g_evict_code, (char *)g_evict_code + bytes);
}

static void setup_chase_buffer(size_t bytes) {
    if (bytes < 4096) {
        return;
    }

    size_t entries = bytes / sizeof(g_chase[0]);
    if (entries > UINT32_MAX) {
        entries = UINT32_MAX;
    }

    g_chase = mmap(NULL, entries * sizeof(g_chase[0]), PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (g_chase == MAP_FAILED) {
        fprintf(stderr, "WARN: failed to allocate chase delay buffer: %s\n", strerror(errno));
        g_chase = NULL;
        return;
    }

    uint32_t *order = malloc(entries * sizeof(order[0]));
    if (!order) {
        fprintf(stderr, "WARN: failed to allocate chase permutation\n");
        munmap(g_chase, entries * sizeof(g_chase[0]));
        g_chase = NULL;
        return;
    }

    for (size_t i = 0; i < entries; ++i) {
        order[i] = (uint32_t)i;
    }

    uint64_t rng = 0x243f6a8885a308d3ull ^ (uint64_t)entries;
    for (size_t i = entries - 1; i > 0; --i) {
        rng = xorshift64(rng);
        size_t j = (size_t)(rng % (i + 1));
        uint32_t tmp = order[i];
        order[i] = order[j];
        order[j] = tmp;
    }

    for (size_t i = 0; i < entries; ++i) {
        g_chase[order[i]] = order[(i + 1) % entries];
    }
    g_chase_idx = order[0];
    g_chase_len = entries;

    free(order);
}

static void evict_icache(void) {
    if (!g_evict_code) {
        return;
    }
    void (*fn)(void) = (void (*)(void))g_evict_code;
    fn();
}

static void flush_code_range(const void *ptr, size_t bytes) {
    uintptr_t start = (uintptr_t)ptr & ~(uintptr_t)63;
    uintptr_t end = ((uintptr_t)ptr + bytes + 63u) & ~(uintptr_t)63;
    for (uintptr_t p = start; p < end; p += 64) {
        _mm_clflush((const void *)p);
    }
}

static void flush_target_code(void) {
    flush_code_range((const void *)bar, 1024);
    flush_code_range((const void *)foo, 1024);
    flush_code_range((const void *)baz, 1024);
}

static void flush_call_path_code(void) {
    flush_code_range((const void *)call_targets_indirect, 512);
    flush_code_range((const void *)call_one_target_indirect, 512);
}

static int call_measured_targets(int seed) {
    if (g_measure_one_target) {
        return call_one_target_indirect(seed);
    }
    return call_targets_indirect(seed);
}

static int cmp_u64(const void *a, const void *b) {
    uint64_t va = *(const uint64_t *)a;
    uint64_t vb = *(const uint64_t *)b;
    return (va > vb) - (va < vb);
}

static uint64_t percentile(const uint64_t *arr, int n, int pct) {
    int idx = (int)(((uint64_t)(n - 1) * (uint64_t)pct) / 100u);
    return arr[idx];
}

static Stats compute_stats(uint64_t *cycles, int count) {
    Stats s;
    memset(&s, 0, sizeof(s));
    s.cycles = cycles;
    s.count = count;
    qsort(cycles, (size_t)count, sizeof(cycles[0]), cmp_u64);

    unsigned __int128 sum = 0;
    for (int i = 0; i < count; ++i) {
        sum += cycles[i];
    }

    s.mean = (double)sum / (double)count;
    s.min = cycles[0];
    s.p05 = percentile(cycles, count, 5);
    s.p25 = percentile(cycles, count, 25);
    s.p50 = percentile(cycles, count, 50);
    s.p75 = percentile(cycles, count, 75);
    s.p95 = percentile(cycles, count, 95);
    s.p99 = percentile(cycles, count, 99);
    s.max = cycles[count - 1];
    return s;
}

static Stats run_one_case(StrategyKind strategy, DelayKind delay, int iterations) {
    uint64_t *cycles = calloc((size_t)iterations, sizeof(cycles[0]));
    if (!cycles) {
        fprintf(stderr, "calloc failed\n");
        exit(1);
    }

    for (int i = 0; i < iterations; ++i) {
        g_state = xorshift64(g_state + (uint64_t)i + 1u);
        int seed = (int)g_state;

        evict_icache();
        if (g_flush_targets_each_iter) {
            flush_target_code();
        }
        if (g_flush_call_path_each_iter) {
            flush_call_path_code();
        }
        asm volatile("mfence\n\tlfence" ::: "memory");

        run_strategy(strategy, seed);
        run_delay(delay, seed);

        uint64_t t0 = rdtsc_begin();
        (void)call_measured_targets(seed);
        uint64_t t1 = rdtsc_end();
        cycles[i] = t1 - t0;
    }

    return compute_stats(cycles, iterations);
}

static void print_stats_csv(StrategyKind strategy, DelayKind delay, int iterations,
                            size_t evict_kib, const Stats *s) {
    printf("%s,%s,%d,%zu,%.2f,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu\n",
           strategy_name(strategy),
           delay_name(delay),
           iterations,
           evict_kib,
           s->mean,
           (unsigned long long)s->min,
           (unsigned long long)s->p05,
           (unsigned long long)s->p25,
           (unsigned long long)s->p50,
           (unsigned long long)s->p75,
           (unsigned long long)s->p95,
           (unsigned long long)s->p99,
           (unsigned long long)s->max);
}

static int has_prefetchi(void) {
    unsigned eax = 7, ebx, ecx = 1, edx;
    __asm__ volatile("cpuid"
                     : "+a"(eax), "=b"(ebx), "+c"(ecx), "=d"(edx)
                     :
                     : "memory");
    return ((edx >> 14) & 1u) != 0;
}

static int matches_filter(const char *name, const char *filter) {
    if (!filter || filter[0] == '\0' || strcmp(filter, "all") == 0) {
        return 1;
    }

    const char *start = filter;
    while (*start) {
        const char *end = strchr(start, ',');
        size_t len = end ? (size_t)(end - start) : strlen(start);
        if (len > 0) {
            if (start[0] == '=') {
                size_t exact_len = len - 1u;
                if (strlen(name) == exact_len && strncmp(name, start + 1, exact_len) == 0) {
                    return 1;
                }
            } else {
                size_t name_len = strlen(name);
                for (size_t i = 0; i + len <= name_len; ++i) {
                    if (strncmp(name + i, start, len) == 0) {
                        return 1;
                    }
                }
            }
        }
        if (!end) {
            break;
        }
        start = end + 1;
    }

    return 0;
}

int main(int argc, char **argv) {
    int iterations = 200;
    size_t evict_kib = 1024;
    int cpu = 10;
    const char *delay_filter = NULL;
    const char *strategy_filter = NULL;
    const char *cold_mode = NULL;

    if (argc > 1) {
        iterations = atoi(argv[1]);
    }
    if (argc > 2) {
        evict_kib = (size_t)strtoull(argv[2], NULL, 0);
    }
    if (argc > 3) {
        cpu = atoi(argv[3]);
    }
    if (argc > 4) {
        delay_filter = argv[4];
    }
    if (argc > 5) {
        strategy_filter = argv[5];
    }
    if (argc > 6) {
        cold_mode = argv[6];
        if (strstr(cold_mode, "flush_targets")) {
            g_flush_targets_each_iter = 1;
        }
        if (strstr(cold_mode, "flush_callpath")) {
            g_flush_call_path_each_iter = 1;
        }
        if (strstr(cold_mode, "one_target")) {
            g_measure_one_target = 1;
        }
    }
    if (iterations <= 0) {
        iterations = 200;
    }

    pin_to_cpu(cpu);
    elevate_realtime(80);
    lock_and_prefault(8ull * 1024 * 1024);
    setup_evictor(evict_kib * 1024ull);
    setup_chase_buffer(16ull * 1024 * 1024);

    fprintf(stderr, "INFO: CPU PREFETCHI support: %s\n", has_prefetchi() ? "yes" : "no");
    fprintf(stderr, "INFO: iterations=%d evict_kib=%zu cpu=%d\n", iterations, evict_kib, cpu);
    fprintf(stderr, "INFO: delay_filter=%s strategy_filter=%s\n",
            delay_filter ? delay_filter : "all",
            strategy_filter ? strategy_filter : "all");
    fprintf(stderr, "INFO: cold_mode=%s flush_targets=%d flush_callpath=%d\n",
            cold_mode ? cold_mode : "evict_only",
            g_flush_targets_each_iter,
            g_flush_call_path_each_iter);
    fprintf(stderr, "INFO: measure_one_target=%d\n", g_measure_one_target);
    fprintf(stderr, "INFO: targets bar=%p foo=%p baz=%p\n", (void *)bar, (void *)foo, (void *)baz);

    puts("strategy,delay,iters,evict_kib,mean,min,p05,p25,p50,p75,p95,p99,max");

    for (int d = 0; d < DELAY_COUNT; ++d) {
        if (!matches_filter(delay_name((DelayKind)d), delay_filter)) {
            continue;
        }
        for (int s = 0; s < STRATEGY_COUNT; ++s) {
            if (!matches_filter(strategy_name((StrategyKind)s), strategy_filter)) {
                continue;
            }
            Stats stats = run_one_case((StrategyKind)s, (DelayKind)d, iterations);
            print_stats_csv((StrategyKind)s, (DelayKind)d, iterations, evict_kib, &stats);
            free(stats.cycles);
        }
    }

    if (g_evict_code) {
        munmap(g_evict_code, g_evict_bytes);
    }
    if (g_chase) {
        munmap(g_chase, g_chase_len * sizeof(g_chase[0]));
    }
    return 0;
}
