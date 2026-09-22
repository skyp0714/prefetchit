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
typedef void (*VoidFn)(void);

static volatile int g_sink;
static volatile int g_branch_gate = 1;
static volatile uint64_t g_state = 0x9e3779b97f4a7c15ull;
static volatile uint64_t g_slow_branch_data[512] __attribute__((aligned(64)));
static volatile uint64_t g_slow_branch_mask;
typedef struct {
    volatile uintptr_t value;
    char pad[64 - sizeof(uintptr_t)];
} BranchChainLine;
static BranchChainLine g_branch_chain[8] __attribute__((aligned(64)));
static VoidFn volatile g_void_call_target;
static const char * volatile g_prefetch_ptrs[3];
static const char * volatile g_prefetch_one_ptr;
static uint32_t *g_chase;
static size_t g_chase_len;
static uint32_t g_chase_idx;
static int g_flush_targets_each_iter;
static int g_flush_call_path_each_iter;
static int g_measure_one_target;
static int g_measure_fixed_targets;
static int g_measure_bar_only;
static int g_collect_perf_each_iter;
static int g_measure_once_process;
static int g_shootdown_targets_each_iter;
static int g_measure_serial_entry;
static int g_collect_prepare_perf;
static PerfGroup g_perf_group = {
    .leader = -1,
    .l1i_miss = -1,
    .itlb_miss = -1,
    .itlb_stlb_hit = -1,
    .itlb_walk = -1,
    .dtlb_load_walk = -1,
    .l2_lines_in = -1,
    .l2_miss = -1,
    .l2_code_rd = -1,
    .l2_code_miss = -1,
    .l2_all_miss = -1,
    .llc_load_miss = -1,
    .llc_miss = -1,
    .branch_miss = -1
};

extern int bar(int);
extern int foo(int);
extern int baz(int);

static int call_measured_targets(int seed);
static void flush_target_code(void);
static void flush_code_range(const void *ptr, size_t bytes);
static void shootdown_code_page_tlb_strong(void (*fn)(void));
static void shootdown_target_code_tlb(void);
static void call_far_tlb_miss_pair(void);
static void call_far_tlb_miss_pair_cd(void);
static void prepare_far_tlb_miss_calls_strong(void);

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

#define PREFETCHI_T0_SYMBOL_LINES(symbol)  \
    do {                                   \
        PREFETCHI_T0_LINE(symbol, 0);      \
        PREFETCHI_T0_LINE(symbol, 64);     \
        PREFETCHI_T0_LINE(symbol, 128);    \
        PREFETCHI_T0_LINE(symbol, 192);    \
        PREFETCHI_T0_LINE(symbol, 256);    \
        PREFETCHI_T0_LINE(symbol, 320);    \
        PREFETCHI_T0_LINE(symbol, 384);    \
        PREFETCHI_T0_LINE(symbol, 448);    \
        PREFETCHI_T0_LINE(symbol, 512);    \
    } while (0)

#define PREFETCHI_T0_SYMBOL_LINES_REPEAT4(symbol) \
    do {                                          \
        PREFETCHI_T0_SYMBOL_LINES(symbol);        \
        PREFETCHI_T0_SYMBOL_LINES(symbol);        \
        PREFETCHI_T0_SYMBOL_LINES(symbol);        \
        PREFETCHI_T0_SYMBOL_LINES(symbol);        \
    } while (0)

#define PREFETCH_PAUSE_GAP(count)         \
    do {                                  \
        for (int gap_i = 0; gap_i < (count); ++gap_i) { \
            _mm_pause();                  \
        }                                 \
    } while (0)

#define PREFETCHI_T0_SYMBOL_LINES_SPACED(symbol, count) \
    do {                                                \
        PREFETCHI_T0_LINE(symbol, 0); PREFETCH_PAUSE_GAP(count);   \
        PREFETCHI_T0_LINE(symbol, 64); PREFETCH_PAUSE_GAP(count);  \
        PREFETCHI_T0_LINE(symbol, 128); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T0_LINE(symbol, 192); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T0_LINE(symbol, 256); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T0_LINE(symbol, 320); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T0_LINE(symbol, 384); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T0_LINE(symbol, 448); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T0_LINE(symbol, 512); PREFETCH_PAUSE_GAP(count); \
    } while (0)

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
        PREFETCHI_T0_LINE(bar, 512);        \
        PREFETCHI_T0_LINE(foo, 0);          \
        PREFETCHI_T0_LINE(foo, 64);         \
        PREFETCHI_T0_LINE(foo, 128);        \
        PREFETCHI_T0_LINE(foo, 192);        \
        PREFETCHI_T0_LINE(foo, 256);        \
        PREFETCHI_T0_LINE(foo, 320);        \
        PREFETCHI_T0_LINE(foo, 384);        \
        PREFETCHI_T0_LINE(foo, 448);        \
        PREFETCHI_T0_LINE(foo, 512);        \
        PREFETCHI_T0_LINE(baz, 0);          \
        PREFETCHI_T0_LINE(baz, 64);         \
        PREFETCHI_T0_LINE(baz, 128);        \
        PREFETCHI_T0_LINE(baz, 192);        \
        PREFETCHI_T0_LINE(baz, 256);        \
        PREFETCHI_T0_LINE(baz, 320);        \
        PREFETCHI_T0_LINE(baz, 384);        \
        PREFETCHI_T0_LINE(baz, 448);        \
        PREFETCHI_T0_LINE(baz, 512);        \
    } while (0)

#define PREFETCHI_T0_TARGET_LINES_SPACED(count) \
    do {                                        \
        PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, count); \
        PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, count); \
        PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, count); \
    } while (0)

#define PREFETCHI_T1_TARGETS()              \
    do {                                    \
        __builtin_ia32_prefetchi(bar, 2);   \
        __builtin_ia32_prefetchi(foo, 2);   \
        __builtin_ia32_prefetchi(baz, 2);   \
    } while (0)

#define PREFETCHI_T1_LINE(symbol, offset) \
    __builtin_ia32_prefetchi((const char *)(const void *)(symbol) + (offset), 2)

#define PREFETCHI_T1_SYMBOL_LINES(symbol)  \
    do {                                   \
        PREFETCHI_T1_LINE(symbol, 0);      \
        PREFETCHI_T1_LINE(symbol, 64);     \
        PREFETCHI_T1_LINE(symbol, 128);    \
        PREFETCHI_T1_LINE(symbol, 192);    \
        PREFETCHI_T1_LINE(symbol, 256);    \
        PREFETCHI_T1_LINE(symbol, 320);    \
        PREFETCHI_T1_LINE(symbol, 384);    \
        PREFETCHI_T1_LINE(symbol, 448);    \
        PREFETCHI_T1_LINE(symbol, 512);    \
    } while (0)

#define PREFETCHI_T1_SYMBOL_LINES_SPACED(symbol, count) \
    do {                                                \
        PREFETCHI_T1_LINE(symbol, 0); PREFETCH_PAUSE_GAP(count);   \
        PREFETCHI_T1_LINE(symbol, 64); PREFETCH_PAUSE_GAP(count);  \
        PREFETCHI_T1_LINE(symbol, 128); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T1_LINE(symbol, 192); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T1_LINE(symbol, 256); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T1_LINE(symbol, 320); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T1_LINE(symbol, 384); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T1_LINE(symbol, 448); PREFETCH_PAUSE_GAP(count); \
        PREFETCHI_T1_LINE(symbol, 512); PREFETCH_PAUSE_GAP(count); \
    } while (0)

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
        PREFETCHI_T1_LINE(bar, 512);        \
        PREFETCHI_T1_LINE(foo, 0);          \
        PREFETCHI_T1_LINE(foo, 64);         \
        PREFETCHI_T1_LINE(foo, 128);        \
        PREFETCHI_T1_LINE(foo, 192);        \
        PREFETCHI_T1_LINE(foo, 256);        \
        PREFETCHI_T1_LINE(foo, 320);        \
        PREFETCHI_T1_LINE(foo, 384);        \
        PREFETCHI_T1_LINE(foo, 448);        \
        PREFETCHI_T1_LINE(foo, 512);        \
        PREFETCHI_T1_LINE(baz, 0);          \
        PREFETCHI_T1_LINE(baz, 64);         \
        PREFETCHI_T1_LINE(baz, 128);        \
        PREFETCHI_T1_LINE(baz, 192);        \
        PREFETCHI_T1_LINE(baz, 256);        \
        PREFETCHI_T1_LINE(baz, 320);        \
        PREFETCHI_T1_LINE(baz, 384);        \
        PREFETCHI_T1_LINE(baz, 448);        \
        PREFETCHI_T1_LINE(baz, 512);        \
    } while (0)

#define PREFETCHI_T1_TARGET_LINES_SPACED(count) \
    do {                                        \
        PREFETCHI_T1_SYMBOL_LINES_SPACED(bar, count); \
        PREFETCHI_T1_SYMBOL_LINES_SPACED(foo, count); \
        PREFETCHI_T1_SYMBOL_LINES_SPACED(baz, count); \
    } while (0)

#define PREFETCHI_T0_TIMED_PATH()                       \
    do {                                                \
        __builtin_ia32_prefetchi(call_targets_indirect, 3); \
        PREFETCHI_T0_TARGETS();                         \
    } while (0)

#define PREFETCHI_T0_CALL_PATH_LINES()                       \
    do {                                                     \
        PREFETCHI_T0_LINE(call_targets_indirect, 0);          \
        PREFETCHI_T0_LINE(call_targets_indirect, 64);         \
        PREFETCHI_T0_LINE(call_targets_indirect, 128);        \
        PREFETCHI_T0_LINE(call_targets_indirect, 192);        \
        PREFETCHI_T0_LINE(call_measured_targets, 0);          \
        PREFETCHI_T0_LINE(call_measured_targets, 64);         \
        PREFETCHI_T0_LINE(call_measured_targets, 128);        \
        PREFETCHI_T0_LINE(call_measured_targets, 192);        \
    } while (0)

#define PREFETCHI_T0_FIXED_CALL_PATH_LINES()                 \
    do {                                                     \
        PREFETCHI_T0_LINE(call_targets_fixed, 0);             \
        PREFETCHI_T0_LINE(call_targets_fixed, 64);            \
        PREFETCHI_T0_LINE(call_targets_fixed, 128);           \
        PREFETCHI_T0_LINE(call_targets_fixed, 192);           \
        PREFETCHI_T0_LINE(call_measured_targets, 0);          \
        PREFETCHI_T0_LINE(call_measured_targets, 64);         \
        PREFETCHI_T0_LINE(call_measured_targets, 128);        \
        PREFETCHI_T0_LINE(call_measured_targets, 192);        \
    } while (0)

#define PREFETCHI_T0_TIMED_PATH_LINES() \
    do {                                \
        PREFETCHI_T0_CALL_PATH_LINES(); \
        PREFETCHI_T0_TARGET_LINES();    \
    } while (0)

#define PREFETCHI_T0_FIXED_TIMED_PATH_LINES() \
    do {                                      \
        PREFETCHI_T0_FIXED_CALL_PATH_LINES(); \
        PREFETCHI_T0_TARGET_LINES();          \
    } while (0)

#define PREFETCHI_T0_FIXED_TIMED_PATH_LINES_SPACED(count) \
    do {                                                  \
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();             \
        PREFETCH_PAUSE_GAP(count);                        \
        PREFETCHI_T0_TARGET_LINES_SPACED(count);          \
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

#define PREFETCHT0_TARGET_PAGE_TAILS()      \
    do {                                    \
        PREFETCHT0_TARGET_OFFSET(bar, 3584);\
        PREFETCHT0_TARGET_OFFSET(foo, 3584);\
        PREFETCHT0_TARGET_OFFSET(baz, 3584);\
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
        PREFETCHT0_TARGET_OFFSET(bar, 512); \
        PREFETCHT0_TARGET_OFFSET(foo, 0);   \
        PREFETCHT0_TARGET_OFFSET(foo, 64);  \
        PREFETCHT0_TARGET_OFFSET(foo, 128); \
        PREFETCHT0_TARGET_OFFSET(foo, 192); \
        PREFETCHT0_TARGET_OFFSET(foo, 256); \
        PREFETCHT0_TARGET_OFFSET(foo, 320); \
        PREFETCHT0_TARGET_OFFSET(foo, 384); \
        PREFETCHT0_TARGET_OFFSET(foo, 448); \
        PREFETCHT0_TARGET_OFFSET(foo, 512); \
        PREFETCHT0_TARGET_OFFSET(baz, 0);   \
        PREFETCHT0_TARGET_OFFSET(baz, 64);  \
        PREFETCHT0_TARGET_OFFSET(baz, 128); \
        PREFETCHT0_TARGET_OFFSET(baz, 192); \
        PREFETCHT0_TARGET_OFFSET(baz, 256); \
        PREFETCHT0_TARGET_OFFSET(baz, 320); \
        PREFETCHT0_TARGET_OFFSET(baz, 384); \
        PREFETCHT0_TARGET_OFFSET(baz, 448); \
        PREFETCHT0_TARGET_OFFSET(baz, 512); \
    } while (0)

#define PREFETCHT0_CALL_PATH_LINES()                 \
    do {                                             \
        PREFETCHT0_TARGET_OFFSET(call_targets_indirect, 0);   \
        PREFETCHT0_TARGET_OFFSET(call_targets_indirect, 64);  \
        PREFETCHT0_TARGET_OFFSET(call_measured_targets, 0);   \
        PREFETCHT0_TARGET_OFFSET(call_measured_targets, 64);  \
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

#define PREFETCHT1_TARGET_PAGE_TAILS()      \
    do {                                    \
        PREFETCHT1_TARGET_OFFSET(bar, 3584);\
        PREFETCHT1_TARGET_OFFSET(foo, 3584);\
        PREFETCHT1_TARGET_OFFSET(baz, 3584);\
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
        PREFETCHT1_TARGET_OFFSET(bar, 512); \
        PREFETCHT1_TARGET_OFFSET(foo, 0);   \
        PREFETCHT1_TARGET_OFFSET(foo, 64);  \
        PREFETCHT1_TARGET_OFFSET(foo, 128); \
        PREFETCHT1_TARGET_OFFSET(foo, 192); \
        PREFETCHT1_TARGET_OFFSET(foo, 256); \
        PREFETCHT1_TARGET_OFFSET(foo, 320); \
        PREFETCHT1_TARGET_OFFSET(foo, 384); \
        PREFETCHT1_TARGET_OFFSET(foo, 448); \
        PREFETCHT1_TARGET_OFFSET(foo, 512); \
        PREFETCHT1_TARGET_OFFSET(baz, 0);   \
        PREFETCHT1_TARGET_OFFSET(baz, 64);  \
        PREFETCHT1_TARGET_OFFSET(baz, 128); \
        PREFETCHT1_TARGET_OFFSET(baz, 192); \
        PREFETCHT1_TARGET_OFFSET(baz, 256); \
        PREFETCHT1_TARGET_OFFSET(baz, 320); \
        PREFETCHT1_TARGET_OFFSET(baz, 384); \
        PREFETCHT1_TARGET_OFFSET(baz, 448); \
        PREFETCHT1_TARGET_OFFSET(baz, 512); \
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

#define NOP7_TARGET_LINES_SPACED(count)                     \
    do {                                                    \
        for (int nop_i = 0; nop_i < 9; ++nop_i) {           \
            asm volatile(".byte 0x0f,0x1f,0x80,0,0,0,0" ::: "memory"); \
            PREFETCH_PAUSE_GAP(count);                      \
        }                                                   \
    } while (0)

#define NOP_GAP_10()                                        \
    asm volatile(".rept 10\n\t"                             \
                 "nop\n\t"                                 \
                 ".endr" ::: "memory")

#define PREFETCHI_T0_BURST4_SPACED32()                      \
    do {                                                    \
        PREFETCHI_T0_TARGET_LINES_SPACED(32);               \
        PREFETCHI_T0_TARGET_LINES_SPACED(32);               \
        PREFETCHI_T0_TARGET_LINES_SPACED(32);               \
        PREFETCHI_T0_TARGET_LINES_SPACED(32);               \
    } while (0)

#define PREFETCHI_T0_BURST8_SPACED32()                      \
    do {                                                    \
        PREFETCHI_T0_BURST4_SPACED32();                     \
        PREFETCHI_T0_BURST4_SPACED32();                     \
    } while (0)

#define PREFETCHI_T0_BURST4_SPACED128()                     \
    do {                                                    \
        PREFETCHI_T0_TARGET_LINES_SPACED(128);              \
        PREFETCHI_T0_TARGET_LINES_SPACED(128);              \
        PREFETCHI_T0_TARGET_LINES_SPACED(128);              \
        PREFETCHI_T0_TARGET_LINES_SPACED(128);              \
    } while (0)

#define PREFETCHI_T1_BURST4_SPACED32()                      \
    do {                                                    \
        PREFETCHI_T1_TARGET_LINES_SPACED(32);               \
        PREFETCHI_T1_TARGET_LINES_SPACED(32);               \
        PREFETCHI_T1_TARGET_LINES_SPACED(32);               \
        PREFETCHI_T1_TARGET_LINES_SPACED(32);               \
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

__attribute__((noinline, used, aligned(2048), section(".text.target.bar")))
static int bar_page_probe(int a) {
    asm volatile(".rept 16\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a ^ 0x11;
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_shape_lines(void) {
    NOP7_TARGET_LINES();
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_shape_spaced32_lines(void) {
    NOP7_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_prefetchit0_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES(bar);
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_prefetchit0_spaced32_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 32);
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_prefetchit0_spaced128_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 128);
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_prefetchit0_repeat4_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_REPEAT4(bar);
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_prefetchit1_lines(void) {
    PREFETCHI_T1_SYMBOL_LINES(bar);
}

__attribute__((noinline, used, aligned(64), section(".text.target.bar")))
static void bar_page_prefetchit1_spaced32_lines(void) {
    PREFETCHI_T1_SYMBOL_LINES_SPACED(bar, 32);
}

__attribute__((noinline, used, aligned(4096), section(".text.target.foo")))
int foo(int a) {
    asm volatile(".rept 512\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a + 3;
}

__attribute__((noinline, used, aligned(2048), section(".text.target.foo")))
static int foo_page_probe(int a) {
    asm volatile(".rept 16\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a ^ 0x33;
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_shape_lines(void) {
    NOP7_TARGET_LINES();
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_shape_spaced32_lines(void) {
    NOP7_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_prefetchit0_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES(foo);
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_prefetchit0_spaced32_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 32);
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_prefetchit0_spaced128_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 128);
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_prefetchit0_repeat4_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_REPEAT4(foo);
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_prefetchit1_lines(void) {
    PREFETCHI_T1_SYMBOL_LINES(foo);
}

__attribute__((noinline, used, aligned(64), section(".text.target.foo")))
static void foo_page_prefetchit1_spaced32_lines(void) {
    PREFETCHI_T1_SYMBOL_LINES_SPACED(foo, 32);
}

__attribute__((noinline, used, aligned(4096), section(".text.target.baz")))
int baz(int a) {
    asm volatile(".rept 512\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a + 7;
}

__attribute__((noinline, used, aligned(2048), section(".text.target.baz")))
static int baz_page_probe(int a) {
    asm volatile(".rept 16\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    return a ^ 0x77;
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_shape_lines(void) {
    NOP7_TARGET_LINES();
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_shape_spaced32_lines(void) {
    NOP7_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_prefetchit0_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES(baz);
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_prefetchit0_spaced32_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 32);
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_prefetchit0_spaced128_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 128);
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_prefetchit0_repeat4_lines(void) {
    PREFETCHI_T0_SYMBOL_LINES_REPEAT4(baz);
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_prefetchit1_lines(void) {
    PREFETCHI_T1_SYMBOL_LINES(baz);
}

__attribute__((noinline, used, aligned(64), section(".text.target.baz")))
static void baz_page_prefetchit1_spaced32_lines(void) {
    PREFETCHI_T1_SYMBOL_LINES_SPACED(baz, 32);
}

__attribute__((noinline, used))
static void call_target_page_probes(int seed) {
    int v = seed;
    v = bar_page_probe(v);
    v = foo_page_probe(v);
    v = baz_page_probe(v);
    g_sink = v;
}

__attribute__((noinline, used))
static void call_target_page_shapes(void) {
    bar_page_shape_lines();
    foo_page_shape_lines();
    baz_page_shape_lines();
}

__attribute__((noinline, used))
static void call_target_page_shape_spaced32_lines(void) {
    bar_page_shape_spaced32_lines();
    foo_page_shape_spaced32_lines();
    baz_page_shape_spaced32_lines();
}

__attribute__((noinline, used))
static void call_target_page_prefetchit0_lines(void) {
    bar_page_prefetchit0_lines();
    foo_page_prefetchit0_lines();
    baz_page_prefetchit0_lines();
}

__attribute__((noinline, used))
static void call_target_page_prefetchit0_spaced32_lines(void) {
    bar_page_prefetchit0_spaced32_lines();
    foo_page_prefetchit0_spaced32_lines();
    baz_page_prefetchit0_spaced32_lines();
}

__attribute__((noinline, used))
static void call_target_page_prefetchit0_spaced128_lines(void) {
    bar_page_prefetchit0_spaced128_lines();
    foo_page_prefetchit0_spaced128_lines();
    baz_page_prefetchit0_spaced128_lines();
}

__attribute__((noinline, used))
static void call_target_page_prefetchit0_repeat4_lines(void) {
    bar_page_prefetchit0_repeat4_lines();
    foo_page_prefetchit0_repeat4_lines();
    baz_page_prefetchit0_repeat4_lines();
}

__attribute__((noinline, used))
static void call_target_page_prefetchit1_lines(void) {
    bar_page_prefetchit1_lines();
    foo_page_prefetchit1_lines();
    baz_page_prefetchit1_lines();
}

__attribute__((noinline, used))
static void call_target_page_prefetchit1_spaced32_lines(void) {
    bar_page_prefetchit1_spaced32_lines();
    foo_page_prefetchit1_spaced32_lines();
    baz_page_prefetchit1_spaced32_lines();
}

__attribute__((noinline, used, aligned(4096), section(".text.target.zz_adjacent_prefetch")))
static void adjacent_target_shape_spaced32_lines(void) {
    NOP7_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(4096), section(".text.target.zz_adjacent_prefetch")))
static void adjacent_target_prefetchit0_spaced32_lines(void) {
    PREFETCHI_T0_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(4096), section(".text.target.zz_adjacent_prefetch")))
static void adjacent_target_prefetchit0_spaced128_lines(void) {
    PREFETCHI_T0_TARGET_LINES_SPACED(128);
}

__attribute__((noinline, used, aligned(4096), section(".text.target.zz_adjacent_prefetch")))
static void adjacent_target_prefetchit1_spaced32_lines(void) {
    PREFETCHI_T1_TARGET_LINES_SPACED(32);
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
static int call_targets_fixed(int seed) {
    int v = seed;
    v = bar(v);
    v = foo(v);
    v = baz(v);
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

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t0_burst4_spaced32")))
static void prefetchi_target_lines_t0_burst4_spaced32(void) {
    PREFETCHI_T0_BURST4_SPACED32();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t0_burst8_spaced32")))
static void prefetchi_target_lines_t0_burst8_spaced32(void) {
    PREFETCHI_T0_BURST8_SPACED32();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t0_burst4_spaced128")))
static void prefetchi_target_lines_t0_burst4_spaced128(void) {
    PREFETCHI_T0_BURST4_SPACED128();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t1_burst4_spaced32")))
static void prefetchi_target_lines_t1_burst4_spaced32(void) {
    PREFETCHI_T1_BURST4_SPACED32();
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t0_repeat16")))
static void prefetchi_target_lines_t0_repeat16(void) {
    for (int i = 0; i < 16; ++i) {
        PREFETCHI_T0_TARGET_LINES();
        asm volatile("" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t0_repeat64")))
static void prefetchi_target_lines_t0_repeat64(void) {
    for (int i = 0; i < 64; ++i) {
        PREFETCHI_T0_TARGET_LINES();
        asm volatile("" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.prefetchi.lines_t1_repeat16")))
static void prefetchi_target_lines_t1_repeat16(void) {
    for (int i = 0; i < 16; ++i) {
        PREFETCHI_T1_TARGET_LINES();
        asm volatile("" ::: "memory");
    }
}

__attribute__((noinline, used))
static void prefetchi_target_lines_t0_spaced(int pause_count) {
    const char *targets[3] = {
        (const char *)(const void *)bar,
        (const char *)(const void *)foo,
        (const char *)(const void *)baz
    };
    for (int target = 0; target < 3; ++target) {
        for (int offset = 0; offset <= 512; offset += 64) {
            __builtin_ia32_prefetchi(targets[target] + offset, 3);
            for (int i = 0; i < pause_count; ++i) {
                _mm_pause();
            }
        }
    }
}

__attribute__((noinline, used))
static void prefetchi_target_lines_t1_spaced(int pause_count) {
    const char *targets[3] = {
        (const char *)(const void *)bar,
        (const char *)(const void *)foo,
        (const char *)(const void *)baz
    };
    for (int target = 0; target < 3; ++target) {
        for (int offset = 0; offset <= 512; offset += 64) {
            __builtin_ia32_prefetchi(targets[target] + offset, 2);
            for (int i = 0; i < pause_count; ++i) {
                _mm_pause();
            }
        }
    }
}

__attribute__((noinline, used))
static void prefetchi_target_lines_t0_arith_gap(int gap_rounds) {
    const char *targets[3] = {
        (const char *)(const void *)bar,
        (const char *)(const void *)foo,
        (const char *)(const void *)baz
    };
    uint64_t x = g_state + 0x9e3779b97f4a7c15ull;
    for (int target = 0; target < 3; ++target) {
        for (int offset = 0; offset <= 512; offset += 64) {
            __builtin_ia32_prefetchi(targets[target] + offset, 3);
            for (int i = 0; i < gap_rounds; ++i) {
                x = x * 2862933555777941757ull + 3037000493ull;
                asm volatile("" : "+r"(x) :: "memory");
            }
        }
    }
    g_state ^= x;
}

__attribute__((noinline, used))
static void prefetchi_target_lines_t1_arith_gap(int gap_rounds) {
    const char *targets[3] = {
        (const char *)(const void *)bar,
        (const char *)(const void *)foo,
        (const char *)(const void *)baz
    };
    uint64_t x = g_state + 0xd1b54a32d192ed03ull;
    for (int target = 0; target < 3; ++target) {
        for (int offset = 0; offset <= 512; offset += 64) {
            __builtin_ia32_prefetchi(targets[target] + offset, 2);
            for (int i = 0; i < gap_rounds; ++i) {
                x = (x ^ (x >> 29)) * 6364136223846793005ull + 1442695040888963407ull;
                asm volatile("" : "+r"(x) :: "memory");
            }
        }
    }
    g_state ^= x;
}

__attribute__((noinline, used))
static void prefetchi_target_lines_t0_control_gap(int gap_rounds) {
    const char *targets[3] = {
        (const char *)(const void *)bar,
        (const char *)(const void *)foo,
        (const char *)(const void *)baz
    };
    uint64_t x = g_state ^ 0xa0761d6478bd642full;
    for (int target = 0; target < 3; ++target) {
        for (int offset = 0; offset <= 512; offset += 64) {
            __builtin_ia32_prefetchi(targets[target] + offset, 3);
            for (int i = 0; i < gap_rounds; ++i) {
                x = x * 1664525ull + 1013904223ull + (uint64_t)i;
                if (x & 0x80000000ull) {
                    x ^= x >> 7;
                } else {
                    x += x << 3;
                }
                asm volatile("" : "+r"(x) :: "memory", "cc");
            }
        }
    }
    g_state ^= x;
}

__attribute__((noinline, used))
static void nofetch_target_lines_spaced(int pause_count) {
    for (int target = 0; target < 3; ++target) {
        for (int offset = 0; offset <= 512; offset += 64) {
            (void)target;
            (void)offset;
            asm volatile(".byte 0x0f,0x1f,0x80,0,0,0,0" ::: "memory");
            for (int i = 0; i < pause_count; ++i) {
                _mm_pause();
            }
        }
    }
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

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_path_lines")))
static void farcall_prefetchit0_path_lines(void) {
    PREFETCHI_T0_TIMED_PATH_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_lines")))
static void farcall_prefetchit1_lines(void) {
    PREFETCHI_T1_TARGET_LINES();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_frontend_stall_tiny")))
static void farcall_frontend_stall_tiny(void) {
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_frontend_stall_small")))
static void farcall_frontend_stall_small(void) {
    asm volatile(".rept 1024\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_frontend_stall_big")))
static void farcall_frontend_stall_big(void) {
    asm volatile(".rept 4096\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_frontend_stall_huge")))
static void farcall_frontend_stall_huge(void) {
    asm volatile(".rept 16384\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_far_tlb_miss_a")))
static void farcall_tlb_miss_a(void) {
    asm volatile("nop" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_far_tlb_miss_b")))
static void farcall_tlb_miss_b(void) {
    asm volatile("nop" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_far_tlb_miss_c")))
static void farcall_tlb_miss_c(void) {
    asm volatile("nop" ::: "memory");
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_far_tlb_miss_d")))
static void farcall_tlb_miss_d(void) {
    asm volatile("nop" ::: "memory");
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

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_path_lines_repeat")))
static void farcall_prefetchit0_path_lines_repeat(void) {
    PREFETCHI_T0_TIMED_PATH_LINES();
    asm volatile(".rept 64\n\t"
                 "nop\n\t"
                 ".endr" ::: "memory");
    PREFETCHI_T0_TIMED_PATH_LINES();
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

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_shape_lines_spaced128")))
static void farcall_lines_spaced128_shape(void) {
    NOP7_TARGET_LINES_SPACED(128);
    NOP7_TARGET_LINES_SPACED(128);
    NOP7_TARGET_LINES_SPACED(128);
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_lines_spaced32")))
static void farcall_prefetchit0_lines_spaced32(void) {
    PREFETCHI_T0_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_lines_spaced128")))
static void farcall_prefetchit0_lines_spaced128(void) {
    PREFETCHI_T0_TARGET_LINES_SPACED(128);
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_burst4_spaced32")))
static void farcall_prefetchit0_burst4_spaced32(void) {
    PREFETCHI_T0_BURST4_SPACED32();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_burst8_spaced32")))
static void farcall_prefetchit0_burst8_spaced32(void) {
    PREFETCHI_T0_BURST8_SPACED32();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t0_burst4_spaced128")))
static void farcall_prefetchit0_burst4_spaced128(void) {
    PREFETCHI_T0_BURST4_SPACED128();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_lines_spaced32")))
static void farcall_prefetchit1_lines_spaced32(void) {
    PREFETCHI_T1_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_far_t1_burst4_spaced32")))
static void farcall_prefetchit1_burst4_spaced32(void) {
    PREFETCHI_T1_BURST4_SPACED32();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_call_window_pre10_t0")))
static void call_window_prefetchit0_pre10(void) {
    PREFETCHI_T0_TARGET_LINES_SPACED(32);
    NOP_GAP_10();
    farcall_frontend_stall_big();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_call_window_post10_t0")))
static void call_window_prefetchit0_post10(void) {
    farcall_frontend_stall_big();
    NOP_GAP_10();
    PREFETCHI_T0_TARGET_LINES_SPACED(32);
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_call_window_pre10_t0_burst4")))
static void call_window_prefetchit0_burst4_pre10(void) {
    PREFETCHI_T0_BURST4_SPACED32();
    NOP_GAP_10();
    farcall_frontend_stall_big();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_call_window_post10_t0_burst4")))
static void call_window_prefetchit0_burst4_post10(void) {
    farcall_frontend_stall_big();
    NOP_GAP_10();
    PREFETCHI_T0_BURST4_SPACED32();
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_call_window_pre10_t1_burst4")))
static void call_window_prefetchit1_burst4_pre10(void) {
    PREFETCHI_T1_BURST4_SPACED32();
    NOP_GAP_10();
    farcall_frontend_stall_big();
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

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_t0_lines")))
static void trained_branch_prefetchit0_lines_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        PREFETCHI_T0_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_call_t0_lines")))
static void trained_branch_call_prefetchit0_lines_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        farcall_prefetchit0_lines();
    } else {
        farcall_lines_shape();
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_call_t0_path_lines")))
static void trained_branch_call_prefetchit0_path_lines_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        farcall_prefetchit0_path_lines();
    } else {
        farcall_lines_shape();
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_train_far_after_t0")))
static void trained_branch_to_frontend_stall_once(int take_path) {
    if (__builtin_expect(take_path, 0)) {
        farcall_frontend_stall_big();
    } else {
        asm volatile(".rept 64\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_t0_lines")))
static void slow_branch_wrongpath_prefetchit0_lines_once(void) {
    if (__builtin_expect(g_branch_gate, 1)) {
        PREFETCHI_T0_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_t0_path_lines")))
static void slow_branch_wrongpath_prefetchit0_path_lines_once(void) {
    if (__builtin_expect(g_branch_gate, 1)) {
        PREFETCHI_T0_TIMED_PATH_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_t1_lines")))
static void slow_branch_wrongpath_prefetchit1_lines_once(void) {
    if (__builtin_expect(g_branch_gate, 1)) {
        PREFETCHI_T1_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
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

__attribute__((noinline, used))
static void trained_branch_prefetchit0_lines(void) {
    for (int i = 0; i < 128; ++i) {
        trained_branch_prefetchit0_lines_once(0);
    }
    trained_branch_prefetchit0_lines_once(1);
}

__attribute__((noinline, used))
static void trained_branch_call_prefetchit0_lines(void) {
    for (int i = 0; i < 96; ++i) {
        trained_branch_call_prefetchit0_lines_once(0);
    }
    trained_branch_call_prefetchit0_lines_once(1);
}

__attribute__((noinline, used))
static void trained_branch_call_prefetchit0_path_lines(void) {
    for (int i = 0; i < 96; ++i) {
        trained_branch_call_prefetchit0_path_lines_once(0);
    }
    trained_branch_call_prefetchit0_path_lines_once(1);
}

__attribute__((noinline, used))
static void train_branch_to_frontend_stall_not_taken(void) {
    for (int i = 0; i < 128; ++i) {
        trained_branch_to_frontend_stall_once(0);
    }
}

__attribute__((noinline, used))
static void train_wrongpath_branch_taken_t0_lines(void) {
    g_branch_gate = 1;
    for (int i = 0; i < 128; ++i) {
        slow_branch_wrongpath_prefetchit0_lines_once();
    }
}

__attribute__((noinline, used))
static void train_wrongpath_branch_taken_t0_path_lines(void) {
    g_branch_gate = 1;
    for (int i = 0; i < 128; ++i) {
        slow_branch_wrongpath_prefetchit0_path_lines_once();
    }
}

__attribute__((noinline, used))
static void train_wrongpath_branch_taken_t1_lines(void) {
    g_branch_gate = 1;
    for (int i = 0; i < 128; ++i) {
        slow_branch_wrongpath_prefetchit1_lines_once();
    }
}

static void flush_branch_gate_zero(void) {
    g_branch_gate = 0;
    _mm_clflush((const void *)&g_branch_gate);
    asm volatile("mfence\n\tlfence" ::: "memory");
}

static void prepare_slow_branch_false_condition(void) {
    g_branch_gate = 0;
    g_slow_branch_mask = 0;
    for (int i = 0; i < 64; ++i) {
        g_slow_branch_data[(size_t)i * 8u] = 0;
    }
    _mm_clflush((const void *)&g_branch_gate);
    _mm_clflush((const void *)&g_slow_branch_mask);
    for (int i = 0; i < 64; ++i) {
        _mm_clflush((const void *)&g_slow_branch_data[(size_t)i * 8u]);
    }
    asm volatile("mfence\n\tlfence" ::: "memory");
}

static void prepare_slow_branch_true_condition(void) {
    g_branch_gate = 1;
    g_slow_branch_mask = 0;
    for (int i = 0; i < 64; ++i) {
        g_slow_branch_data[(size_t)i * 8u] = 0;
    }
    _mm_clflush((const void *)&g_branch_gate);
    _mm_clflush((const void *)&g_slow_branch_mask);
    for (int i = 0; i < 64; ++i) {
        _mm_clflush((const void *)&g_slow_branch_data[(size_t)i * 8u]);
    }
    asm volatile("mfence\n\tlfence" ::: "memory");
}

__attribute__((noinline, used))
static uint64_t slow_branch_dependency(void) {
    uint64_t x = g_slow_branch_data[0];
    for (int i = 0; i < 16; ++i) {
        size_t idx = (size_t)((x + (uint64_t)i * 17ull) & 63ull) * 8u;
        x = g_slow_branch_data[idx];
    }
    return x & g_slow_branch_mask;
}

__attribute__((noinline, used))
static uint64_t slow_branch_dependency_deep(void) {
    uint64_t x = g_slow_branch_data[0];
    for (int i = 0; i < 64; ++i) {
        size_t idx = (size_t)((x + (uint64_t)i * 17ull) & 63ull) * 8u;
        x = g_slow_branch_data[idx];
    }
    return x & g_slow_branch_mask;
}

static void prepare_chase_branch_false_condition(int steps) {
    g_branch_gate = 0;
    g_slow_branch_mask = 0;
    _mm_clflush((const void *)&g_branch_gate);
    _mm_clflush((const void *)&g_slow_branch_mask);
    if (g_chase && g_chase_len > 0) {
        uint32_t idx = g_chase_idx;
        for (int i = 0; i < steps; ++i) {
            uint32_t next = g_chase[idx];
            _mm_clflush((const void *)&g_chase[idx]);
            idx = next;
        }
    }
    asm volatile("mfence\n\tlfence" ::: "memory");
}

__attribute__((noinline, used))
static uint64_t chase_branch_dependency(int steps) {
    uint32_t idx = g_chase_idx;
    if (g_chase && g_chase_len > 0) {
        for (int i = 0; i < steps; ++i) {
            idx = g_chase[idx];
            asm volatile("" : "+r"(idx) :: "memory");
        }
        g_chase_idx = idx;
    }
    return (uint64_t)idx & g_slow_branch_mask;
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_t0_lines")))
static void data_slow_branch_wrongpath_prefetchit0_lines_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency()) != 0, 1)) {
        PREFETCHI_T0_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_t0_path_lines")))
static void data_slow_branch_wrongpath_prefetchit0_path_lines_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency()) != 0, 1)) {
        PREFETCHI_T0_TIMED_PATH_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_t1_lines")))
static void data_slow_branch_wrongpath_prefetchit1_lines_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency()) != 0, 1)) {
        PREFETCHI_T1_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_deep_t0_repeat4")))
static void data_deep_branch_wrongpath_prefetchit0_repeat4_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency_deep()) != 0, 1)) {
        for (int i = 0; i < 4; ++i) {
            PREFETCHI_T0_TARGET_LINES();
        }
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_deep_t0_spaced32")))
static void data_deep_branch_wrongpath_prefetchit0_spaced32_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency_deep()) != 0, 1)) {
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

static void set_prefetch_ptrs_to_targets(void) {
    g_prefetch_ptrs[0] = (const char *)(const void *)bar;
    g_prefetch_ptrs[1] = (const char *)(const void *)foo;
    g_prefetch_ptrs[2] = (const char *)(const void *)baz;
}

static void set_prefetch_ptrs_to_dummy(void) {
    g_prefetch_ptrs[0] = (const char *)(const void *)farcall_tlb_miss_a;
    g_prefetch_ptrs[1] = (const char *)(const void *)farcall_tlb_miss_b;
    g_prefetch_ptrs[2] = (const char *)(const void *)farcall_tlb_miss_c;
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_ptr_t0_spaced32")))
static void ptr_deep_branch_wrongpath_prefetchit0_spaced32_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency_deep()) != 0, 1)) {
        for (int target = 0; target < 3; ++target) {
            const char *base = g_prefetch_ptrs[target];
            for (int offset = 0; offset <= 512; offset += 64) {
                __builtin_ia32_prefetchi(base + offset, 3);
                PREFETCH_PAUSE_GAP(32);
            }
        }
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_ptr_one_t0_spaced32")))
static void ptr_one_deep_branch_wrongpath_prefetchit0_spaced32_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency_deep()) != 0, 1)) {
        const char *base = g_prefetch_one_ptr;
        for (int offset = 0; offset <= 512; offset += 64) {
            __builtin_ia32_prefetchi(base + offset, 3);
            PREFETCH_PAUSE_GAP(32);
        }
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_deep_t1_spaced32")))
static void data_deep_branch_wrongpath_prefetchit1_spaced32_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency_deep()) != 0, 1)) {
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_t0_bar")))
static void data_slow_branch_wrongpath_prefetchit0_bar_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency()) != 0, 1)) {
        PREFETCHI_T0_SYMBOL_LINES(bar);
    } else {
        asm volatile(".rept 128\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_t0_foo")))
static void data_slow_branch_wrongpath_prefetchit0_foo_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency()) != 0, 1)) {
        PREFETCHI_T0_SYMBOL_LINES(foo);
    } else {
        asm volatile(".rept 128\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_data_t0_baz")))
static void data_slow_branch_wrongpath_prefetchit0_baz_once(void) {
    if (__builtin_expect((g_branch_gate | (int)slow_branch_dependency()) != 0, 1)) {
        PREFETCHI_T0_SYMBOL_LINES(baz);
    } else {
        asm volatile(".rept 128\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_chase_t0_lines")))
static void chase_branch_wrongpath_prefetchit0_lines_once(int steps) {
    if (__builtin_expect((g_branch_gate | (int)chase_branch_dependency(steps)) != 0, 1)) {
        PREFETCHI_T0_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_wrongpath_chase_t1_lines")))
static void chase_branch_wrongpath_prefetchit1_lines_once(int steps) {
    if (__builtin_expect((g_branch_gate | (int)chase_branch_dependency(steps)) != 0, 1)) {
        PREFETCHI_T1_TARGET_LINES();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_inline_chase_t0_burst4")))
static void inline_chase_branch_prefetchit0_burst4_once(int steps) {
    uint32_t idx = g_chase_idx;
    if (g_chase && g_chase_len > 0) {
        for (int i = 0; i < steps; ++i) {
            idx = g_chase[idx];
            asm volatile("" : "+r"(idx) :: "memory");
        }
        g_chase_idx = idx;
    }

    if (__builtin_expect((g_branch_gate | (int)(idx & (uint32_t)g_slow_branch_mask)) != 0, 1)) {
        PREFETCHI_T0_BURST4_SPACED32();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_inline_chase_t0_fixed_burst4")))
static void inline_chase_branch_prefetchit0_fixed_burst4_once(int steps) {
    uint32_t idx = g_chase_idx;
    if (g_chase && g_chase_len > 0) {
        for (int i = 0; i < steps; ++i) {
            idx = g_chase[idx];
            asm volatile("" : "+r"(idx) :: "memory");
        }
        g_chase_idx = idx;
    }

    if (__builtin_expect((g_branch_gate | (int)(idx & (uint32_t)g_slow_branch_mask)) != 0, 1)) {
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();
        PREFETCHI_T0_BURST4_SPACED32();
    } else {
        asm volatile(".rept 256\n\t"
                     "nop\n\t"
                     ".endr" ::: "memory");
    }
}

__attribute__((noinline, used))
static void train_inline_chase_branch_prefetchit0_burst4(void) {
    g_branch_gate = 1;
    g_slow_branch_mask = 0;
    for (int i = 0; i < 96; ++i) {
        inline_chase_branch_prefetchit0_burst4_once(8);
    }
}

__attribute__((noinline, used))
static void train_inline_chase_branch_prefetchit0_fixed_burst4(void) {
    g_branch_gate = 1;
    g_slow_branch_mask = 0;
    for (int i = 0; i < 96; ++i) {
        inline_chase_branch_prefetchit0_fixed_burst4_once(8);
    }
}

__attribute__((noinline, used))
static void train_data_wrongpath_taken_t0_lines(void) {
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 96; ++i) {
        data_slow_branch_wrongpath_prefetchit0_lines_once();
    }
}

__attribute__((noinline, used))
static void train_data_wrongpath_taken_t1_lines(void) {
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 96; ++i) {
        data_slow_branch_wrongpath_prefetchit1_lines_once();
    }
}

__attribute__((noinline, used))
static void train_data_deep_wrongpath_taken_t0_repeat4(void) {
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 48; ++i) {
        data_deep_branch_wrongpath_prefetchit0_repeat4_once();
    }
}

__attribute__((noinline, used))
static void train_data_deep_wrongpath_taken_t0_spaced32(void) {
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 48; ++i) {
        data_deep_branch_wrongpath_prefetchit0_spaced32_once();
    }
}

__attribute__((noinline, used))
static void train_data_deep_wrongpath_taken_t1_spaced32(void) {
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 48; ++i) {
        data_deep_branch_wrongpath_prefetchit1_spaced32_once();
    }
}

__attribute__((noinline, used))
static void train_ptr_deep_wrongpath_dummy_t0_spaced32(void) {
    set_prefetch_ptrs_to_dummy();
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 64; ++i) {
        ptr_deep_branch_wrongpath_prefetchit0_spaced32_once();
    }
}

__attribute__((noinline, used))
static void train_ptr_one_deep_wrongpath_dummy_t0_spaced32(void) {
    g_prefetch_one_ptr = (const char *)(const void *)farcall_tlb_miss_a;
    prepare_slow_branch_true_condition();
    for (int i = 0; i < 64; ++i) {
        ptr_one_deep_branch_wrongpath_prefetchit0_spaced32_once();
    }
}

static void issue_ptr_one_deep_wrongpath_target_t0_spaced32(const void *target) {
    train_ptr_one_deep_wrongpath_dummy_t0_spaced32();
    flush_code_range(target, 1024);
    shootdown_code_page_tlb_strong((void (*)(void))target);
    prepare_slow_branch_false_condition();
    g_prefetch_one_ptr = (const char *)target;
    serialize_cpuid();
    ptr_one_deep_branch_wrongpath_prefetchit0_spaced32_once();
}

__attribute__((noinline, used))
static void trained_indirect_call_prefetchit0_lines(void) {
    g_void_call_target = farcall_lines_shape;
    for (int i = 0; i < 128; ++i) {
        VoidFn fn = g_void_call_target;
        fn();
    }
    g_void_call_target = farcall_prefetchit0_lines;
    asm volatile("" ::: "memory");
    VoidFn fn = g_void_call_target;
    fn();
}

__attribute__((noinline, used))
static void trained_indirect_call_prefetchit0_path_lines(void) {
    g_void_call_target = farcall_lines_shape;
    for (int i = 0; i < 128; ++i) {
        VoidFn fn = g_void_call_target;
        fn();
    }
    g_void_call_target = farcall_prefetchit0_path_lines;
    asm volatile("" ::: "memory");
    VoidFn fn = g_void_call_target;
    fn();
}

__attribute__((noinline, used))
static void train_indirect_frontend_stall_to_tiny(void) {
    g_void_call_target = farcall_frontend_stall_tiny;
    for (int i = 0; i < 128; ++i) {
        VoidFn fn = g_void_call_target;
        fn();
    }
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_complex_t0_lines")))
static void complex_control_prefetchit0_lines(uint64_t seed) {
    uint64_t x = seed ^ g_state;
    for (int i = 0; i < 48; ++i) {
        x ^= x << 13;
        x ^= x >> 7;
        if ((x >> ((i * 7) & 63)) & 1u) {
            x = x * 0x9e3779b185ebca87ull + (uint64_t)i;
            asm volatile(".rept 8\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        } else {
            x ^= (x >> 17) + 0xd1b54a32d192ed03ull;
            asm volatile(".rept 16\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        }
    }
    PREFETCHI_T0_TARGET_LINES();
    g_state = x;
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_complex_t0_path_lines")))
static void complex_control_prefetchit0_path_lines(uint64_t seed) {
    uint64_t x = seed ^ (g_state << 1);
    for (int i = 0; i < 64; ++i) {
        x ^= x << 9;
        x ^= x >> 11;
        if ((x + (uint64_t)i) & 0x80u) {
            x = (x << 3) ^ 0xa0761d6478bd642full;
            asm volatile(".rept 8\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        } else {
            x = (x >> 5) ^ 0xe7037ed1a0b428dbull;
            asm volatile(".rept 20\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        }
    }
    PREFETCHI_T0_TIMED_PATH_LINES();
    g_state = x;
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_nested_t0_scatter")))
static void nested_branch_prefetchit0_scatter(uint64_t seed, int far_mode) {
    uint64_t x = seed ^ g_state ^ slow_branch_dependency_deep();

    PREFETCHI_T0_TARGET_LINES_SPACED(32);
    if ((x & 1u) == 0) {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 16);
        x = (x * 0x9e3779b185ebca87ull) + 0xd1b54a32d192ed03ull;
        if ((x >> 7) & 1u) {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
        } else {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 16);
        }
    } else {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
        x ^= (x << 13) + 0xa0761d6478bd642full;
        if ((x >> 11) & 1u) {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 16);
        } else {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 16);
        }
    }

    if (far_mode) {
        call_far_tlb_miss_pair();
    }

    for (int i = 0; i < 10; ++i) {
        x ^= x << 9;
        x ^= x >> 7;
        x *= 0x27bb2ee687b0b0fdull;
        if ((x >> ((i * 5) & 63)) & 1u) {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 8);
            if ((x + (uint64_t)i) & 0x40u) {
                PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 8);
            } else {
                PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 8);
            }
        } else {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 8);
            if ((x ^ (uint64_t)i) & 0x80u) {
                PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 8);
            } else {
                PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 8);
            }
        }
        if (far_mode == 2 && (i == 2 || i == 6)) {
            call_far_tlb_miss_pair_cd();
        }
        asm volatile("" : "+r"(x) :: "memory");
    }

    PREFETCHI_T0_TARGET_LINES_SPACED(64);
    if (far_mode == 3) {
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(128);
        call_far_tlb_miss_pair_cd();
    }
    g_state ^= x;
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_nested_t0_per_target")))
static void nested_branch_prefetchit0_per_target(uint64_t seed, int far_mode) {
    uint64_t x = seed ^ (g_state << 1) ^ slow_branch_dependency();

    PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 32);
    if ((x & 3u) != 0) {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 64);
    } else {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
    }
    if (far_mode) {
        farcall_tlb_miss_a();
    }

    x = (x << 17) ^ (x >> 9) ^ 0xe7037ed1a0b428dbull;
    PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 32);
    if ((x & 5u) == 1u) {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 16);
    } else {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 64);
    }
    if (far_mode) {
        farcall_tlb_miss_b();
    }

    x = (x * 0x5851f42d4c957f2dull) + 0x14057b7ef767814full;
    PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 32);
    if ((x >> 13) & 1u) {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 16);
    } else {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 64);
    }
    if (far_mode) {
        call_far_tlb_miss_pair_cd();
    }

    PREFETCHI_T0_TARGET_LINES_SPACED(128);
    g_state += x;
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_nested_window_t0")))
static void nested_branch_prefetchit0_window(uint64_t seed, int mode) {
    uint64_t x = seed ^ g_state ^ slow_branch_dependency_deep();

    if ((x & 1u) == 0) {
        if ((x >> 3) & 1u) {
            asm volatile(".rept 32\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        } else {
            asm volatile(".rept 64\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        }
    } else {
        if ((x >> 5) & 1u) {
            asm volatile(".rept 96\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        } else {
            asm volatile(".rept 128\n\t"
                         "nop\n\t"
                         ".endr" ::: "memory");
        }
    }

    if (mode == 2) {
        call_far_tlb_miss_pair();
    }

    PREFETCHI_T0_TARGET_LINES_SPACED(32);
    if ((x >> 7) & 1u) {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 16);
        if ((x >> 13) & 1u) {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
        }
    } else {
        PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 16);
        if ((x >> 17) & 1u) {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
        }
    }
    PREFETCHI_T0_TARGET_LINES_SPACED(32);

    if (mode == 1) {
        farcall_tlb_miss_a();
        PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 32);
        farcall_tlb_miss_b();
        PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 32);
        call_far_tlb_miss_pair_cd();
        PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 32);
    } else {
        call_far_tlb_miss_pair();
    }

    if (mode == 2) {
        PREFETCHI_T0_TARGET_LINES_SPACED(64);
        call_far_tlb_miss_pair_cd();
    }

    g_state ^= x + (uint64_t)mode;
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_prefetch_branch_actual_t0")))
static void branch_actual_prefetchit0_window(uint64_t seed, int mode) {
    uint64_t dep = slow_branch_dependency_deep();
    uint64_t x = seed ^ g_state ^ dep;

    if (__builtin_expect((g_branch_gate | (int)dep) == 0, 1)) {
        asm volatile("" ::: "memory");
    } else {
        if (mode == 1) {
            call_far_tlb_miss_pair();
        }

        PREFETCHI_T0_TARGET_LINES_SPACED(32);

        if (mode == 2) {
            if ((x >> 3) & 1u) {
                PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 16);
                PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
            } else {
                PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 16);
                PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
            }
        }

        PREFETCHI_T0_TARGET_LINES_SPACED(32);

        if (mode == 3) {
            call_far_tlb_miss_pair();
            PREFETCHI_T0_TARGET_LINES_SPACED(32);
            call_far_tlb_miss_pair_cd();
        } else {
            call_far_tlb_miss_pair_cd();
        }
    }

    g_state += x + (uint64_t)mode;
}

__attribute__((noinline, used))
static void train_branch_actual_prefetchit0_window(void) {
    g_branch_gate = 0;
    g_slow_branch_mask = 0;
    for (int i = 0; i < 96; ++i) {
        branch_actual_prefetchit0_window((uint64_t)i, 0);
    }
}

__attribute__((noinline, used, aligned(65536), section(".text.zz_branch_farpath_prefetch_t0")))
static void branch_farpath_prefetchit0_target(uint64_t x, int mode) {
    if (mode == 1) {
        call_far_tlb_miss_pair();
    }

    PREFETCHI_T0_TARGET_LINES_SPACED(32);

    if (mode == 2) {
        if ((x >> 4) & 1u) {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(bar, 16);
            PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
        } else {
            PREFETCHI_T0_SYMBOL_LINES_SPACED(baz, 16);
            PREFETCHI_T0_SYMBOL_LINES_SPACED(foo, 16);
        }
    }

    PREFETCHI_T0_TARGET_LINES_SPACED(32);

    if (mode == 3) {
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
    } else {
        call_far_tlb_miss_pair_cd();
    }

    g_state ^= x + (uint64_t)mode;
}

__attribute__((noinline, used, aligned(4096), section(".text.branch_to_farpath_t0")))
static void branch_to_farpath_prefetchit0_window(uint64_t seed, int mode) {
    uint64_t dep = slow_branch_dependency_deep();
    uint64_t x = seed ^ g_state ^ dep;

    if (__builtin_expect((g_branch_gate | (int)dep) == 0, 1)) {
        asm volatile("" ::: "memory");
    } else {
        branch_farpath_prefetchit0_target(x, mode);
    }

    g_state += x + (uint64_t)mode;
}

__attribute__((noinline, used))
static void train_branch_farpath_prefetchit0_window(void) {
    g_branch_gate = 0;
    g_slow_branch_mask = 0;
    for (int i = 0; i < 96; ++i) {
        branch_to_farpath_prefetchit0_window((uint64_t)i, 0);
    }
}

#define ASM_PREFETCHIT0_TARGET_LINES                                         \
    "prefetchit0 bar(%%rip)\n\t"                                             \
    "prefetchit0 bar+64(%%rip)\n\t"                                          \
    "prefetchit0 bar+128(%%rip)\n\t"                                         \
    "prefetchit0 bar+192(%%rip)\n\t"                                         \
    "prefetchit0 bar+256(%%rip)\n\t"                                         \
    "prefetchit0 bar+320(%%rip)\n\t"                                         \
    "prefetchit0 bar+384(%%rip)\n\t"                                         \
    "prefetchit0 bar+448(%%rip)\n\t"                                         \
    "prefetchit0 bar+512(%%rip)\n\t"                                         \
    "prefetchit0 foo(%%rip)\n\t"                                             \
    "prefetchit0 foo+64(%%rip)\n\t"                                          \
    "prefetchit0 foo+128(%%rip)\n\t"                                         \
    "prefetchit0 foo+192(%%rip)\n\t"                                         \
    "prefetchit0 foo+256(%%rip)\n\t"                                         \
    "prefetchit0 foo+320(%%rip)\n\t"                                         \
    "prefetchit0 foo+384(%%rip)\n\t"                                         \
    "prefetchit0 foo+448(%%rip)\n\t"                                         \
    "prefetchit0 foo+512(%%rip)\n\t"                                         \
    "prefetchit0 baz(%%rip)\n\t"                                             \
    "prefetchit0 baz+64(%%rip)\n\t"                                          \
    "prefetchit0 baz+128(%%rip)\n\t"                                         \
    "prefetchit0 baz+192(%%rip)\n\t"                                         \
    "prefetchit0 baz+256(%%rip)\n\t"                                         \
    "prefetchit0 baz+320(%%rip)\n\t"                                         \
    "prefetchit0 baz+384(%%rip)\n\t"                                         \
    "prefetchit0 baz+448(%%rip)\n\t"                                         \
    "prefetchit0 baz+512(%%rip)\n\t"

#define ASM_PREFETCHIT1_TARGET_LINES                                         \
    "prefetchit1 bar(%%rip)\n\t"                                             \
    "prefetchit1 bar+64(%%rip)\n\t"                                          \
    "prefetchit1 bar+128(%%rip)\n\t"                                         \
    "prefetchit1 bar+192(%%rip)\n\t"                                         \
    "prefetchit1 bar+256(%%rip)\n\t"                                         \
    "prefetchit1 bar+320(%%rip)\n\t"                                         \
    "prefetchit1 bar+384(%%rip)\n\t"                                         \
    "prefetchit1 bar+448(%%rip)\n\t"                                         \
    "prefetchit1 bar+512(%%rip)\n\t"                                         \
    "prefetchit1 foo(%%rip)\n\t"                                             \
    "prefetchit1 foo+64(%%rip)\n\t"                                          \
    "prefetchit1 foo+128(%%rip)\n\t"                                         \
    "prefetchit1 foo+192(%%rip)\n\t"                                         \
    "prefetchit1 foo+256(%%rip)\n\t"                                         \
    "prefetchit1 foo+320(%%rip)\n\t"                                         \
    "prefetchit1 foo+384(%%rip)\n\t"                                         \
    "prefetchit1 foo+448(%%rip)\n\t"                                         \
    "prefetchit1 foo+512(%%rip)\n\t"                                         \
    "prefetchit1 baz(%%rip)\n\t"                                             \
    "prefetchit1 baz+64(%%rip)\n\t"                                          \
    "prefetchit1 baz+128(%%rip)\n\t"                                         \
    "prefetchit1 baz+192(%%rip)\n\t"                                         \
    "prefetchit1 baz+256(%%rip)\n\t"                                         \
    "prefetchit1 baz+320(%%rip)\n\t"                                         \
    "prefetchit1 baz+384(%%rip)\n\t"                                         \
    "prefetchit1 baz+448(%%rip)\n\t"                                         \
    "prefetchit1 baz+512(%%rip)\n\t"

#define ASM_PREFETCHIT0_BAR_LINES                                            \
    "prefetchit0 bar(%%rip)\n\t"                                             \
    "prefetchit0 bar+64(%%rip)\n\t"                                          \
    "prefetchit0 bar+128(%%rip)\n\t"                                         \
    "prefetchit0 bar+192(%%rip)\n\t"                                         \
    "prefetchit0 bar+256(%%rip)\n\t"                                         \
    "prefetchit0 bar+320(%%rip)\n\t"                                         \
    "prefetchit0 bar+384(%%rip)\n\t"                                         \
    "prefetchit0 bar+448(%%rip)\n\t"                                         \
    "prefetchit0 bar+512(%%rip)\n\t"

#define ASM_PREFETCHT0_BAR_LINES                                             \
    "prefetcht0 bar(%%rip)\n\t"                                              \
    "prefetcht0 bar+64(%%rip)\n\t"                                           \
    "prefetcht0 bar+128(%%rip)\n\t"                                          \
    "prefetcht0 bar+192(%%rip)\n\t"                                          \
    "prefetcht0 bar+256(%%rip)\n\t"                                          \
    "prefetcht0 bar+320(%%rip)\n\t"                                          \
    "prefetcht0 bar+384(%%rip)\n\t"                                          \
    "prefetcht0 bar+448(%%rip)\n\t"                                          \
    "prefetcht0 bar+512(%%rip)\n\t"

#define ASM_PREFETCHIT0_TARGET_HEADS                                         \
    "prefetchit0 bar(%%rip)\n\t"                                             \
    "prefetchit0 foo(%%rip)\n\t"                                             \
    "prefetchit0 baz(%%rip)\n\t"

#define ASM_PREFETCHT0_TARGET_LINES                                          \
    "prefetcht0 bar(%%rip)\n\t"                                              \
    "prefetcht0 bar+64(%%rip)\n\t"                                           \
    "prefetcht0 bar+128(%%rip)\n\t"                                          \
    "prefetcht0 bar+192(%%rip)\n\t"                                          \
    "prefetcht0 bar+256(%%rip)\n\t"                                          \
    "prefetcht0 bar+320(%%rip)\n\t"                                          \
    "prefetcht0 bar+384(%%rip)\n\t"                                          \
    "prefetcht0 bar+448(%%rip)\n\t"                                          \
    "prefetcht0 bar+512(%%rip)\n\t"                                          \
    "prefetcht0 foo(%%rip)\n\t"                                              \
    "prefetcht0 foo+64(%%rip)\n\t"                                           \
    "prefetcht0 foo+128(%%rip)\n\t"                                          \
    "prefetcht0 foo+192(%%rip)\n\t"                                          \
    "prefetcht0 foo+256(%%rip)\n\t"                                          \
    "prefetcht0 foo+320(%%rip)\n\t"                                          \
    "prefetcht0 foo+384(%%rip)\n\t"                                          \
    "prefetcht0 foo+448(%%rip)\n\t"                                          \
    "prefetcht0 foo+512(%%rip)\n\t"                                          \
    "prefetcht0 baz(%%rip)\n\t"                                              \
    "prefetcht0 baz+64(%%rip)\n\t"                                           \
    "prefetcht0 baz+128(%%rip)\n\t"                                          \
    "prefetcht0 baz+192(%%rip)\n\t"                                          \
    "prefetcht0 baz+256(%%rip)\n\t"                                          \
    "prefetcht0 baz+320(%%rip)\n\t"                                          \
    "prefetcht0 baz+384(%%rip)\n\t"                                          \
    "prefetcht0 baz+448(%%rip)\n\t"                                          \
    "prefetcht0 baz+512(%%rip)\n\t"

#define ASM_REPT_NOPS(count) ".rept " #count "\n\tnop\n\t.endr\n\t"

#define BASM_REPT_NOPS(count) ".rept " #count "\n\tnop\n\t.endr\n\t"

#define BASM_PREFETCHIT0_BAR_LINES                                           \
    "prefetchit0 bar(%rip)\n\t"                                              \
    "prefetchit0 bar+64(%rip)\n\t"                                           \
    "prefetchit0 bar+128(%rip)\n\t"                                          \
    "prefetchit0 bar+192(%rip)\n\t"                                          \
    "prefetchit0 bar+256(%rip)\n\t"                                          \
    "prefetchit0 bar+320(%rip)\n\t"                                          \
    "prefetchit0 bar+384(%rip)\n\t"                                          \
    "prefetchit0 bar+448(%rip)\n\t"                                          \
    "prefetchit0 bar+512(%rip)\n\t"

#define BASM_PREFETCHIT0_BAR_HEAD                                            \
    "prefetchit0 bar(%rip)\n\t"

#define BASM_PREFETCHIT1_BAR_LINES                                           \
    "prefetchit1 bar(%rip)\n\t"                                              \
    "prefetchit1 bar+64(%rip)\n\t"                                           \
    "prefetchit1 bar+128(%rip)\n\t"                                          \
    "prefetchit1 bar+192(%rip)\n\t"                                          \
    "prefetchit1 bar+256(%rip)\n\t"                                          \
    "prefetchit1 bar+320(%rip)\n\t"                                          \
    "prefetchit1 bar+384(%rip)\n\t"                                          \
    "prefetchit1 bar+448(%rip)\n\t"                                          \
    "prefetchit1 bar+512(%rip)\n\t"

#define BASM_PREFETCHIT1_BAR_HEAD                                            \
    "prefetchit1 bar(%rip)\n\t"

#define BASM_PREFETCHT0_BAR_LINES                                            \
    "prefetcht0 bar(%rip)\n\t"                                               \
    "prefetcht0 bar+64(%rip)\n\t"                                            \
    "prefetcht0 bar+128(%rip)\n\t"                                           \
    "prefetcht0 bar+192(%rip)\n\t"                                           \
    "prefetcht0 bar+256(%rip)\n\t"                                           \
    "prefetcht0 bar+320(%rip)\n\t"                                           \
    "prefetcht0 bar+384(%rip)\n\t"                                           \
    "prefetcht0 bar+448(%rip)\n\t"                                           \
    "prefetcht0 bar+512(%rip)\n\t"

#define BASM_PREFETCHT0_BAR_HEAD                                             \
    "prefetcht0 bar(%rip)\n\t"

#define BASM_PREFETCHIT0_TARGET_LINES                                        \
    BASM_PREFETCHIT0_BAR_LINES                                               \
    "prefetchit0 foo(%rip)\n\t"                                              \
    "prefetchit0 foo+64(%rip)\n\t"                                           \
    "prefetchit0 foo+128(%rip)\n\t"                                          \
    "prefetchit0 foo+192(%rip)\n\t"                                          \
    "prefetchit0 foo+256(%rip)\n\t"                                          \
    "prefetchit0 foo+320(%rip)\n\t"                                          \
    "prefetchit0 foo+384(%rip)\n\t"                                          \
    "prefetchit0 foo+448(%rip)\n\t"                                          \
    "prefetchit0 foo+512(%rip)\n\t"                                          \
    "prefetchit0 baz(%rip)\n\t"                                              \
    "prefetchit0 baz+64(%rip)\n\t"                                           \
    "prefetchit0 baz+128(%rip)\n\t"                                          \
    "prefetchit0 baz+192(%rip)\n\t"                                          \
    "prefetchit0 baz+256(%rip)\n\t"                                          \
    "prefetchit0 baz+320(%rip)\n\t"                                          \
    "prefetchit0 baz+384(%rip)\n\t"                                          \
    "prefetchit0 baz+448(%rip)\n\t"                                          \
    "prefetchit0 baz+512(%rip)\n\t"

#define BASM_PREFETCHIT1_TARGET_LINES                                        \
    BASM_PREFETCHIT1_BAR_LINES                                               \
    "prefetchit1 foo(%rip)\n\t"                                              \
    "prefetchit1 foo+64(%rip)\n\t"                                           \
    "prefetchit1 foo+128(%rip)\n\t"                                          \
    "prefetchit1 foo+192(%rip)\n\t"                                          \
    "prefetchit1 foo+256(%rip)\n\t"                                          \
    "prefetchit1 foo+320(%rip)\n\t"                                          \
    "prefetchit1 foo+384(%rip)\n\t"                                          \
    "prefetchit1 foo+448(%rip)\n\t"                                          \
    "prefetchit1 foo+512(%rip)\n\t"                                          \
    "prefetchit1 baz(%rip)\n\t"                                              \
    "prefetchit1 baz+64(%rip)\n\t"                                           \
    "prefetchit1 baz+128(%rip)\n\t"                                          \
    "prefetchit1 baz+192(%rip)\n\t"                                          \
    "prefetchit1 baz+256(%rip)\n\t"                                          \
    "prefetchit1 baz+320(%rip)\n\t"                                          \
    "prefetchit1 baz+384(%rip)\n\t"                                          \
    "prefetchit1 baz+448(%rip)\n\t"                                          \
    "prefetchit1 baz+512(%rip)\n\t"

#define BASM_PREFETCHT0_TARGET_LINES                                         \
    BASM_PREFETCHT0_BAR_LINES                                                \
    "prefetcht0 foo(%rip)\n\t"                                               \
    "prefetcht0 foo+64(%rip)\n\t"                                            \
    "prefetcht0 foo+128(%rip)\n\t"                                           \
    "prefetcht0 foo+192(%rip)\n\t"                                           \
    "prefetcht0 foo+256(%rip)\n\t"                                           \
    "prefetcht0 foo+320(%rip)\n\t"                                           \
    "prefetcht0 foo+384(%rip)\n\t"                                           \
    "prefetcht0 foo+448(%rip)\n\t"                                           \
    "prefetcht0 foo+512(%rip)\n\t"                                           \
    "prefetcht0 baz(%rip)\n\t"                                               \
    "prefetcht0 baz+64(%rip)\n\t"                                            \
    "prefetcht0 baz+128(%rip)\n\t"                                           \
    "prefetcht0 baz+192(%rip)\n\t"                                           \
    "prefetcht0 baz+256(%rip)\n\t"                                           \
    "prefetcht0 baz+320(%rip)\n\t"                                           \
    "prefetcht0 baz+384(%rip)\n\t"                                           \
    "prefetcht0 baz+448(%rip)\n\t"                                           \
    "prefetcht0 baz+512(%rip)\n\t"

#define DEFINE_BRANCHWIN_TARGET_T0_WITH(name, count, prefetch_block)         \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        "movl g_branch_gate(%%rip), %%eax\n\t"                                \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        prefetch_block                                                         \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_WRONG_T0_WITH(name, count, prefetch_block)           \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        "movl g_branch_gate(%%rip), %%eax\n\t"                                \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        prefetch_block                                                         \
        "jmp 2f\n\t"                                                          \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_FALLWRONG_T0_WITH(name, count, prefetch_block)       \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        "movl g_branch_gate(%%rip), %%eax\n\t"                                \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        ASM_REPT_NOPS(count)                                                   \
        prefetch_block                                                         \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_FALLCORRECT_T0_WITH(name, count, prefetch_block)     \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        "movl g_branch_gate(%%rip), %%eax\n\t"                                \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        ASM_REPT_NOPS(count)                                                   \
        prefetch_block                                                         \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_BEFORE_T0_WITH(name, count, prefetch_block)          \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        prefetch_block                                                         \
        ASM_REPT_NOPS(count)                                                   \
        "movl g_branch_gate(%%rip), %%eax\n\t"                                \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_TARGET_T0(name, count) \
    DEFINE_BRANCHWIN_TARGET_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_LINES)
#define DEFINE_BRANCHWIN_WRONG_T0(name, count) \
    DEFINE_BRANCHWIN_WRONG_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_LINES)
#define DEFINE_BRANCHWIN_BEFORE_T0(name, count) \
    DEFINE_BRANCHWIN_BEFORE_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_LINES)
#define DEFINE_BRANCHWIN_TARGET_HEAD_T0(name, count) \
    DEFINE_BRANCHWIN_TARGET_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_HEADS)
#define DEFINE_BRANCHWIN_WRONG_HEAD_T0(name, count) \
    DEFINE_BRANCHWIN_WRONG_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_HEADS)
#define DEFINE_BRANCHWIN_FALLWRONG_T0(name, count) \
    DEFINE_BRANCHWIN_FALLWRONG_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_LINES)
#define DEFINE_BRANCHWIN_FALLCORRECT_T0(name, count) \
    DEFINE_BRANCHWIN_FALLCORRECT_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_LINES)
#define DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(name, count) \
    DEFINE_BRANCHWIN_FALLWRONG_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_HEADS)
#define DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(name, count) \
    DEFINE_BRANCHWIN_FALLCORRECT_T0_WITH(name, count, ASM_PREFETCHIT0_TARGET_HEADS)

DEFINE_BRANCHWIN_TARGET_T0(branchwin_target_t0_o0, 0)
DEFINE_BRANCHWIN_TARGET_T0(branchwin_target_t0_o1, 1)
DEFINE_BRANCHWIN_TARGET_T0(branchwin_target_t0_o2, 2)
DEFINE_BRANCHWIN_TARGET_T0(branchwin_target_t0_o4, 4)
DEFINE_BRANCHWIN_TARGET_T0(branchwin_target_t0_o8, 8)
DEFINE_BRANCHWIN_TARGET_T0(branchwin_target_t0_o16, 16)

DEFINE_BRANCHWIN_WRONG_T0(branchwin_wrong_t0_o0, 0)
DEFINE_BRANCHWIN_WRONG_T0(branchwin_wrong_t0_o1, 1)
DEFINE_BRANCHWIN_WRONG_T0(branchwin_wrong_t0_o2, 2)
DEFINE_BRANCHWIN_WRONG_T0(branchwin_wrong_t0_o4, 4)
DEFINE_BRANCHWIN_WRONG_T0(branchwin_wrong_t0_o8, 8)
DEFINE_BRANCHWIN_WRONG_T0(branchwin_wrong_t0_o16, 16)

DEFINE_BRANCHWIN_BEFORE_T0(branchwin_before_t0_o0, 0)
DEFINE_BRANCHWIN_BEFORE_T0(branchwin_before_t0_o1, 1)
DEFINE_BRANCHWIN_BEFORE_T0(branchwin_before_t0_o2, 2)
DEFINE_BRANCHWIN_BEFORE_T0(branchwin_before_t0_o4, 4)
DEFINE_BRANCHWIN_BEFORE_T0(branchwin_before_t0_o8, 8)
DEFINE_BRANCHWIN_BEFORE_T0(branchwin_before_t0_o16, 16)

DEFINE_BRANCHWIN_TARGET_HEAD_T0(branchwin_target_head_t0_o0, 0)
DEFINE_BRANCHWIN_TARGET_HEAD_T0(branchwin_target_head_t0_o1, 1)
DEFINE_BRANCHWIN_TARGET_HEAD_T0(branchwin_target_head_t0_o2, 2)
DEFINE_BRANCHWIN_TARGET_HEAD_T0(branchwin_target_head_t0_o4, 4)
DEFINE_BRANCHWIN_TARGET_HEAD_T0(branchwin_target_head_t0_o8, 8)
DEFINE_BRANCHWIN_TARGET_HEAD_T0(branchwin_target_head_t0_o16, 16)

DEFINE_BRANCHWIN_WRONG_HEAD_T0(branchwin_wrong_head_t0_o0, 0)
DEFINE_BRANCHWIN_WRONG_HEAD_T0(branchwin_wrong_head_t0_o1, 1)
DEFINE_BRANCHWIN_WRONG_HEAD_T0(branchwin_wrong_head_t0_o2, 2)
DEFINE_BRANCHWIN_WRONG_HEAD_T0(branchwin_wrong_head_t0_o4, 4)
DEFINE_BRANCHWIN_WRONG_HEAD_T0(branchwin_wrong_head_t0_o8, 8)
DEFINE_BRANCHWIN_WRONG_HEAD_T0(branchwin_wrong_head_t0_o16, 16)

DEFINE_BRANCHWIN_FALLWRONG_T0(branchwin_fallwrong_t0_o0, 0)
DEFINE_BRANCHWIN_FALLWRONG_T0(branchwin_fallwrong_t0_o1, 1)
DEFINE_BRANCHWIN_FALLWRONG_T0(branchwin_fallwrong_t0_o2, 2)
DEFINE_BRANCHWIN_FALLWRONG_T0(branchwin_fallwrong_t0_o4, 4)
DEFINE_BRANCHWIN_FALLWRONG_T0(branchwin_fallwrong_t0_o8, 8)
DEFINE_BRANCHWIN_FALLWRONG_T0(branchwin_fallwrong_t0_o16, 16)

DEFINE_BRANCHWIN_FALLCORRECT_T0(branchwin_fallcorrect_t0_o0, 0)
DEFINE_BRANCHWIN_FALLCORRECT_T0(branchwin_fallcorrect_t0_o1, 1)
DEFINE_BRANCHWIN_FALLCORRECT_T0(branchwin_fallcorrect_t0_o2, 2)
DEFINE_BRANCHWIN_FALLCORRECT_T0(branchwin_fallcorrect_t0_o4, 4)
DEFINE_BRANCHWIN_FALLCORRECT_T0(branchwin_fallcorrect_t0_o8, 8)
DEFINE_BRANCHWIN_FALLCORRECT_T0(branchwin_fallcorrect_t0_o16, 16)

DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(branchwin_fallwrong_head_t0_o0, 0)
DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(branchwin_fallwrong_head_t0_o1, 1)
DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(branchwin_fallwrong_head_t0_o2, 2)
DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(branchwin_fallwrong_head_t0_o4, 4)
DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(branchwin_fallwrong_head_t0_o8, 8)
DEFINE_BRANCHWIN_FALLWRONG_HEAD_T0(branchwin_fallwrong_head_t0_o16, 16)

DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(branchwin_fallcorrect_head_t0_o0, 0)
DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(branchwin_fallcorrect_head_t0_o1, 1)
DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(branchwin_fallcorrect_head_t0_o2, 2)
DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(branchwin_fallcorrect_head_t0_o4, 4)
DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(branchwin_fallcorrect_head_t0_o8, 8)
DEFINE_BRANCHWIN_FALLCORRECT_HEAD_T0(branchwin_fallcorrect_head_t0_o16, 16)

static void train_branchwin_gate(VoidFn fn, int gate_value) {
    g_branch_gate = gate_value;
    asm volatile("mfence\n\tlfence" ::: "memory");
    for (int i = 0; i < 192; ++i) {
        fn();
    }
}

static void prepare_actual_gate_miss(int gate_value) {
    g_branch_gate = gate_value;
    _mm_clflush((const void *)&g_branch_gate);
    asm volatile("mfence\n\tlfence" ::: "memory");
}

static void run_branchwin_target_t0(VoidFn fn) {
    train_branchwin_gate(fn, 0);
    prepare_actual_gate_miss(1);
    fn();
}

static void run_branchwin_wrong_t0(VoidFn fn) {
    train_branchwin_gate(fn, 1);
    flush_target_code();
    shootdown_target_code_tlb();
    prepare_actual_gate_miss(0);
    fn();
    g_branch_gate = 1;
}

static void run_branchwin_before_t0(VoidFn fn) {
    train_branchwin_gate(fn, 0);
    flush_target_code();
    shootdown_target_code_tlb();
    prepare_actual_gate_miss(1);
    fn();
}

static void run_branchwin_fallwrong_t0(VoidFn fn) {
    train_branchwin_gate(fn, 0);
    flush_target_code();
    shootdown_target_code_tlb();
    prepare_actual_gate_miss(1);
    fn();
}

static void run_branchwin_fallcorrect_t0(VoidFn fn) {
    train_branchwin_gate(fn, 1);
    prepare_actual_gate_miss(0);
    fn();
    g_branch_gate = 1;
}

static void setup_branch_chain(int gate_value) {
    g_branch_gate = gate_value;
    for (int i = 0; i < 7; ++i) {
        g_branch_chain[i].value = (uintptr_t)&g_branch_chain[i + 1].value;
    }
    g_branch_chain[7].value = (uintptr_t)&g_branch_gate;
    asm volatile("mfence\n\tlfence" ::: "memory");
}

static void flush_branch_chain_gate(void) {
    for (int i = 0; i < 8; ++i) {
        _mm_clflush((const void *)&g_branch_chain[i].value);
    }
    _mm_clflush((const void *)&g_branch_gate);
    asm volatile("mfence\n\tlfence" ::: "memory");
}

#define ASM_LOAD_SLOW_GATE                                                    \
    "leaq g_branch_chain(%%rip), %%rax\n\t"                                  \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movq (%%rax), %%rax\n\t"                                                \
    "movl (%%rax), %%eax\n\t"

#define BASM_LOAD_SLOW_GATE                                                   \
    "leaq g_branch_chain(%rip), %rax\n\t"                                    \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movq (%rax), %rax\n\t"                                                  \
    "movl (%rax), %eax\n\t"

#define DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(name, count)                    \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.slow." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT0_TARGET_HEADS                                           \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(name, count)                 \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.slow." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT0_TARGET_HEADS                                           \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(name, count)               \
    DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(name, count)

#define DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(name, count)                   \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.slow." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT0_TARGET_LINES                                           \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(name, count)                \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.slow." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT0_TARGET_LINES                                           \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(name, count)              \
    DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(name, count)

#define DEFINE_BRANCHWIN_SLOW_TARGET_DATAT0_LINES(name, count)               \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.slow." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHT0_TARGET_LINES                                            \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(name, count)           \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.farblock." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT0_TARGET_HEADS                                           \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(name, count)          \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.farblock." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT0_TARGET_LINES                                           \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_DATAT0_LINES(name, count)      \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.farblock." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHT0_TARGET_LINES                                            \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_IT1(name, count)         \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.farblock." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHIT1_TARGET_LINES                                           \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(name, count)          \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.beforefar." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_PREFETCHIT0_TARGET_HEADS                                           \
        ASM_REPT_NOPS(count)                                                   \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(name, count)         \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.beforefar." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_PREFETCHIT0_TARGET_LINES                                           \
        ASM_REPT_NOPS(count)                                                   \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_DATAT0_LINES(name, count)     \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.beforefar." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_PREFETCHT0_TARGET_LINES                                            \
        ASM_REPT_NOPS(count)                                                   \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_IT1(name, count)        \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.beforefar." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_PREFETCHIT1_TARGET_LINES                                           \
        ASM_REPT_NOPS(count)                                                   \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define ASM_BRANCH_STORM_STEP(label)                                          \
    ASM_LOAD_SLOW_GATE                                                        \
    "testl %%eax, %%eax\n\t"                                                  \
    "jne " #label "f\n\t"                                                     \
    "jmp 9f\n\t"                                                             \
    ".p2align 12\n\t"                                                        \
    #label ":\n\t"

#define DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(name, prefetch_block)    \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.beforestorm." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        prefetch_block                                                         \
        ASM_BRANCH_STORM_STEP(1)                                               \
        ASM_BRANCH_STORM_STEP(2)                                               \
        ASM_BRANCH_STORM_STEP(3)                                               \
        ASM_BRANCH_STORM_STEP(4)                                               \
        "nop\n\t"                                                             \
        "9:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_BOTH_FARBLOCK_LINES(name, prefetch_block)      \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.bothfar." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        prefetch_block                                                         \
        "jmp 2f\n\t"                                                          \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        prefetch_block                                                         \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

#define DEFINE_BRANCHWIN_SLOW_FALLCORRECT_DATAT0_LINES(name, count)          \
__attribute__((noinline, used, aligned(4096), section(".text.branchwin.slow." #name))) \
static void name(void) {                                                       \
    asm volatile(                                                              \
        ASM_LOAD_SLOW_GATE                                                     \
        "testl %%eax, %%eax\n\t"                                               \
        "jne 1f\n\t"                                                          \
        ASM_REPT_NOPS(count)                                                   \
        ASM_PREFETCHT0_TARGET_LINES                                            \
        "jmp 2f\n\t"                                                          \
        "1:\n\t"                                                              \
        "nop\n\t"                                                             \
        "2:\n\t"                                                              \
        ::: "rax", "memory");                                                 \
}

DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_TARGET_HEAD_T0(branchwin_slow_target_head_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_HEAD_T0(branchwin_slow_fallwrong_head_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_HEAD_T0(branchwin_slow_fallcorrect_head_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_TARGET_LINES_T0(branchwin_slow_target_lines_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_FALLWRONG_LINES_T0(branchwin_slow_fallwrong_lines_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_LINES_T0(branchwin_slow_fallcorrect_lines_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_TARGET_DATAT0_LINES(branchwin_slow_target_lines_datat0_o5, 5)
DEFINE_BRANCHWIN_SLOW_FALLCORRECT_DATAT0_LINES(branchwin_slow_fallcorrect_lines_datat0_o1, 1)

DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_T0(branchwin_slow_target_farblock_head_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_T0(branchwin_slow_target_farblock_lines_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_DATAT0_LINES(branchwin_slow_target_farblock_lines_datat0_o0, 0)

DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_T0(branchwin_slow_before_farbranch_head_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o0, 0)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o1, 1)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o2, 2)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o3, 3)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o4, 4)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o5, 5)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o6, 6)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o7, 7)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_T0(branchwin_slow_before_farbranch_lines_t0_o8, 8)

DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_DATAT0_LINES(branchwin_slow_before_farbranch_lines_datat0_o0, 0)

DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(branchwin_slow_before_farstorm_lines_t0, ASM_PREFETCHIT0_TARGET_LINES)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(branchwin_slow_before_farstorm_lines_datat0, ASM_PREFETCHT0_TARGET_LINES)
DEFINE_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_IT1(branchwin_slow_target_farblock_lines_it1_o0, 0)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_IT1(branchwin_slow_before_farbranch_lines_it1_o7, 7)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(branchwin_slow_before_farstorm_lines_it1, ASM_PREFETCHIT1_TARGET_LINES)
DEFINE_BRANCHWIN_SLOW_BOTH_FARBLOCK_LINES(branchwin_slow_both_farblock_lines_t0, ASM_PREFETCHIT0_TARGET_LINES)
DEFINE_BRANCHWIN_SLOW_BOTH_FARBLOCK_LINES(branchwin_slow_both_farblock_lines_datat0, ASM_PREFETCHT0_TARGET_LINES)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(branchwin_slow_before_farstorm_bar_lines_t0, ASM_PREFETCHIT0_BAR_LINES)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(branchwin_slow_before_farstorm_bar_lines_datat0, ASM_PREFETCHT0_BAR_LINES)
DEFINE_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES(branchwin_slow_before_farstorm_nopref, "")

#define BASM_BRANCH_STORM_STEP(label)                                         \
    BASM_LOAD_SLOW_GATE                                                       \
    "testl %eax, %eax\n\t"                                                    \
    "jne " #label "f\n\t"                                                    \
    "jmp 9f\n\t"                                                             \
    ".p2align 12\n\t"                                                        \
    #label ":\n\t"

#define DEFINE_NAKED_BEFORE_FARSTORM(name, prefetch_block)                   \
__attribute__((naked, noinline, used, aligned(4096), section(".text.branchwin.naked." #name))) \
static void name(void) {                                                       \
    __asm__ volatile(                                                          \
        prefetch_block                                                         \
        BASM_BRANCH_STORM_STEP(1)                                              \
        BASM_BRANCH_STORM_STEP(2)                                              \
        BASM_BRANCH_STORM_STEP(3)                                              \
        BASM_BRANCH_STORM_STEP(4)                                              \
        "9:\n\t"                                                               \
        "retq\n\t");                                                          \
}

#define DEFINE_NAKED_TARGET_FARBLOCK(name, count, prefetch_block)            \
__attribute__((naked, noinline, used, aligned(4096), section(".text.branchwin.naked." #name))) \
static void name(void) {                                                       \
    __asm__ volatile(                                                          \
        BASM_LOAD_SLOW_GATE                                                    \
        "testl %eax, %eax\n\t"                                                 \
        "jne 1f\n\t"                                                          \
        "retq\n\t"                                                            \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        BASM_REPT_NOPS(count)                                                  \
        prefetch_block                                                         \
        "retq\n\t");                                                          \
}

#define DEFINE_NAKED_FALLTHROUGH_PREFETCH(name, count, prefetch_block)       \
__attribute__((naked, noinline, used, aligned(4096), section(".text.branchwin.naked." #name))) \
static void name(void) {                                                       \
    __asm__ volatile(                                                          \
        BASM_LOAD_SLOW_GATE                                                    \
        "testl %eax, %eax\n\t"                                                 \
        "jne 1f\n\t"                                                          \
        BASM_REPT_NOPS(count)                                                  \
        prefetch_block                                                         \
        "retq\n\t"                                                            \
        ".p2align 12\n\t"                                                     \
        "1:\n\t"                                                              \
        "retq\n\t");                                                          \
}

#define BASM_BRANCH_TARGET_PREFETCH_STEP(label, count, prefetch_block)        \
    BASM_LOAD_SLOW_GATE                                                       \
    "testl %eax, %eax\n\t"                                                    \
    "jne " #label "f\n\t"                                                     \
    "jmp 9f\n\t"                                                             \
    ".p2align 12\n\t"                                                        \
    #label ":\n\t"                                                            \
    BASM_REPT_NOPS(count)                                                     \
    prefetch_block

#define DEFINE_NAKED_CHAIN_TARGET_PREFETCH(name, count, prefetch_block)      \
__attribute__((naked, noinline, used, aligned(4096), section(".text.branchwin.naked." #name))) \
static void name(void) {                                                       \
    __asm__ volatile(                                                          \
        BASM_BRANCH_TARGET_PREFETCH_STEP(1, count, prefetch_block)             \
        BASM_BRANCH_TARGET_PREFETCH_STEP(2, count, prefetch_block)             \
        BASM_BRANCH_TARGET_PREFETCH_STEP(3, count, prefetch_block)             \
        BASM_BRANCH_TARGET_PREFETCH_STEP(4, count, prefetch_block)             \
        "9:\n\t"                                                               \
        "retq\n\t");                                                          \
}

#define DEFINE_NAKED_FARCALL_WINDOW(name, prefetch_block)                    \
__attribute__((naked, noinline, used, aligned(4096), section(".text.branchwin.naked." #name))) \
static void name(void) {                                                       \
    __asm__ volatile(                                                          \
        prefetch_block                                                         \
        prefetch_block                                                         \
        "callq farcall_tlb_miss_a\n\t"                                        \
        "callq farcall_tlb_miss_b\n\t"                                        \
        "retq\n\t");                                                          \
}

#define DEFINE_NAKED_FARCALL_PREFETCH_SPLIT(name, prefetch_block)            \
__attribute__((naked, noinline, used, aligned(4096), section(".text.branchwin.naked." #name))) \
static void name(void) {                                                       \
    __asm__ volatile(                                                          \
        "callq farcall_tlb_miss_a\n\t"                                        \
        prefetch_block                                                         \
        prefetch_block                                                         \
        "callq farcall_tlb_miss_b\n\t"                                        \
        "retq\n\t");                                                          \
}

DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_bar_lines_t0, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_bar_lines_it1, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_bar_lines_datat0, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_lines_t0, BASM_PREFETCHIT0_TARGET_LINES)
DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_lines_it1, BASM_PREFETCHIT1_TARGET_LINES)
DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_lines_datat0, BASM_PREFETCHT0_TARGET_LINES)
DEFINE_NAKED_BEFORE_FARSTORM(branchwin_naked_before_farstorm_nopref, "")

DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o0, 0, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o1, 1, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o2, 2, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o4, 4, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o8, 8, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o16, 16, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o32, 32, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o64, 64, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_t0_o128, 128, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_it1_o0, 0, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_it1_o32, 32, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_datat0_o0, 0, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_lines_datat0_o32, 32, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_nopref_o0, 0, "")
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_nopref_o32, 32, "")
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_head_t0_o0, 0, BASM_PREFETCHIT0_BAR_HEAD)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_head_it1_o0, 0, BASM_PREFETCHIT1_BAR_HEAD)
DEFINE_NAKED_TARGET_FARBLOCK(branchwin_naked_target_farblock_bar_head_datat0_o0, 0, BASM_PREFETCHT0_BAR_HEAD)

DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o0, 0, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o1, 1, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o2, 2, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o3, 3, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o4, 4, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o5, 5, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o8, 8, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o12, 12, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_t0_o16, 16, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_it1_o0, 0, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_bar_lines_datat0_o0, 0, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_FALLTHROUGH_PREFETCH(branchwin_naked_fallthrough_nopref_o0, 0, "")

DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_t0_o0, 0, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_t0_o1, 1, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_t0_o2, 2, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_t0_o4, 4, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_t0_o8, 8, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_it1_o0, 0, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_lines_datat0_o0, 0, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_nopref_o0, 0, "")
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_head_t0_o0, 0, BASM_PREFETCHIT0_BAR_HEAD)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_head_it1_o0, 0, BASM_PREFETCHIT1_BAR_HEAD)
DEFINE_NAKED_CHAIN_TARGET_PREFETCH(branchwin_naked_chain_targetpref_bar_head_datat0_o0, 0, BASM_PREFETCHT0_BAR_HEAD)

DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_bar_lines_t0, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_bar_lines_it1, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_bar_lines_datat0, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_nopref, "")
DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_bar_head_t0, BASM_PREFETCHIT0_BAR_HEAD)
DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_bar_head_it1, BASM_PREFETCHIT1_BAR_HEAD)
DEFINE_NAKED_FARCALL_WINDOW(branchwin_naked_p2_far2_bar_head_datat0, BASM_PREFETCHT0_BAR_HEAD)
DEFINE_NAKED_FARCALL_PREFETCH_SPLIT(branchwin_naked_far_p2_far_bar_lines_t0, BASM_PREFETCHIT0_BAR_LINES)
DEFINE_NAKED_FARCALL_PREFETCH_SPLIT(branchwin_naked_far_p2_far_bar_lines_it1, BASM_PREFETCHIT1_BAR_LINES)
DEFINE_NAKED_FARCALL_PREFETCH_SPLIT(branchwin_naked_far_p2_far_bar_lines_datat0, BASM_PREFETCHT0_BAR_LINES)
DEFINE_NAKED_FARCALL_PREFETCH_SPLIT(branchwin_naked_far_p2_far_nopref, "")

enum {
    BRANCHWIN_SLOW_MODE_TARGET,
    BRANCHWIN_SLOW_MODE_FALLWRONG,
    BRANCHWIN_SLOW_MODE_FALLCORRECT,
    BRANCHWIN_SLOW_MODE_BEFORE,
    BRANCHWIN_SLOW_MODE_PREFETCH_FARCALL
};

#define BRANCHWIN_SLOW_ENTRY(prefix, fnfamily, modefamily, offset)            \
    { "fair_code_prefetchit0_branchwin_slow_" prefix "_head_o" #offset,       \
      branchwin_slow_##fnfamily##_head_t0_o##offset, BRANCHWIN_SLOW_MODE_##modefamily }

#define BRANCHWIN_SLOW_LINES_ENTRY(prefix, fnfamily, modefamily, offset)      \
    { "fair_code_prefetchit0_branchwin_slow_" prefix "_lines_o" #offset,      \
      branchwin_slow_##fnfamily##_lines_t0_o##offset, BRANCHWIN_SLOW_MODE_##modefamily }

#define BRANCHWIN_SLOW_DATAT0_ENTRY(prefix, fnfamily, modefamily, offset)     \
    { "fair_data_prefetcht0_branchwin_slow_" prefix "_lines_o" #offset,       \
      branchwin_slow_##fnfamily##_lines_datat0_o##offset, BRANCHWIN_SLOW_MODE_##modefamily }

#define BRANCHWIN_SLOW_FARBLOCK_ENTRY(kind, offset)                           \
    { "fair_code_prefetchit0_branchwin_slow_target_farblock_" #kind "_o" #offset, \
      branchwin_slow_target_farblock_##kind##_t0_o##offset, BRANCHWIN_SLOW_MODE_TARGET }

#define BRANCHWIN_SLOW_FARBLOCK_DATAT0_ENTRY(offset)                          \
    { "fair_data_prefetcht0_branchwin_slow_target_farblock_lines_o" #offset,  \
      branchwin_slow_target_farblock_lines_datat0_o##offset, BRANCHWIN_SLOW_MODE_TARGET }

#define BRANCHWIN_SLOW_BEFOREFAR_ENTRY(kind, offset)                          \
    { "fair_code_prefetchit0_branchwin_slow_before_farbranch_" #kind "_o" #offset, \
      branchwin_slow_before_farbranch_##kind##_t0_o##offset, BRANCHWIN_SLOW_MODE_BEFORE }

#define BRANCHWIN_SLOW_BEFOREFAR_DATAT0_ENTRY(offset)                         \
    { "fair_data_prefetcht0_branchwin_slow_before_farbranch_lines_o" #offset, \
      branchwin_slow_before_farbranch_lines_datat0_o##offset, BRANCHWIN_SLOW_MODE_BEFORE }

#define BRANCHWIN_SLOW_BEFORESTORM_ENTRY(name_prefix, fn_suffix)              \
    { name_prefix, branchwin_slow_before_farstorm_lines_##fn_suffix, BRANCHWIN_SLOW_MODE_BEFORE }

#define BRANCHWIN_NAKED_BEFORESTORM_ENTRY(name_prefix, fn_suffix)             \
    { name_prefix, branchwin_naked_before_farstorm_##fn_suffix, BRANCHWIN_SLOW_MODE_BEFORE }

#define BRANCHWIN_NAKED_TARGET_ENTRY(name_prefix, fn_suffix, offset)          \
    { name_prefix "_o" #offset, branchwin_naked_target_farblock_##fn_suffix##_o##offset, BRANCHWIN_SLOW_MODE_BEFORE }

#define BRANCHWIN_NAKED_TARGET_MODE_ENTRY(name_prefix, fn_suffix, offset, modefamily) \
    { name_prefix "_o" #offset, branchwin_naked_target_farblock_##fn_suffix##_o##offset, BRANCHWIN_SLOW_MODE_##modefamily }

#define BRANCHWIN_NAKED_FALLTHROUGH_ENTRY(name_prefix, fn_suffix, offset, modefamily) \
    { name_prefix "_o" #offset, branchwin_naked_fallthrough_##fn_suffix##_o##offset, BRANCHWIN_SLOW_MODE_##modefamily }

#define BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY(name_prefix, fn_suffix, offset) \
    { name_prefix "_o" #offset, branchwin_naked_chain_targetpref_##fn_suffix##_o##offset, BRANCHWIN_SLOW_MODE_BEFORE }

#define BRANCHWIN_NAKED_FARCALL_ENTRY(name_prefix, fn_suffix)                 \
    { name_prefix, branchwin_naked_##fn_suffix, BRANCHWIN_SLOW_MODE_PREFETCH_FARCALL }

typedef struct {
    const char *name;
    VoidFn fn;
    int mode;
} BranchwinSlowVariant;

static const BranchwinSlowVariant g_branchwin_slow_variants[] = {
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 0),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 1),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 2),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 3),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 4),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 5),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 6),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 7),
    BRANCHWIN_SLOW_ENTRY("target", target, TARGET, 8),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 0),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 1),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 2),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 3),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 4),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 5),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 6),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 7),
    BRANCHWIN_SLOW_ENTRY("fallwrong", fallwrong, FALLWRONG, 8),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 0),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 1),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 2),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 3),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 4),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 5),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 6),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 7),
    BRANCHWIN_SLOW_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 8),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 0),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 1),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 2),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 3),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 4),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 5),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 6),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 7),
    BRANCHWIN_SLOW_LINES_ENTRY("target", target, TARGET, 8),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 0),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 1),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 2),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 3),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 4),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 5),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 6),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 7),
    BRANCHWIN_SLOW_LINES_ENTRY("fallwrong", fallwrong, FALLWRONG, 8),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 0),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 1),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 2),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 3),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 4),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 5),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 6),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 7),
    BRANCHWIN_SLOW_LINES_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 8),
    BRANCHWIN_SLOW_DATAT0_ENTRY("target", target, TARGET, 5),
    BRANCHWIN_SLOW_DATAT0_ENTRY("fallcorrect", fallcorrect, FALLCORRECT, 1),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 0),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 1),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 2),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 3),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 4),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 5),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 6),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 7),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(head, 8),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 0),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 1),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 2),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 3),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 4),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 5),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 6),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 7),
    BRANCHWIN_SLOW_FARBLOCK_ENTRY(lines, 8),
    BRANCHWIN_SLOW_FARBLOCK_DATAT0_ENTRY(0),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 0),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 1),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 2),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 3),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 4),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 5),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 6),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 7),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(head, 8),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 0),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 1),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 2),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 3),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 4),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 5),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 6),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 7),
    BRANCHWIN_SLOW_BEFOREFAR_ENTRY(lines, 8),
    BRANCHWIN_SLOW_BEFOREFAR_DATAT0_ENTRY(0),
    BRANCHWIN_SLOW_BEFORESTORM_ENTRY("fair_code_prefetchit0_branchwin_slow_before_farstorm_lines", t0),
    BRANCHWIN_SLOW_BEFORESTORM_ENTRY("fair_data_prefetcht0_branchwin_slow_before_farstorm_lines", datat0),
    { "fair_code_prefetchit1_branchwin_slow_target_farblock_lines_o0",
      branchwin_slow_target_farblock_lines_it1_o0, BRANCHWIN_SLOW_MODE_TARGET },
    { "fair_code_prefetchit1_branchwin_slow_before_farbranch_lines_o7",
      branchwin_slow_before_farbranch_lines_it1_o7, BRANCHWIN_SLOW_MODE_BEFORE },
    { "fair_code_prefetchit1_branchwin_slow_before_farstorm_lines",
      branchwin_slow_before_farstorm_lines_it1, BRANCHWIN_SLOW_MODE_BEFORE },
    { "fair_code_prefetchit0_branchwin_slow_both_farblock_lines",
      branchwin_slow_both_farblock_lines_t0, BRANCHWIN_SLOW_MODE_BEFORE },
    { "fair_data_prefetcht0_branchwin_slow_both_farblock_lines",
      branchwin_slow_both_farblock_lines_datat0, BRANCHWIN_SLOW_MODE_BEFORE },
    { "fair_code_prefetchit0_branchwin_slow_before_farstorm_bar_lines",
      branchwin_slow_before_farstorm_bar_lines_t0, BRANCHWIN_SLOW_MODE_BEFORE },
    { "fair_data_prefetcht0_branchwin_slow_before_farstorm_bar_lines",
      branchwin_slow_before_farstorm_bar_lines_datat0, BRANCHWIN_SLOW_MODE_BEFORE },
    { "fair_code_branchwin_slow_before_farstorm_nopref",
      branchwin_slow_before_farstorm_nopref, BRANCHWIN_SLOW_MODE_BEFORE },
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_code_prefetchit0_branchwin_naked_before_farstorm_bar_lines", bar_lines_t0),
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_code_prefetchit1_branchwin_naked_before_farstorm_bar_lines", bar_lines_it1),
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_data_prefetcht0_branchwin_naked_before_farstorm_bar_lines", bar_lines_datat0),
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_code_prefetchit0_branchwin_naked_before_farstorm_lines", lines_t0),
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_code_prefetchit1_branchwin_naked_before_farstorm_lines", lines_it1),
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_data_prefetcht0_branchwin_naked_before_farstorm_lines", lines_datat0),
    BRANCHWIN_NAKED_BEFORESTORM_ENTRY("fair_code_branchwin_naked_before_farstorm_nopref", nopref),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 0),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 1),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 2),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 4),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 8),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 16),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 32),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 64),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_lines", bar_lines_t0, 128),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit1_branchwin_naked_target_farblock_bar_lines", bar_lines_it1, 0),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit1_branchwin_naked_target_farblock_bar_lines", bar_lines_it1, 32),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_data_prefetcht0_branchwin_naked_target_farblock_bar_lines", bar_lines_datat0, 0),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_data_prefetcht0_branchwin_naked_target_farblock_bar_lines", bar_lines_datat0, 32),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_branchwin_naked_target_farblock_nopref", nopref, 0),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_branchwin_naked_target_farblock_nopref", nopref, 32),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit0_branchwin_naked_target_farblock_bar_head", bar_head_t0, 0),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_code_prefetchit1_branchwin_naked_target_farblock_bar_head", bar_head_it1, 0),
    BRANCHWIN_NAKED_TARGET_ENTRY("fair_data_prefetcht0_branchwin_naked_target_farblock_bar_head", bar_head_datat0, 0),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 0, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 1, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 2, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 3, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 4, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 5, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 8, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 12, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_t0, 16, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit1_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_it1, 0, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_data_prefetcht0_branchwin_naked_wrong_fallthrough_bar_lines", bar_lines_datat0, 0, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_branchwin_naked_wrong_fallthrough_nopref", nopref, 0, FALLWRONG),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 0, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 1, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 2, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 3, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 4, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 5, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 8, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 12, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_t0, 16, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_prefetchit1_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_it1, 0, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_data_prefetcht0_branchwin_naked_actual_fallthrough_bar_lines", bar_lines_datat0, 0, FALLCORRECT),
    BRANCHWIN_NAKED_FALLTHROUGH_ENTRY("fair_code_branchwin_naked_actual_fallthrough_nopref", nopref, 0, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_taken_bar_lines", bar_lines_t0, 0, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_taken_bar_lines", bar_lines_t0, 1, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_taken_bar_lines", bar_lines_t0, 2, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_taken_bar_lines", bar_lines_t0, 4, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_prefetchit0_branchwin_naked_wrong_taken_bar_lines", bar_lines_t0, 8, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_prefetchit1_branchwin_naked_wrong_taken_bar_lines", bar_lines_it1, 0, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_data_prefetcht0_branchwin_naked_wrong_taken_bar_lines", bar_lines_datat0, 0, FALLCORRECT),
    BRANCHWIN_NAKED_TARGET_MODE_ENTRY("fair_code_branchwin_naked_wrong_taken_nopref", nopref, 0, FALLCORRECT),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit0_branchwin_naked_chain_targetpref_bar_lines", bar_lines_t0, 0),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit0_branchwin_naked_chain_targetpref_bar_lines", bar_lines_t0, 1),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit0_branchwin_naked_chain_targetpref_bar_lines", bar_lines_t0, 2),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit0_branchwin_naked_chain_targetpref_bar_lines", bar_lines_t0, 4),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit0_branchwin_naked_chain_targetpref_bar_lines", bar_lines_t0, 8),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit1_branchwin_naked_chain_targetpref_bar_lines", bar_lines_it1, 0),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_data_prefetcht0_branchwin_naked_chain_targetpref_bar_lines", bar_lines_datat0, 0),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_branchwin_naked_chain_targetpref_nopref", nopref, 0),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit0_branchwin_naked_chain_targetpref_bar_head", bar_head_t0, 0),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_code_prefetchit1_branchwin_naked_chain_targetpref_bar_head", bar_head_it1, 0),
    BRANCHWIN_NAKED_CHAIN_TARGETPREF_ENTRY("fair_data_prefetcht0_branchwin_naked_chain_targetpref_bar_head", bar_head_datat0, 0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_prefetchit0_branchwin_naked_p2_far2_bar_lines", p2_far2_bar_lines_t0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_prefetchit1_branchwin_naked_p2_far2_bar_lines", p2_far2_bar_lines_it1),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_data_prefetcht0_branchwin_naked_p2_far2_bar_lines", p2_far2_bar_lines_datat0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_branchwin_naked_p2_far2_nopref", p2_far2_nopref),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_prefetchit0_branchwin_naked_p2_far2_bar_head", p2_far2_bar_head_t0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_prefetchit1_branchwin_naked_p2_far2_bar_head", p2_far2_bar_head_it1),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_data_prefetcht0_branchwin_naked_p2_far2_bar_head", p2_far2_bar_head_datat0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_prefetchit0_branchwin_naked_far_p2_far_bar_lines", far_p2_far_bar_lines_t0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_prefetchit1_branchwin_naked_far_p2_far_bar_lines", far_p2_far_bar_lines_it1),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_data_prefetcht0_branchwin_naked_far_p2_far_bar_lines", far_p2_far_bar_lines_datat0),
    BRANCHWIN_NAKED_FARCALL_ENTRY("fair_code_branchwin_naked_far_p2_far_nopref", far_p2_far_nopref),
};

static void train_branchwin_slow_gate(VoidFn fn, int gate_value) {
    setup_branch_chain(gate_value);
    for (int i = 0; i < 192; ++i) {
        fn();
    }
}

static void prepare_slow_actual_gate_miss(int gate_value) {
    setup_branch_chain(gate_value);
    flush_branch_chain_gate();
}

static void run_branchwin_slow_target_t0(VoidFn fn) {
    train_branchwin_slow_gate(fn, 0);
    prepare_slow_actual_gate_miss(1);
    fn();
}

static void run_branchwin_slow_fallwrong_t0(VoidFn fn) {
    train_branchwin_slow_gate(fn, 0);
    flush_target_code();
    shootdown_target_code_tlb();
    prepare_slow_actual_gate_miss(1);
    fn();
}

static void run_branchwin_slow_fallcorrect_t0(VoidFn fn) {
    train_branchwin_slow_gate(fn, 1);
    prepare_slow_actual_gate_miss(0);
    fn();
    setup_branch_chain(1);
}

static void run_branchwin_slow_before_t0(VoidFn fn) {
    train_branchwin_slow_gate(fn, 0);
    flush_code_range((const void *)fn, 32768);
    flush_target_code();
    shootdown_target_code_tlb();
    prepare_slow_actual_gate_miss(1);
    fn();
}

static void run_branchwin_slow_prefetch_farcall_t0(VoidFn fn) {
    flush_code_range((const void *)fn, 32768);
    flush_target_code();
    shootdown_target_code_tlb();
    prepare_far_tlb_miss_calls_strong();
    serialize_cpuid();
    fn();
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
    DELAY_SPIN100K,
    DELAY_ARITH64,
    DELAY_ARITH256,
    DELAY_ARITH512,
    DELAY_ARITH1024,
    DELAY_ARITH2048,
    DELAY_ARITH8192,
    DELAY_ARITH32768,
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
    DELAY_BRANCH4096,
    DELAY_BRANCH8192,
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
    DELAY_PAUSE32768,
    DELAY_PAUSE65536,
    DELAY_CHASE256,
    DELAY_CHASE1024,
    DELAY_CHASE4096,
    DELAY_CHASE16384,
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
    STRATEGY_COMPARE_DATA_PREFETCHT1_LINES,
    STRATEGY_COMPARE_CODE_PREFETCHIT1_FARCALL_LINES,
    STRATEGY_FAIR_ADVANCE_EXECUTION,
    STRATEGY_FAIR_DATA_PREFETCHT0,
    STRATEGY_FAIR_DATA_PREFETCHT0_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT1,
    STRATEGY_FAIR_DATA_PREFETCHT1_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1,
    STRATEGY_FAIR_CODE_PREFETCHIT1_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NOFLUSH_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FORCED_REPEAT_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_MISP_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_CALL_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_INDIRECT_CALL_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_COMPLEX_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_REPEAT_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_BRANCH_CALL_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_INDIRECT_CALL_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_COMPLEX_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_SCATTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_FAR_SCATTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_FAR_DEEP_SCATTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_PER_TARGET_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_PER_TARGET,
    STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_FAR_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_FAR_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_NESTED_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_REPEAT,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_ACTUAL_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_ACTUAL_REPEAT,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_FAR_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_REPEAT,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_FARPATH_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_PATH_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_REPEAT_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_PATH_REPEAT_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_BRANCH_CALL_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_INDIRECT_CALL_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_AFTER_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_CPUID_AFTER_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_SMALL,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_HUGE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_SHAPE_AFTER_FAR_COLDLINE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_AFTER_FAR_COLDLINE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_AFTER_FAR_COLDLINE_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT1_AFTER_FAR_COLDLINE_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_COLDLINE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_COLDLINE_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BETWEEN_COLD_CALLS,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_BRANCH_MISP_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_INDIRECT_MISP_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT16_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT64_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT1_REPEAT16_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT16_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT64_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_SLOW_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_FAR_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_WRONGPATH_SLOW_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT1_WRONGPATH_SLOW_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_SLOW_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_FAR_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_WRONGPATH_DATA_SLOW_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED8_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED32_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED128_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT1_SPACED32_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_ARITH_GAP16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_ARITH_GAP64,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CONTROL_GAP16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CONTROL_GAP64,
    STRATEGY_FAIR_CODE_PREFETCHIT1_ARITH_GAP64,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TWOPHASE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TWOPHASE_LONGGAP,
    STRATEGY_FAIR_CODE_PREFETCHIT1_TWOPHASE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_UNROLLED_SPACED32_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_UNROLLED_SPACED128_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT1_UNROLLED_SPACED32_CPUID_AFTER,
    STRATEGY_FAIR_CODE_SHAPE_FAR_SPACED128,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_SPACED128,
    STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED32_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_SPACED32_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT1_DTLB_PRIME_SPACED32_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_SPACED32_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DEEP_REPEAT4_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_PER_PAGE_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE256,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE1024,
    STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE256_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT1_WRONGPATH_CHASE256_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE4096_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE16384_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE4096_FIXED_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE16384_FIXED_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_INLINE_CHASE4096_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_INLINE_CHASE4096_FIXED_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_SLOW_TAKEN_BRANCH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_PER_PAGE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT1_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DATA_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT1_DATA_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DEEP_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_DEEP_SPACED32_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT1_DEEP_SPACED32_TRAINED_WRONGPATH_FLUSH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PTR_WRONGPATH_DUMMYTRAIN_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_PTR_WRONGPATH_DUMMYTRAIN_PER_PAGE,
    STRATEGY_FAIR_CODE_TLB_OFFSET_PRIME_ONLY,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_PRIME_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_PRIME_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_PRIME_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_PRIME_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BURST4_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BURST8_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BURST4_SPACED128,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BURST4_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_BEFORE_FAR_BIG,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_TLB_OFFSET_FAR_BURST4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P4_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P2_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P4_FAR_TLB4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P_FAR_P_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR2_P2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB2_CPUID_AFTER,
    STRATEGY_FAIR_CODE_PREFETCHIT1_P2_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_TLB4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_P2_STRONG_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_REPEAT,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P2_STRONG_FAR_TLB4,
    STRATEGY_FAIR_CODE_PREFETCHIT1_P2_STRONG_FAR_TLB4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_P2_CPUID_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_P2_FAR_CPUID,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_CPUID_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_FAR_P2_FAR_CPUID,
    STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_P2_CPUID_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_P2_FAR_CPUID,
    STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_CPUID_P2_FAR,
    STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_FAR_P2_FAR_CPUID,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_AB_P2_FAR_CD,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_AB_P4_FAR_CD,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_FAR_AB_P2_FAR_CD,
    STRATEGY_FAIR_CODE_PREFETCHIT0_STRONG_FARFUNC_BURST4_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_STRONG_FARFUNC_PATH_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT1_STRONG_FARFUNC_BURST4_FAR_TLB2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST4_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST8_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST4_SPACED128,
    STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_BURST4_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_FAR_BURST4_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_FAR_BURST8_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_FAR_BURST4_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_PRE10,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_POST10,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_BURST4_PRE10,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_BURST4_POST10,
    STRATEGY_FAIR_CODE_PREFETCHIT1_CALL_WINDOW_BURST4_PRE10,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_CALL_WINDOW_BURST4_PRE10,
    STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_CALL_WINDOW_BURST4_POST10,
    STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_CALL_WINDOW_BURST4_PRE10,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O16,
    STRATEGY_FAIR_CODE_PAGE_PRIME_ONLY,
    STRATEGY_FAIR_CODE_PAGE_SHAPE_LINES,
    STRATEGY_FAIR_CODE_PAGE_SHAPE_SPACED32_LINES,
    STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_LINES,
    STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_SPACED32_LINES,
    STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_SPACED128_LINES,
    STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_REPEAT4_LINES,
    STRATEGY_FAIR_CODE_PAGE_PREFETCHIT1_LINES,
    STRATEGY_FAIR_CODE_PAGE_PREFETCHIT1_SPACED32_LINES,
    STRATEGY_FAIR_CODE_ADJACENT_SHAPE_SPACED32_LINES,
    STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT0_SPACED32_LINES,
    STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT0_SPACED128_LINES,
    STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT1_SPACED32_LINES,
    STRATEGY_FAIR_CODE_TLB_PRIME_SPACED32_SHAPE,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED64,
    STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED128,
    STRATEGY_FAIR_CODE_PREFETCHIT1_CODE_TLB_PRIME_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_CODE_TLB_PRIME_SPACED32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLWRONG_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O8,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_TARGET_LINES_O5,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_FALLCORRECT_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O8,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_HEAD_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O6,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O8,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_SLOW_TARGET_FARBLOCK_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_SLOW_BEFORE_FARBRANCH_LINES_O7,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_SLOW_BEFORE_FARSTORM_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BOTH_FARBLOCK_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_BOTH_FARBLOCK_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_BEFORE_FARSTORM_BAR_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_SLOW_BEFORE_FARSTORM_BAR_LINES,
    STRATEGY_FAIR_CODE_BRANCHWIN_SLOW_BEFORE_FARSTORM_NOPREF,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_BEFORE_FARSTORM_BAR_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_BEFORE_FARSTORM_BAR_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_BEFORE_FARSTORM_BAR_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_BEFORE_FARSTORM_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_BEFORE_FARSTORM_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_BEFORE_FARSTORM_LINES,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_BEFORE_FARSTORM_NOPREF,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O64,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O128,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O32,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_LINES_O32,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_TARGET_FARBLOCK_NOPREF_O0,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_TARGET_FARBLOCK_NOPREF_O32,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_HEAD_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_TARGET_FARBLOCK_BAR_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O12,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_WRONG_FALLTHROUGH_NOPREF_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O3,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O5,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O12,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O16,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_ACTUAL_FALLTHROUGH_NOPREF_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_WRONG_TAKEN_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_WRONG_TAKEN_NOPREF_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O1,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O2,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O4,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O8,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_LINES_O0,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_CHAIN_TARGETPREF_NOPREF_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_HEAD_O0,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_CHAIN_TARGETPREF_BAR_HEAD_O0,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_P2_FAR2_BAR_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_P2_FAR2_BAR_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_P2_FAR2_BAR_LINES,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_P2_FAR2_NOPREF,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_P2_FAR2_BAR_HEAD,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_P2_FAR2_BAR_HEAD,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_P2_FAR2_BAR_HEAD,
    STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_NAKED_FAR_P2_FAR_BAR_LINES,
    STRATEGY_FAIR_CODE_PREFETCHIT1_BRANCHWIN_NAKED_FAR_P2_FAR_BAR_LINES,
    STRATEGY_FAIR_DATA_PREFETCHT0_BRANCHWIN_NAKED_FAR_P2_FAR_BAR_LINES,
    STRATEGY_FAIR_CODE_BRANCHWIN_NAKED_FAR_P2_FAR_NOPREF,
    STRATEGY_COUNT
} StrategyKind;

typedef struct {
    double mean;
    uint64_t min;
    uint64_t p05;
    uint64_t p25;
    uint64_t p50;
    uint64_t p75;
    uint64_t p95;
    uint64_t p99;
    uint64_t max;
} Summary;

typedef struct {
    uint64_t *cycles;
    uint64_t *l1i_miss;
    uint64_t *itlb_miss;
    uint64_t *itlb_stlb_hit;
    uint64_t *itlb_walk;
    uint64_t *itlb_miss_est;
    uint64_t *prep_itlb_walk;
    uint64_t *prep_dtlb_walk;
    uint64_t *prep_branch_miss;
    uint64_t *l2_code_rd;
    uint64_t *l2_code_miss;
    uint64_t *l2_all_miss;
    uint64_t *llc_load_miss;
    uint64_t *llc_miss;
    uint64_t *insn;
    int count;
    Summary latency;
    Summary l1i;
    Summary itlb;
    Summary itlb_stlb_hit_summary;
    Summary itlb_walk_summary;
    Summary itlb_miss_est_summary;
    Summary prep_itlb_walk_summary;
    Summary prep_dtlb_walk_summary;
    Summary prep_branch_miss_summary;
    Summary l2_code;
    Summary l2_code_miss_summary;
    Summary l2_all_miss_summary;
    Summary llc_load;
    Summary llc;
    Summary insn_summary;
} Stats;

static int branchwin_slow_index(StrategyKind kind) {
    int idx = (int)kind - (int)STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_SLOW_TARGET_HEAD_O0;
    int count = (int)(sizeof(g_branchwin_slow_variants) / sizeof(g_branchwin_slow_variants[0]));
    return (idx >= 0 && idx < count) ? idx : -1;
}

static const char *branchwin_slow_strategy_name(StrategyKind kind) {
    int idx = branchwin_slow_index(kind);
    return (idx >= 0) ? g_branchwin_slow_variants[idx].name : NULL;
}

static int run_branchwin_slow_strategy(StrategyKind kind) {
    int idx = branchwin_slow_index(kind);
    if (idx < 0) {
        return 0;
    }
    const BranchwinSlowVariant *variant = &g_branchwin_slow_variants[idx];
    switch (variant->mode) {
    case BRANCHWIN_SLOW_MODE_TARGET:
        run_branchwin_slow_target_t0(variant->fn);
        break;
    case BRANCHWIN_SLOW_MODE_FALLWRONG:
        run_branchwin_slow_fallwrong_t0(variant->fn);
        break;
    case BRANCHWIN_SLOW_MODE_FALLCORRECT:
        run_branchwin_slow_fallcorrect_t0(variant->fn);
        break;
    case BRANCHWIN_SLOW_MODE_BEFORE:
        run_branchwin_slow_before_t0(variant->fn);
        break;
    case BRANCHWIN_SLOW_MODE_PREFETCH_FARCALL:
        run_branchwin_slow_prefetch_farcall_t0(variant->fn);
        break;
    default:
        return 0;
    }
    return 1;
}

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
    case DELAY_SPIN100K: return "spin100k";
    case DELAY_ARITH64: return "arith64";
    case DELAY_ARITH256: return "arith256";
    case DELAY_ARITH512: return "arith512";
    case DELAY_ARITH1024: return "arith1024";
    case DELAY_ARITH2048: return "arith2048";
    case DELAY_ARITH8192: return "arith8192";
    case DELAY_ARITH32768: return "arith32768";
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
    case DELAY_BRANCH4096: return "branch4096";
    case DELAY_BRANCH8192: return "branch8192";
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
    case DELAY_PAUSE32768: return "pause32768";
    case DELAY_PAUSE65536: return "pause65536";
    case DELAY_CHASE256: return "chase256";
    case DELAY_CHASE1024: return "chase1024";
    case DELAY_CHASE4096: return "chase4096";
    case DELAY_CHASE16384: return "chase16384";
    case DELAY_COMPLEX_LIGHT: return "complex_light";
    case DELAY_COMPLEX_HEAVY: return "complex_heavy";
    case DELAY_COUNT: break;
    }
    return "unknown";
}

static const char *strategy_name(StrategyKind kind) {
    const char *slow_branchwin_name = branchwin_slow_strategy_name(kind);
    if (slow_branchwin_name) {
        return slow_branchwin_name;
    }
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
    case STRATEGY_COMPARE_DATA_PREFETCHT1_LINES: return "compare_data_prefetcht1_lines";
    case STRATEGY_COMPARE_CODE_PREFETCHIT1_FARCALL_LINES: return "compare_code_prefetchit1_farcall_lines";
    case STRATEGY_FAIR_ADVANCE_EXECUTION: return "fair_advance_execution";
    case STRATEGY_FAIR_DATA_PREFETCHT0: return "fair_data_prefetcht0";
    case STRATEGY_FAIR_DATA_PREFETCHT0_LINES: return "fair_data_prefetcht0_lines";
    case STRATEGY_FAIR_DATA_PREFETCHT1: return "fair_data_prefetcht1";
    case STRATEGY_FAIR_DATA_PREFETCHT1_LINES: return "fair_data_prefetcht1_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0: return "fair_code_prefetchit0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_LINES: return "fair_code_prefetchit0_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT1: return "fair_code_prefetchit1";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_LINES: return "fair_code_prefetchit1_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NOFLUSH_LINES: return "fair_code_prefetchit0_noflush_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FORCED_REPEAT_LINES: return "fair_code_prefetchit0_forced_repeat_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_MISP_LINES: return "fair_code_prefetchit0_branch_misp_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_CALL_LINES: return "fair_code_prefetchit0_branch_call_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INDIRECT_CALL_LINES: return "fair_code_prefetchit0_indirect_call_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_COMPLEX_LINES: return "fair_code_prefetchit0_complex_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_LINES: return "fair_code_prefetchit0_path_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_REPEAT_LINES: return "fair_code_prefetchit0_path_repeat_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_BRANCH_CALL_LINES: return "fair_code_prefetchit0_path_branch_call_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_INDIRECT_CALL_LINES: return "fair_code_prefetchit0_path_indirect_call_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_COMPLEX_LINES: return "fair_code_prefetchit0_path_complex_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_SCATTER: return "fair_code_prefetchit0_nested_scatter";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_FAR_SCATTER: return "fair_code_prefetchit0_nested_far_scatter";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_FAR_DEEP_SCATTER: return "fair_code_prefetchit0_nested_far_deep_scatter";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_PER_TARGET_FAR: return "fair_code_prefetchit0_nested_per_target_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_P2_FAR: return "fair_code_prefetchit0_nested_window_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_PER_TARGET: return "fair_code_prefetchit0_nested_window_per_target";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_FAR_P2_FAR: return "fair_code_prefetchit0_nested_window_far_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_P2_FAR: return "fair_code_prefetchit0_branch_actual_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_FAR_P2_FAR: return "fair_code_prefetchit0_branch_actual_far_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_NESTED_P2_FAR: return "fair_code_prefetchit0_branch_actual_nested_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_REPEAT: return "fair_code_prefetchit0_branch_actual_repeat";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_ACTUAL_P2_FAR: return "fair_code_prefetchit0_far_branch_actual_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_ACTUAL_REPEAT: return "fair_code_prefetchit0_far_branch_actual_repeat";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_P2_FAR: return "fair_code_prefetchit0_branch_farpath_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_FAR_P2_FAR: return "fair_code_prefetchit0_branch_farpath_far_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_REPEAT: return "fair_code_prefetchit0_branch_farpath_repeat";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_FARPATH_P2_FAR: return "fair_code_prefetchit0_far_branch_farpath_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_LINES: return "fair_code_prefetchit0_dtlb_prime_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_PATH_LINES: return "fair_code_prefetchit0_dtlb_prime_path_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_REPEAT_LINES: return "fair_code_prefetchit0_dtlb_prime_repeat_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_PATH_REPEAT_LINES: return "fair_code_prefetchit0_dtlb_prime_path_repeat_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_BRANCH_CALL_LINES: return "fair_code_prefetchit0_dtlb_prime_branch_call_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_INDIRECT_CALL_LINES: return "fair_code_prefetchit0_dtlb_prime_indirect_call_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_AFTER_LINES: return "fair_code_prefetchit0_cpuid_after_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_CPUID_AFTER_LINES: return "fair_code_prefetchit0_path_cpuid_after_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_SMALL: return "fair_code_prefetchit0_before_far_small";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_BIG: return "fair_code_prefetchit0_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_HUGE: return "fair_code_prefetchit0_before_far_huge";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_CPUID_AFTER: return "fair_code_prefetchit0_before_far_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_BEFORE_FAR_BIG: return "fair_code_prefetchit0_path_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_BEFORE_FAR_BIG: return "fair_code_prefetchit1_before_far_big";
    case STRATEGY_FAIR_CODE_SHAPE_AFTER_FAR_COLDLINE: return "fair_code_shape_after_far_coldline";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_AFTER_FAR_COLDLINE: return "fair_code_prefetchit0_after_far_coldline";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_AFTER_FAR_COLDLINE_SPACED32: return "fair_code_prefetchit0_after_far_coldline_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_AFTER_FAR_COLDLINE_SPACED32: return "fair_code_prefetchit1_after_far_coldline_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_COLDLINE: return "fair_code_prefetchit0_before_far_coldline";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_COLDLINE_SPACED32: return "fair_code_prefetchit0_before_far_coldline_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BETWEEN_COLD_CALLS: return "fair_code_prefetchit0_between_cold_calls";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_BRANCH_MISP_FAR: return "fair_code_prefetchit0_before_branch_misp_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_INDIRECT_MISP_FAR: return "fair_code_prefetchit0_before_indirect_misp_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT16_CPUID_AFTER: return "fair_code_prefetchit0_repeat16_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT64_CPUID_AFTER: return "fair_code_prefetchit0_repeat64_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_REPEAT16_CPUID_AFTER: return "fair_code_prefetchit1_repeat16_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT16_BEFORE_FAR_BIG: return "fair_code_prefetchit0_repeat16_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT64_BEFORE_FAR_BIG: return "fair_code_prefetchit0_repeat64_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_SLOW_BRANCH: return "fair_code_prefetchit0_wrongpath_slow_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CPUID_AFTER: return "fair_code_prefetchit0_wrongpath_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_FAR_AFTER: return "fair_code_prefetchit0_wrongpath_far_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_WRONGPATH_SLOW_BRANCH: return "fair_code_prefetchit0_path_wrongpath_slow_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_WRONGPATH_SLOW_BRANCH: return "fair_code_prefetchit1_wrongpath_slow_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_SLOW_BRANCH: return "fair_code_prefetchit0_wrongpath_data_slow_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_CPUID_AFTER: return "fair_code_prefetchit0_wrongpath_data_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_FAR_AFTER: return "fair_code_prefetchit0_wrongpath_data_far_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_WRONGPATH_DATA_SLOW_BRANCH: return "fair_code_prefetchit0_path_wrongpath_data_slow_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED8_CPUID_AFTER: return "fair_code_prefetchit0_spaced8_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED32_CPUID_AFTER: return "fair_code_prefetchit0_spaced32_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED128_CPUID_AFTER: return "fair_code_prefetchit0_spaced128_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_SPACED32_CPUID_AFTER: return "fair_code_prefetchit1_spaced32_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_ARITH_GAP16: return "fair_code_prefetchit0_arith_gap16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_ARITH_GAP64: return "fair_code_prefetchit0_arith_gap64";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CONTROL_GAP16: return "fair_code_prefetchit0_control_gap16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CONTROL_GAP64: return "fair_code_prefetchit0_control_gap64";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_ARITH_GAP64: return "fair_code_prefetchit1_arith_gap64";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TWOPHASE: return "fair_code_prefetchit0_twophase";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TWOPHASE_LONGGAP: return "fair_code_prefetchit0_twophase_longgap";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TWOPHASE: return "fair_code_prefetchit1_twophase";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_UNROLLED_SPACED32_CPUID_AFTER: return "fair_code_prefetchit0_unrolled_spaced32_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_UNROLLED_SPACED128_CPUID_AFTER: return "fair_code_prefetchit0_unrolled_spaced128_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_UNROLLED_SPACED32_CPUID_AFTER: return "fair_code_prefetchit1_unrolled_spaced32_cpuid_after";
    case STRATEGY_FAIR_CODE_SHAPE_FAR_SPACED128: return "fair_code_shape_far_spaced128";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_SPACED32: return "fair_code_prefetchit0_far_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_SPACED128: return "fair_code_prefetchit0_far_spaced128";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_SPACED32: return "fair_code_prefetchit1_far_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED32_BEFORE_FAR_BIG: return "fair_code_prefetchit0_spaced32_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_SPACED32_CPUID_AFTER: return "fair_code_prefetchit0_dtlb_prime_spaced32_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_DTLB_PRIME_SPACED32_CPUID_AFTER: return "fair_code_prefetchit1_dtlb_prime_spaced32_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_SPACED32_BEFORE_FAR_BIG: return "fair_code_prefetchit0_dtlb_prime_spaced32_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DEEP_REPEAT4_CPUID_AFTER: return "fair_code_prefetchit0_wrongpath_deep_repeat4_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_PER_PAGE_CPUID_AFTER: return "fair_code_prefetchit0_wrongpath_per_page_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE256: return "fair_code_prefetchit0_wrongpath_chase256";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE1024: return "fair_code_prefetchit0_wrongpath_chase1024";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE256_CPUID_AFTER: return "fair_code_prefetchit0_wrongpath_chase256_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_WRONGPATH_CHASE256_CPUID_AFTER: return "fair_code_prefetchit1_wrongpath_chase256_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE4096_BURST4: return "fair_code_prefetchit0_inline_chase4096_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE16384_BURST4: return "fair_code_prefetchit0_inline_chase16384_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE4096_FIXED_BURST4: return "fair_code_prefetchit0_inline_chase4096_fixed_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE16384_FIXED_BURST4: return "fair_code_prefetchit0_inline_chase16384_fixed_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_INLINE_CHASE4096_BURST4: return "fair_code_prefetchit0_trained_inline_chase4096_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_INLINE_CHASE4096_FIXED_BURST4: return "fair_code_prefetchit0_trained_inline_chase4096_fixed_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_BRANCH: return "fair_code_prefetchit0_slow_taken_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_CPUID_AFTER: return "fair_code_prefetchit0_slow_taken_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_SLOW_TAKEN_BRANCH: return "fair_code_prefetchit0_path_slow_taken_branch";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_PER_PAGE: return "fair_code_prefetchit0_slow_taken_per_page";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit0_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit1_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DATA_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit0_data_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_DATA_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit1_data_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DEEP_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit0_deep_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DEEP_SPACED32_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit0_deep_spaced32_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_DEEP_SPACED32_TRAINED_WRONGPATH_FLUSH: return "fair_code_prefetchit1_deep_spaced32_trained_wrongpath_flush";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PTR_WRONGPATH_DUMMYTRAIN_SPACED32: return "fair_code_prefetchit0_ptr_wrongpath_dummytrain_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PTR_WRONGPATH_DUMMYTRAIN_PER_PAGE: return "fair_code_prefetchit0_ptr_wrongpath_dummytrain_per_page";
    case STRATEGY_FAIR_CODE_TLB_OFFSET_PRIME_ONLY: return "fair_code_tlb_offset_prime_only";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_PRIME_LINES: return "fair_code_prefetchit0_tlb_offset_prime_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_PRIME_SPACED32: return "fair_code_prefetchit0_tlb_offset_prime_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_PRIME_LINES: return "fair_code_prefetchit1_tlb_offset_prime_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_PRIME_SPACED32: return "fair_code_prefetchit1_tlb_offset_prime_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BURST4_SPACED32: return "fair_code_prefetchit0_burst4_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BURST8_SPACED32: return "fair_code_prefetchit0_burst8_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BURST4_SPACED128: return "fair_code_prefetchit0_burst4_spaced128";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_BURST4_SPACED32: return "fair_code_prefetchit1_burst4_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH: return "fair_code_prefetchit0_fixed_path";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_SPACED32: return "fair_code_prefetchit0_fixed_path_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_BURST4: return "fair_code_prefetchit0_fixed_path_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_BEFORE_FAR_BIG: return "fair_code_prefetchit0_fixed_path_before_far_big";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_TLB_OFFSET_FAR_BURST4: return "fair_code_prefetchit0_fixed_path_tlb_offset_far_burst4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB2: return "fair_code_prefetchit0_p2_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P4_FAR_TLB2: return "fair_code_prefetchit0_p4_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB4: return "fair_code_prefetchit0_p2_far_tlb4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P2_FAR_TLB2: return "fair_code_prefetchit0_fixed_p2_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P4_FAR_TLB4: return "fair_code_prefetchit0_fixed_p4_far_tlb4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P_FAR_P_FAR: return "fair_code_prefetchit0_p_far_p_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_P2_FAR: return "fair_code_prefetchit0_far_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR2_P2: return "fair_code_prefetchit0_far2_p2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB2_CPUID_AFTER: return "fair_code_prefetchit0_p2_far_tlb2_cpuid_after";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_P2_FAR_TLB2: return "fair_code_prefetchit1_p2_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_TLB2: return "fair_code_prefetchit0_p2_strong_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_TLB4: return "fair_code_prefetchit0_p2_strong_far_tlb4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_P2_STRONG_FAR: return "fair_code_prefetchit0_far_p2_strong_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_REPEAT: return "fair_code_prefetchit0_p2_strong_far_repeat";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P2_STRONG_FAR_TLB4: return "fair_code_prefetchit0_fixed_p2_strong_far_tlb4";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_P2_STRONG_FAR_TLB4: return "fair_code_prefetchit1_p2_strong_far_tlb4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_P2_CPUID_FAR: return "fair_code_prefetchit0_cpuid_p2_cpuid_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_P2_FAR_CPUID: return "fair_code_prefetchit0_cpuid_p2_far_cpuid";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_CPUID_P2_FAR: return "fair_code_prefetchit0_far_cpuid_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_FAR_P2_FAR_CPUID: return "fair_code_prefetchit0_cpuid_far_p2_far_cpuid";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_P2_CPUID_FAR: return "fair_code_prefetchit1_cpuid_p2_cpuid_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_P2_FAR_CPUID: return "fair_code_prefetchit1_cpuid_p2_far_cpuid";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_CPUID_P2_FAR: return "fair_code_prefetchit1_far_cpuid_p2_far";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_FAR_P2_FAR_CPUID: return "fair_code_prefetchit1_cpuid_far_p2_far_cpuid";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_AB_P2_FAR_CD: return "fair_code_prefetchit0_far_ab_p2_far_cd";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_AB_P4_FAR_CD: return "fair_code_prefetchit0_far_ab_p4_far_cd";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_FAR_AB_P2_FAR_CD: return "fair_code_prefetchit0_fixed_far_ab_p2_far_cd";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_STRONG_FARFUNC_BURST4_FAR_TLB2: return "fair_code_prefetchit0_strong_farfunc_burst4_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_STRONG_FARFUNC_PATH_FAR_TLB2: return "fair_code_prefetchit0_strong_farfunc_path_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_STRONG_FARFUNC_BURST4_FAR_TLB2: return "fair_code_prefetchit1_strong_farfunc_burst4_far_tlb2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST4_SPACED32: return "fair_code_prefetchit0_far_burst4_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST8_SPACED32: return "fair_code_prefetchit0_far_burst8_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST4_SPACED128: return "fair_code_prefetchit0_far_burst4_spaced128";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_BURST4_SPACED32: return "fair_code_prefetchit1_far_burst4_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_FAR_BURST4_SPACED32: return "fair_code_prefetchit0_tlb_offset_far_burst4_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_FAR_BURST8_SPACED32: return "fair_code_prefetchit0_tlb_offset_far_burst8_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_FAR_BURST4_SPACED32: return "fair_code_prefetchit1_tlb_offset_far_burst4_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_PRE10: return "fair_code_prefetchit0_call_window_pre10";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_POST10: return "fair_code_prefetchit0_call_window_post10";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_BURST4_PRE10: return "fair_code_prefetchit0_call_window_burst4_pre10";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_BURST4_POST10: return "fair_code_prefetchit0_call_window_burst4_post10";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CALL_WINDOW_BURST4_PRE10: return "fair_code_prefetchit1_call_window_burst4_pre10";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_CALL_WINDOW_BURST4_PRE10: return "fair_code_prefetchit0_tlb_offset_call_window_burst4_pre10";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_CALL_WINDOW_BURST4_POST10: return "fair_code_prefetchit0_tlb_offset_call_window_burst4_post10";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_CALL_WINDOW_BURST4_PRE10: return "fair_code_prefetchit1_tlb_offset_call_window_burst4_pre10";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O0: return "fair_code_prefetchit0_branchwin_target_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O1: return "fair_code_prefetchit0_branchwin_target_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O2: return "fair_code_prefetchit0_branchwin_target_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O4: return "fair_code_prefetchit0_branchwin_target_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O8: return "fair_code_prefetchit0_branchwin_target_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O16: return "fair_code_prefetchit0_branchwin_target_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O0: return "fair_code_prefetchit0_branchwin_wrong_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O1: return "fair_code_prefetchit0_branchwin_wrong_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O2: return "fair_code_prefetchit0_branchwin_wrong_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O4: return "fair_code_prefetchit0_branchwin_wrong_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O8: return "fair_code_prefetchit0_branchwin_wrong_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O16: return "fair_code_prefetchit0_branchwin_wrong_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O0: return "fair_code_prefetchit0_branchwin_before_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O1: return "fair_code_prefetchit0_branchwin_before_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O2: return "fair_code_prefetchit0_branchwin_before_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O4: return "fair_code_prefetchit0_branchwin_before_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O8: return "fair_code_prefetchit0_branchwin_before_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O16: return "fair_code_prefetchit0_branchwin_before_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O0: return "fair_code_prefetchit0_branchwin_target_head_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O1: return "fair_code_prefetchit0_branchwin_target_head_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O2: return "fair_code_prefetchit0_branchwin_target_head_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O4: return "fair_code_prefetchit0_branchwin_target_head_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O8: return "fair_code_prefetchit0_branchwin_target_head_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O16: return "fair_code_prefetchit0_branchwin_target_head_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O0: return "fair_code_prefetchit0_branchwin_wrong_head_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O1: return "fair_code_prefetchit0_branchwin_wrong_head_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O2: return "fair_code_prefetchit0_branchwin_wrong_head_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O4: return "fair_code_prefetchit0_branchwin_wrong_head_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O8: return "fair_code_prefetchit0_branchwin_wrong_head_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O16: return "fair_code_prefetchit0_branchwin_wrong_head_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O0: return "fair_code_prefetchit0_branchwin_fallwrong_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O1: return "fair_code_prefetchit0_branchwin_fallwrong_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O2: return "fair_code_prefetchit0_branchwin_fallwrong_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O4: return "fair_code_prefetchit0_branchwin_fallwrong_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O8: return "fair_code_prefetchit0_branchwin_fallwrong_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O16: return "fair_code_prefetchit0_branchwin_fallwrong_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O0: return "fair_code_prefetchit0_branchwin_fallcorrect_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O1: return "fair_code_prefetchit0_branchwin_fallcorrect_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O2: return "fair_code_prefetchit0_branchwin_fallcorrect_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O4: return "fair_code_prefetchit0_branchwin_fallcorrect_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O8: return "fair_code_prefetchit0_branchwin_fallcorrect_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O16: return "fair_code_prefetchit0_branchwin_fallcorrect_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O0: return "fair_code_prefetchit0_branchwin_fallwrong_head_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O1: return "fair_code_prefetchit0_branchwin_fallwrong_head_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O2: return "fair_code_prefetchit0_branchwin_fallwrong_head_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O4: return "fair_code_prefetchit0_branchwin_fallwrong_head_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O8: return "fair_code_prefetchit0_branchwin_fallwrong_head_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O16: return "fair_code_prefetchit0_branchwin_fallwrong_head_o16";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O0: return "fair_code_prefetchit0_branchwin_fallcorrect_head_o0";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O1: return "fair_code_prefetchit0_branchwin_fallcorrect_head_o1";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O2: return "fair_code_prefetchit0_branchwin_fallcorrect_head_o2";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O4: return "fair_code_prefetchit0_branchwin_fallcorrect_head_o4";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O8: return "fair_code_prefetchit0_branchwin_fallcorrect_head_o8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O16: return "fair_code_prefetchit0_branchwin_fallcorrect_head_o16";
    case STRATEGY_FAIR_CODE_PAGE_PRIME_ONLY: return "fair_code_page_prime_only";
    case STRATEGY_FAIR_CODE_PAGE_SHAPE_LINES: return "fair_code_page_shape_lines";
    case STRATEGY_FAIR_CODE_PAGE_SHAPE_SPACED32_LINES: return "fair_code_page_shape_spaced32_lines";
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_LINES: return "fair_code_page_prefetchit0_lines";
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_SPACED32_LINES: return "fair_code_page_prefetchit0_spaced32_lines";
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_SPACED128_LINES: return "fair_code_page_prefetchit0_spaced128_lines";
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_REPEAT4_LINES: return "fair_code_page_prefetchit0_repeat4_lines";
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT1_LINES: return "fair_code_page_prefetchit1_lines";
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT1_SPACED32_LINES: return "fair_code_page_prefetchit1_spaced32_lines";
    case STRATEGY_FAIR_CODE_ADJACENT_SHAPE_SPACED32_LINES: return "fair_code_adjacent_shape_spaced32_lines";
    case STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT0_SPACED32_LINES: return "fair_code_adjacent_prefetchit0_spaced32_lines";
    case STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT0_SPACED128_LINES: return "fair_code_adjacent_prefetchit0_spaced128_lines";
    case STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT1_SPACED32_LINES: return "fair_code_adjacent_prefetchit1_spaced32_lines";
    case STRATEGY_FAIR_CODE_TLB_PRIME_SPACED32_SHAPE: return "fair_code_tlb_prime_spaced32_shape";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_LINES: return "fair_code_prefetchit0_code_tlb_prime_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED8: return "fair_code_prefetchit0_code_tlb_prime_spaced8";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED32: return "fair_code_prefetchit0_code_tlb_prime_spaced32";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED64: return "fair_code_prefetchit0_code_tlb_prime_spaced64";
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED128: return "fair_code_prefetchit0_code_tlb_prime_spaced128";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CODE_TLB_PRIME_LINES: return "fair_code_prefetchit1_code_tlb_prime_lines";
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CODE_TLB_PRIME_SPACED32: return "fair_code_prefetchit1_code_tlb_prime_spaced32";
    case STRATEGY_COUNT: break;
    default: break;
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
    case DELAY_SPIN100K:
        delay_spin(100000);
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
    case DELAY_ARITH8192:
        (void)delay_arith(seed, 8192);
        break;
    case DELAY_ARITH32768:
        (void)delay_arith(seed, 32768);
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
    case DELAY_BRANCH4096:
        (void)delay_branchy(seed, 4096);
        break;
    case DELAY_BRANCH8192:
        (void)delay_branchy(seed, 8192);
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
    case DELAY_PAUSE32768:
        delay_pause_loop(32768);
        break;
    case DELAY_PAUSE65536:
        delay_pause_loop(65536);
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
    case DELAY_CHASE16384:
        (void)delay_chase(16384);
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
static void shootdown_code_page_tlb_strong(void (*fn)(void));

static void call_cold_prefetch_func(void (*fn)(void), size_t bytes) {
    flush_code_range((const void *)fn, bytes);
    asm volatile("mfence\n\tlfence" ::: "memory");
    fn();
}

static void call_forced_prefetch_func(void (*fn)(void), size_t bytes) {
    flush_code_range((const void *)fn, bytes);
    asm volatile("mfence\n\tlfence" ::: "memory");
    serialize_cpuid();
    fn();
}

static void call_forced_prefetch_func_strong(void (*fn)(void), size_t bytes) {
    flush_code_range((const void *)fn, bytes);
    shootdown_code_page_tlb_strong(fn);
    asm volatile("mfence\n\tlfence" ::: "memory");
    serialize_cpuid();
    fn();
}

static void prepare_cold_call_target(void (*fn)(void), size_t bytes) {
    flush_code_range((const void *)fn, bytes);
    asm volatile("mfence\n\tlfence" ::: "memory");
}

static void shootdown_code_page_tlb(void (*fn)(void)) {
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        return;
    }
    uintptr_t page = (uintptr_t)fn & ~((uintptr_t)page_size - 1u);
    (void)mprotect((void *)page, (size_t)page_size, PROT_READ | PROT_EXEC);
}

static void shootdown_code_page_tlb_strong(void (*fn)(void)) {
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        return;
    }
    uintptr_t page = (uintptr_t)fn & ~((uintptr_t)page_size - 1u);
    (void)mprotect((void *)page, (size_t)page_size, PROT_NONE);
    (void)mprotect((void *)page, (size_t)page_size, PROT_READ | PROT_EXEC);
}

static void prepare_far_tlb_miss_calls_common(int strong) {
    flush_code_range((const void *)farcall_tlb_miss_a, 128);
    flush_code_range((const void *)farcall_tlb_miss_b, 128);
    flush_code_range((const void *)farcall_tlb_miss_c, 128);
    flush_code_range((const void *)farcall_tlb_miss_d, 128);
    if (strong) {
        shootdown_code_page_tlb_strong(farcall_tlb_miss_a);
        shootdown_code_page_tlb_strong(farcall_tlb_miss_b);
        shootdown_code_page_tlb_strong(farcall_tlb_miss_c);
        shootdown_code_page_tlb_strong(farcall_tlb_miss_d);
    } else {
        shootdown_code_page_tlb(farcall_tlb_miss_a);
        shootdown_code_page_tlb(farcall_tlb_miss_b);
        shootdown_code_page_tlb(farcall_tlb_miss_c);
        shootdown_code_page_tlb(farcall_tlb_miss_d);
    }
    asm volatile("mfence\n\tlfence" ::: "memory");
}

static void prepare_far_tlb_miss_calls(void) {
    prepare_far_tlb_miss_calls_common(0);
}

static void prepare_far_tlb_miss_calls_strong(void) {
    prepare_far_tlb_miss_calls_common(1);
}

static void call_far_tlb_miss_pair(void) {
    farcall_tlb_miss_a();
    farcall_tlb_miss_b();
}

static void call_far_tlb_miss_pair_cd(void) {
    farcall_tlb_miss_c();
    farcall_tlb_miss_d();
}

static void call_far_tlb_miss_quad(void) {
    farcall_tlb_miss_a();
    farcall_tlb_miss_b();
    farcall_tlb_miss_c();
    farcall_tlb_miss_d();
}

static void run_strategy(StrategyKind strategy, int seed) {
    if (run_branchwin_slow_strategy(strategy)) {
        return;
    }
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
    case STRATEGY_COMPARE_DATA_PREFETCHT1_LINES:
        prefetcht1_target_lines();
        break;
    case STRATEGY_COMPARE_CODE_PREFETCHIT1_FARCALL_LINES:
        call_cold_prefetch_func(farcall_prefetchit1_lines, 4096);
        break;
    case STRATEGY_FAIR_ADVANCE_EXECUTION:
        (void)call_measured_targets(seed);
        break;
    case STRATEGY_FAIR_DATA_PREFETCHT0:
        prefetcht_targets_direct();
        break;
    case STRATEGY_FAIR_DATA_PREFETCHT0_LINES:
        prefetcht_target_lines();
        break;
    case STRATEGY_FAIR_DATA_PREFETCHT1:
        prefetcht1_targets_direct();
        break;
    case STRATEGY_FAIR_DATA_PREFETCHT1_LINES:
        prefetcht1_target_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0:
        call_forced_prefetch_func(farcall_prefetchit0_small, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_LINES:
        call_forced_prefetch_func(farcall_prefetchit0_lines, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1:
        call_forced_prefetch_func(farcall_prefetchit1_small, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_LINES:
        call_forced_prefetch_func(farcall_prefetchit1_lines, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NOFLUSH_LINES:
        serialize_cpuid();
        farcall_prefetchit0_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FORCED_REPEAT_LINES:
        call_forced_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_MISP_LINES:
        serialize_cpuid();
        trained_branch_prefetchit0_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_CALL_LINES:
        serialize_cpuid();
        trained_branch_call_prefetchit0_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INDIRECT_CALL_LINES:
        serialize_cpuid();
        trained_indirect_call_prefetchit0_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_COMPLEX_LINES:
        serialize_cpuid();
        complex_control_prefetchit0_lines((uint64_t)(uint32_t)seed);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_LINES:
        call_forced_prefetch_func(farcall_prefetchit0_path_lines, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_REPEAT_LINES:
        call_forced_prefetch_func(farcall_prefetchit0_path_lines_repeat, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_BRANCH_CALL_LINES:
        serialize_cpuid();
        trained_branch_call_prefetchit0_path_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_INDIRECT_CALL_LINES:
        serialize_cpuid();
        trained_indirect_call_prefetchit0_path_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_COMPLEX_LINES:
        serialize_cpuid();
        complex_control_prefetchit0_path_lines((uint64_t)(uint32_t)seed);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_SCATTER:
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        nested_branch_prefetchit0_scatter((uint64_t)(uint32_t)seed, 0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_FAR_SCATTER:
        prepare_slow_branch_false_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        nested_branch_prefetchit0_scatter((uint64_t)(uint32_t)seed, 1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_FAR_DEEP_SCATTER:
        prepare_slow_branch_false_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        nested_branch_prefetchit0_scatter((uint64_t)(uint32_t)seed, 3);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_PER_TARGET_FAR:
        prepare_slow_branch_false_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        nested_branch_prefetchit0_per_target((uint64_t)(uint32_t)seed, 1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_P2_FAR:
        prepare_slow_branch_false_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        nested_branch_prefetchit0_window((uint64_t)(uint32_t)seed, 0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_PER_TARGET:
        prepare_slow_branch_false_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        nested_branch_prefetchit0_window((uint64_t)(uint32_t)seed, 1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_NESTED_WINDOW_FAR_P2_FAR:
        prepare_slow_branch_false_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        nested_branch_prefetchit0_window((uint64_t)(uint32_t)seed, 2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_P2_FAR:
        train_branch_actual_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_actual_prefetchit0_window((uint64_t)(uint32_t)seed, 0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_FAR_P2_FAR:
        train_branch_actual_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_actual_prefetchit0_window((uint64_t)(uint32_t)seed, 1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_NESTED_P2_FAR:
        train_branch_actual_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_actual_prefetchit0_window((uint64_t)(uint32_t)seed, 2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_ACTUAL_REPEAT:
        train_branch_actual_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_actual_prefetchit0_window((uint64_t)(uint32_t)seed, 3);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_ACTUAL_P2_FAR:
        train_branch_actual_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        branch_actual_prefetchit0_window((uint64_t)(uint32_t)seed, 0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_ACTUAL_REPEAT:
        train_branch_actual_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        branch_actual_prefetchit0_window((uint64_t)(uint32_t)seed, 3);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_P2_FAR:
        train_branch_farpath_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_to_farpath_prefetchit0_window((uint64_t)(uint32_t)seed, 0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_FAR_P2_FAR:
        train_branch_farpath_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_to_farpath_prefetchit0_window((uint64_t)(uint32_t)seed, 1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCH_FARPATH_REPEAT:
        train_branch_farpath_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        branch_to_farpath_prefetchit0_window((uint64_t)(uint32_t)seed, 3);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BRANCH_FARPATH_P2_FAR:
        train_branch_farpath_prefetchit0_window();
        prepare_slow_branch_true_condition();
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        branch_to_farpath_prefetchit0_window((uint64_t)(uint32_t)seed, 0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_LINES:
        PREFETCHT0_TARGETS();
        call_forced_prefetch_func(farcall_prefetchit0_lines, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_PATH_LINES:
        PREFETCHT0_TARGETS();
        PREFETCHT0_CALL_PATH_LINES();
        call_forced_prefetch_func(farcall_prefetchit0_path_lines, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_REPEAT_LINES:
        PREFETCHT0_TARGETS();
        call_forced_prefetch_func(farcall_prefetchit0_lines_repeat, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_PATH_REPEAT_LINES:
        PREFETCHT0_TARGETS();
        PREFETCHT0_CALL_PATH_LINES();
        call_forced_prefetch_func(farcall_prefetchit0_path_lines_repeat, 4096);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_BRANCH_CALL_LINES:
        PREFETCHT0_TARGETS();
        serialize_cpuid();
        trained_branch_call_prefetchit0_path_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_INDIRECT_CALL_LINES:
        PREFETCHT0_TARGETS();
        serialize_cpuid();
        trained_indirect_call_prefetchit0_path_lines();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_AFTER_LINES:
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_CPUID_AFTER_LINES:
        serialize_cpuid();
        PREFETCHI_T0_TIMED_PATH_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_SMALL:
        prepare_cold_call_target(farcall_frontend_stall_small, 2048);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        farcall_frontend_stall_small();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_HUGE:
        prepare_cold_call_target(farcall_frontend_stall_huge, 32768);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        farcall_frontend_stall_huge();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_CPUID_AFTER:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        serialize_cpuid();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_TIMED_PATH_LINES();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_SHAPE_AFTER_FAR_COLDLINE:
        flush_code_range((const void *)far_pressure_c, 256);
        asm volatile("mfence\n\tlfence" ::: "memory");
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        nofetch_target_lines_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_AFTER_FAR_COLDLINE:
        flush_code_range((const void *)far_pressure_c, 256);
        asm volatile("mfence\n\tlfence" ::: "memory");
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        PREFETCHI_T0_TARGET_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_AFTER_FAR_COLDLINE_SPACED32:
        flush_code_range((const void *)far_pressure_c, 256);
        asm volatile("mfence\n\tlfence" ::: "memory");
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        prefetchi_target_lines_t0_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_AFTER_FAR_COLDLINE_SPACED32:
        flush_code_range((const void *)far_pressure_c, 256);
        asm volatile("mfence\n\tlfence" ::: "memory");
        serialize_cpuid();
        g_sink = far_pressure_c(seed);
        prefetchi_target_lines_t1_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_COLDLINE:
        flush_code_range((const void *)far_pressure_c, 256);
        asm volatile("mfence\n\tlfence" ::: "memory");
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_FAR_COLDLINE_SPACED32:
        flush_code_range((const void *)far_pressure_c, 256);
        asm volatile("mfence\n\tlfence" ::: "memory");
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(32);
        g_sink = far_pressure_c(seed);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BETWEEN_COLD_CALLS:
        prepare_cold_call_target(farcall_frontend_stall_small, 2048);
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        farcall_frontend_stall_small();
        PREFETCHI_T0_TARGET_LINES();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_BRANCH_MISP_FAR:
        train_branch_to_frontend_stall_not_taken();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        trained_branch_to_frontend_stall_once(1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BEFORE_INDIRECT_MISP_FAR: {
        train_indirect_frontend_stall_to_tiny();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        g_void_call_target = farcall_frontend_stall_big;
        asm volatile("" ::: "memory");
        VoidFn fn = g_void_call_target;
        fn();
        break;
    }
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT16_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t0_repeat16();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT64_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t0_repeat64();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_REPEAT16_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t1_repeat16();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT16_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        prefetchi_target_lines_t0_repeat16();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_REPEAT64_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        prefetchi_target_lines_t0_repeat64();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_SLOW_BRANCH:
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit0_lines_once();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CPUID_AFTER:
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit0_lines_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_FAR_AFTER:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit0_lines_once();
        farcall_frontend_stall_big();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_WRONGPATH_SLOW_BRANCH:
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit0_path_lines_once();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_WRONGPATH_SLOW_BRANCH:
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit1_lines_once();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_SLOW_BRANCH:
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_lines_once();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_CPUID_AFTER:
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_lines_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DATA_FAR_AFTER:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_lines_once();
        farcall_frontend_stall_big();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_WRONGPATH_DATA_SLOW_BRANCH:
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_path_lines_once();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED8_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(8);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED32_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED128_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(128);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_SPACED32_CPUID_AFTER:
        serialize_cpuid();
        prefetchi_target_lines_t1_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_ARITH_GAP16:
        serialize_cpuid();
        prefetchi_target_lines_t0_arith_gap(16);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_ARITH_GAP64:
        serialize_cpuid();
        prefetchi_target_lines_t0_arith_gap(64);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CONTROL_GAP16:
        serialize_cpuid();
        prefetchi_target_lines_t0_control_gap(16);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CONTROL_GAP64:
        serialize_cpuid();
        prefetchi_target_lines_t0_control_gap(64);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_ARITH_GAP64:
        serialize_cpuid();
        prefetchi_target_lines_t1_arith_gap(64);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TWOPHASE:
        serialize_cpuid();
        PREFETCHI_T0_TARGETS();
        PREFETCH_PAUSE_GAP(512);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TWOPHASE_LONGGAP:
        serialize_cpuid();
        PREFETCHI_T0_TARGETS();
        PREFETCH_PAUSE_GAP(2048);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(128);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TWOPHASE:
        serialize_cpuid();
        PREFETCHI_T1_TARGETS();
        PREFETCH_PAUSE_GAP(512);
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_UNROLLED_SPACED32_CPUID_AFTER:
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_UNROLLED_SPACED128_CPUID_AFTER:
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(128);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_UNROLLED_SPACED32_CPUID_AFTER:
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_SHAPE_FAR_SPACED128:
        call_forced_prefetch_func(farcall_lines_spaced128_shape, 8192);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_SPACED32:
        call_forced_prefetch_func(farcall_prefetchit0_lines_spaced32, 8192);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_SPACED128:
        call_forced_prefetch_func(farcall_prefetchit0_lines_spaced128, 8192);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_SPACED32:
        call_forced_prefetch_func(farcall_prefetchit1_lines_spaced32, 8192);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SPACED32_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(32);
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_SPACED32_CPUID_AFTER:
        PREFETCHT0_TARGETS();
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_DTLB_PRIME_SPACED32_CPUID_AFTER:
        PREFETCHT0_TARGETS();
        serialize_cpuid();
        prefetchi_target_lines_t1_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DTLB_PRIME_SPACED32_BEFORE_FAR_BIG:
        PREFETCHT0_TARGETS();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(32);
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_DEEP_REPEAT4_CPUID_AFTER:
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_deep_branch_wrongpath_prefetchit0_repeat4_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_PER_PAGE_CPUID_AFTER:
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_bar_once();
        prepare_slow_branch_false_condition();
        data_slow_branch_wrongpath_prefetchit0_foo_once();
        prepare_slow_branch_false_condition();
        data_slow_branch_wrongpath_prefetchit0_baz_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE256:
        prepare_chase_branch_false_condition(256);
        serialize_cpuid();
        chase_branch_wrongpath_prefetchit0_lines_once(256);
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE1024:
        prepare_chase_branch_false_condition(1024);
        serialize_cpuid();
        chase_branch_wrongpath_prefetchit0_lines_once(1024);
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_WRONGPATH_CHASE256_CPUID_AFTER:
        prepare_chase_branch_false_condition(256);
        serialize_cpuid();
        chase_branch_wrongpath_prefetchit0_lines_once(256);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_WRONGPATH_CHASE256_CPUID_AFTER:
        prepare_chase_branch_false_condition(256);
        serialize_cpuid();
        chase_branch_wrongpath_prefetchit1_lines_once(256);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE4096_BURST4:
        prepare_chase_branch_false_condition(4096);
        serialize_cpuid();
        inline_chase_branch_prefetchit0_burst4_once(4096);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE16384_BURST4:
        prepare_chase_branch_false_condition(16384);
        serialize_cpuid();
        inline_chase_branch_prefetchit0_burst4_once(16384);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE4096_FIXED_BURST4:
        prepare_chase_branch_false_condition(4096);
        serialize_cpuid();
        inline_chase_branch_prefetchit0_fixed_burst4_once(4096);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_INLINE_CHASE16384_FIXED_BURST4:
        prepare_chase_branch_false_condition(16384);
        serialize_cpuid();
        inline_chase_branch_prefetchit0_fixed_burst4_once(16384);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_INLINE_CHASE4096_BURST4:
        train_inline_chase_branch_prefetchit0_burst4();
        flush_target_code();
        prepare_chase_branch_false_condition(4096);
        serialize_cpuid();
        inline_chase_branch_prefetchit0_burst4_once(4096);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_INLINE_CHASE4096_FIXED_BURST4:
        train_inline_chase_branch_prefetchit0_fixed_burst4();
        flush_target_code();
        prepare_chase_branch_false_condition(4096);
        serialize_cpuid();
        inline_chase_branch_prefetchit0_fixed_burst4_once(4096);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_BRANCH:
        prepare_slow_branch_true_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_lines_once();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_CPUID_AFTER:
        prepare_slow_branch_true_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_lines_once();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PATH_SLOW_TAKEN_BRANCH:
        prepare_slow_branch_true_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_path_lines_once();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_SLOW_TAKEN_PER_PAGE:
        prepare_slow_branch_true_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_bar_once();
        prepare_slow_branch_true_condition();
        data_slow_branch_wrongpath_prefetchit0_foo_once();
        prepare_slow_branch_true_condition();
        data_slow_branch_wrongpath_prefetchit0_baz_once();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TRAINED_WRONGPATH_FLUSH:
        train_wrongpath_branch_taken_t0_lines();
        flush_target_code();
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit0_lines_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TRAINED_WRONGPATH_FLUSH:
        train_wrongpath_branch_taken_t1_lines();
        flush_target_code();
        flush_branch_gate_zero();
        serialize_cpuid();
        slow_branch_wrongpath_prefetchit1_lines_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DATA_TRAINED_WRONGPATH_FLUSH:
        train_data_wrongpath_taken_t0_lines();
        flush_target_code();
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit0_lines_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_DATA_TRAINED_WRONGPATH_FLUSH:
        train_data_wrongpath_taken_t1_lines();
        flush_target_code();
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_slow_branch_wrongpath_prefetchit1_lines_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DEEP_TRAINED_WRONGPATH_FLUSH:
        train_data_deep_wrongpath_taken_t0_repeat4();
        flush_target_code();
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_deep_branch_wrongpath_prefetchit0_repeat4_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_DEEP_SPACED32_TRAINED_WRONGPATH_FLUSH:
        train_data_deep_wrongpath_taken_t0_spaced32();
        flush_target_code();
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_deep_branch_wrongpath_prefetchit0_spaced32_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_DEEP_SPACED32_TRAINED_WRONGPATH_FLUSH:
        train_data_deep_wrongpath_taken_t1_spaced32();
        flush_target_code();
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        data_deep_branch_wrongpath_prefetchit1_spaced32_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PTR_WRONGPATH_DUMMYTRAIN_SPACED32:
        train_ptr_deep_wrongpath_dummy_t0_spaced32();
        flush_target_code();
        shootdown_target_code_tlb();
        set_prefetch_ptrs_to_targets();
        prepare_slow_branch_false_condition();
        serialize_cpuid();
        ptr_deep_branch_wrongpath_prefetchit0_spaced32_once();
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_PTR_WRONGPATH_DUMMYTRAIN_PER_PAGE:
        issue_ptr_one_deep_wrongpath_target_t0_spaced32((const void *)bar);
        issue_ptr_one_deep_wrongpath_target_t0_spaced32((const void *)foo);
        issue_ptr_one_deep_wrongpath_target_t0_spaced32((const void *)baz);
        serialize_cpuid();
        g_branch_gate = 1;
        break;
    case STRATEGY_FAIR_CODE_TLB_OFFSET_PRIME_ONLY:
        PREFETCHT0_TARGET_PAGE_TAILS();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_PRIME_LINES:
        PREFETCHT0_TARGET_PAGE_TAILS();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_PRIME_SPACED32:
        PREFETCHT0_TARGET_PAGE_TAILS();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_PRIME_LINES:
        PREFETCHT1_TARGET_PAGE_TAILS();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_PRIME_SPACED32:
        PREFETCHT1_TARGET_PAGE_TAILS();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BURST4_SPACED32:
        serialize_cpuid();
        prefetchi_target_lines_t0_burst4_spaced32();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BURST8_SPACED32:
        serialize_cpuid();
        prefetchi_target_lines_t0_burst8_spaced32();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BURST4_SPACED128:
        serialize_cpuid();
        prefetchi_target_lines_t0_burst4_spaced128();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_BURST4_SPACED32:
        serialize_cpuid();
        prefetchi_target_lines_t1_burst4_spaced32();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH:
        serialize_cpuid();
        PREFETCHI_T0_FIXED_TIMED_PATH_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_SPACED32:
        serialize_cpuid();
        PREFETCHI_T0_FIXED_TIMED_PATH_LINES_SPACED(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_BURST4:
        serialize_cpuid();
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();
        PREFETCHI_T0_BURST4_SPACED32();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_BEFORE_FAR_BIG:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_FIXED_TIMED_PATH_LINES_SPACED(32);
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_PATH_TLB_OFFSET_FAR_BURST4:
        PREFETCHT0_TARGET_PAGE_TAILS();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        serialize_cpuid();
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();
        PREFETCHI_T0_BURST4_SPACED32();
        farcall_frontend_stall_big();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB2:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P4_FAR_TLB2:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_BURST4_SPACED32();
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB4:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_quad();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P2_FAR_TLB2:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_FIXED_TIMED_PATH_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P4_FAR_TLB4:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();
        PREFETCHI_T0_BURST4_SPACED32();
        call_far_tlb_miss_quad();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P_FAR_P_FAR:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        farcall_tlb_miss_a();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        farcall_tlb_miss_b();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_P2_FAR:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        farcall_tlb_miss_a();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        farcall_tlb_miss_b();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR2_P2:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_FAR_TLB2_CPUID_AFTER:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_P2_FAR_TLB2:
        prepare_far_tlb_miss_calls();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_TLB2:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_TLB4:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_quad();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_P2_STRONG_FAR:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_P2_STRONG_FAR_REPEAT:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_quad();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_P2_STRONG_FAR_TLB4:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_quad();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_P2_STRONG_FAR_TLB4:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_quad();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_P2_CPUID_FAR:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_P2_FAR_CPUID:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_CPUID_P2_FAR:
        prepare_far_tlb_miss_calls_strong();
        call_far_tlb_miss_pair();
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CPUID_FAR_P2_FAR_CPUID:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_P2_CPUID_FAR:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        serialize_cpuid();
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_P2_FAR_CPUID:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_CPUID_P2_FAR:
        prepare_far_tlb_miss_calls_strong();
        call_far_tlb_miss_pair();
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CPUID_FAR_P2_FAR_CPUID:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        PREFETCHI_T1_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_AB_P2_FAR_CD:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_AB_P4_FAR_CD:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T0_BURST4_SPACED32();
        call_far_tlb_miss_pair_cd();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FIXED_FAR_AB_P2_FAR_CD:
        prepare_far_tlb_miss_calls_strong();
        serialize_cpuid();
        call_far_tlb_miss_pair();
        PREFETCHI_T0_FIXED_CALL_PATH_LINES();
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        PREFETCHI_T0_TARGET_LINES_SPACED(32);
        call_far_tlb_miss_pair_cd();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_STRONG_FARFUNC_BURST4_FAR_TLB2:
        prepare_far_tlb_miss_calls_strong();
        call_forced_prefetch_func_strong(farcall_prefetchit0_burst4_spaced32, 32768);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_STRONG_FARFUNC_PATH_FAR_TLB2:
        prepare_far_tlb_miss_calls_strong();
        call_forced_prefetch_func_strong(farcall_prefetchit0_path_lines_repeat, 32768);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_STRONG_FARFUNC_BURST4_FAR_TLB2:
        prepare_far_tlb_miss_calls_strong();
        call_forced_prefetch_func_strong(farcall_prefetchit1_burst4_spaced32, 32768);
        call_far_tlb_miss_pair();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST4_SPACED32:
        call_forced_prefetch_func(farcall_prefetchit0_burst4_spaced32, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST8_SPACED32:
        call_forced_prefetch_func(farcall_prefetchit0_burst8_spaced32, 65536);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_FAR_BURST4_SPACED128:
        call_forced_prefetch_func(farcall_prefetchit0_burst4_spaced128, 65536);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_FAR_BURST4_SPACED32:
        call_forced_prefetch_func(farcall_prefetchit1_burst4_spaced32, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_FAR_BURST4_SPACED32:
        PREFETCHT0_TARGET_PAGE_TAILS();
        call_forced_prefetch_func(farcall_prefetchit0_burst4_spaced32, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_FAR_BURST8_SPACED32:
        PREFETCHT0_TARGET_PAGE_TAILS();
        call_forced_prefetch_func(farcall_prefetchit0_burst8_spaced32, 65536);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_FAR_BURST4_SPACED32:
        PREFETCHT1_TARGET_PAGE_TAILS();
        call_forced_prefetch_func(farcall_prefetchit1_burst4_spaced32, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_PRE10:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit0_pre10, 16384);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_POST10:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit0_post10, 16384);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_BURST4_PRE10:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit0_burst4_pre10, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CALL_WINDOW_BURST4_POST10:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit0_burst4_post10, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CALL_WINDOW_BURST4_PRE10:
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit1_burst4_pre10, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_CALL_WINDOW_BURST4_PRE10:
        PREFETCHT0_TARGET_PAGE_TAILS();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit0_burst4_pre10, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_TLB_OFFSET_CALL_WINDOW_BURST4_POST10:
        PREFETCHT0_TARGET_PAGE_TAILS();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit0_burst4_post10, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_TLB_OFFSET_CALL_WINDOW_BURST4_PRE10:
        PREFETCHT1_TARGET_PAGE_TAILS();
        prepare_cold_call_target(farcall_frontend_stall_big, 8192);
        call_forced_prefetch_func(call_window_prefetchit1_burst4_pre10, 32768);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O0:
        run_branchwin_target_t0(branchwin_target_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O1:
        run_branchwin_target_t0(branchwin_target_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O2:
        run_branchwin_target_t0(branchwin_target_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O4:
        run_branchwin_target_t0(branchwin_target_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O8:
        run_branchwin_target_t0(branchwin_target_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_O16:
        run_branchwin_target_t0(branchwin_target_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O0:
        run_branchwin_wrong_t0(branchwin_wrong_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O1:
        run_branchwin_wrong_t0(branchwin_wrong_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O2:
        run_branchwin_wrong_t0(branchwin_wrong_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O4:
        run_branchwin_wrong_t0(branchwin_wrong_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O8:
        run_branchwin_wrong_t0(branchwin_wrong_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_O16:
        run_branchwin_wrong_t0(branchwin_wrong_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O0:
        run_branchwin_before_t0(branchwin_before_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O1:
        run_branchwin_before_t0(branchwin_before_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O2:
        run_branchwin_before_t0(branchwin_before_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O4:
        run_branchwin_before_t0(branchwin_before_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O8:
        run_branchwin_before_t0(branchwin_before_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_BEFORE_O16:
        run_branchwin_before_t0(branchwin_before_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O0:
        run_branchwin_target_t0(branchwin_target_head_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O1:
        run_branchwin_target_t0(branchwin_target_head_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O2:
        run_branchwin_target_t0(branchwin_target_head_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O4:
        run_branchwin_target_t0(branchwin_target_head_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O8:
        run_branchwin_target_t0(branchwin_target_head_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_TARGET_HEAD_O16:
        run_branchwin_target_t0(branchwin_target_head_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O0:
        run_branchwin_wrong_t0(branchwin_wrong_head_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O1:
        run_branchwin_wrong_t0(branchwin_wrong_head_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O2:
        run_branchwin_wrong_t0(branchwin_wrong_head_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O4:
        run_branchwin_wrong_t0(branchwin_wrong_head_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O8:
        run_branchwin_wrong_t0(branchwin_wrong_head_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_WRONG_HEAD_O16:
        run_branchwin_wrong_t0(branchwin_wrong_head_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O0:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O1:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O2:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O4:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O8:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_O16:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O0:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O1:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O2:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O4:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O8:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_O16:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O0:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_head_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O1:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_head_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O2:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_head_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O4:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_head_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O8:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_head_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLWRONG_HEAD_O16:
        run_branchwin_fallwrong_t0(branchwin_fallwrong_head_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O0:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_head_t0_o0);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O1:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_head_t0_o1);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O2:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_head_t0_o2);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O4:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_head_t0_o4);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O8:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_head_t0_o8);
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_BRANCHWIN_FALLCORRECT_HEAD_O16:
        run_branchwin_fallcorrect_t0(branchwin_fallcorrect_head_t0_o16);
        break;
    case STRATEGY_FAIR_CODE_PAGE_PRIME_ONLY:
        serialize_cpuid();
        call_target_page_probes(seed);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_SHAPE_LINES:
        serialize_cpuid();
        call_target_page_shapes();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_SHAPE_SPACED32_LINES:
        serialize_cpuid();
        call_target_page_shape_spaced32_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_LINES:
        serialize_cpuid();
        call_target_page_prefetchit0_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_SPACED32_LINES:
        serialize_cpuid();
        call_target_page_prefetchit0_spaced32_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_SPACED128_LINES:
        serialize_cpuid();
        call_target_page_prefetchit0_spaced128_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT0_REPEAT4_LINES:
        serialize_cpuid();
        call_target_page_prefetchit0_repeat4_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT1_LINES:
        serialize_cpuid();
        call_target_page_prefetchit1_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PAGE_PREFETCHIT1_SPACED32_LINES:
        serialize_cpuid();
        call_target_page_prefetchit1_spaced32_lines();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_ADJACENT_SHAPE_SPACED32_LINES:
        call_forced_prefetch_func(adjacent_target_shape_spaced32_lines, 8192);
        break;
    case STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT0_SPACED32_LINES:
        call_forced_prefetch_func(adjacent_target_prefetchit0_spaced32_lines, 8192);
        break;
    case STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT0_SPACED128_LINES:
        call_forced_prefetch_func(adjacent_target_prefetchit0_spaced128_lines, 16384);
        break;
    case STRATEGY_FAIR_CODE_ADJACENT_PREFETCHIT1_SPACED32_LINES:
        call_forced_prefetch_func(adjacent_target_prefetchit1_spaced32_lines, 8192);
        break;
    case STRATEGY_FAIR_CODE_TLB_PRIME_SPACED32_SHAPE:
        call_target_page_probes(seed);
        serialize_cpuid();
        nofetch_target_lines_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_LINES:
        call_target_page_probes(seed);
        serialize_cpuid();
        PREFETCHI_T0_TARGET_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED8:
        call_target_page_probes(seed);
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(8);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED32:
        call_target_page_probes(seed);
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED64:
        call_target_page_probes(seed);
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(64);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT0_CODE_TLB_PRIME_SPACED128:
        call_target_page_probes(seed);
        serialize_cpuid();
        prefetchi_target_lines_t0_spaced(128);
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CODE_TLB_PRIME_LINES:
        call_target_page_probes(seed);
        serialize_cpuid();
        PREFETCHI_T1_TARGET_LINES();
        serialize_cpuid();
        break;
    case STRATEGY_FAIR_CODE_PREFETCHIT1_CODE_TLB_PRIME_SPACED32:
        call_target_page_probes(seed);
        serialize_cpuid();
        prefetchi_target_lines_t1_spaced(32);
        serialize_cpuid();
        break;
    case STRATEGY_COUNT:
        break;
    default:
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

static void shootdown_target_code_tlb(void) {
    shootdown_code_page_tlb_strong((void (*)(void))bar);
    shootdown_code_page_tlb_strong((void (*)(void))foo);
    shootdown_code_page_tlb_strong((void (*)(void))baz);
}

static void flush_call_path_code(void) {
    flush_code_range((const void *)call_targets_indirect, 512);
    flush_code_range((const void *)call_targets_fixed, 512);
    flush_code_range((const void *)call_one_target_indirect, 512);
}

static int call_measured_targets(int seed) {
    if (g_measure_bar_only) {
        return bar(seed);
    }
    if (g_measure_fixed_targets) {
        return call_targets_fixed(seed);
    }
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

static Summary compute_summary(uint64_t *values, int count) {
    Summary s;
    memset(&s, 0, sizeof(s));
    if (!values || count <= 0) {
        return s;
    }
    qsort(values, (size_t)count, sizeof(values[0]), cmp_u64);

    unsigned __int128 sum = 0;
    for (int i = 0; i < count; ++i) {
        sum += values[i];
    }

    s.mean = (double)sum / (double)count;
    s.min = values[0];
    s.p05 = percentile(values, count, 5);
    s.p25 = percentile(values, count, 25);
    s.p50 = percentile(values, count, 50);
    s.p75 = percentile(values, count, 75);
    s.p95 = percentile(values, count, 95);
    s.p99 = percentile(values, count, 99);
    s.max = values[count - 1];
    return s;
}

static Stats compute_stats(Stats s, int count) {
    s.count = count;
    s.latency = compute_summary(s.cycles, count);
    if (g_collect_perf_each_iter) {
        s.itlb_stlb_hit_summary = compute_summary(s.itlb_stlb_hit, count);
        s.itlb_walk_summary = compute_summary(s.itlb_walk, count);
        s.itlb_miss_est_summary = compute_summary(s.itlb_miss_est, count);
        s.l2_code_miss_summary = compute_summary(s.l2_code_miss, count);
        s.llc = compute_summary(s.llc_miss, count);
    }
    if (g_collect_prepare_perf) {
        s.prep_itlb_walk_summary = compute_summary(s.prep_itlb_walk, count);
        s.prep_dtlb_walk_summary = compute_summary(s.prep_dtlb_walk, count);
        s.prep_branch_miss_summary = compute_summary(s.prep_branch_miss, count);
    }
    return s;
}

static void prepare_measurement(StrategyKind strategy, DelayKind delay, int seed) {
    evict_icache();
    if (g_flush_targets_each_iter) {
        flush_target_code();
    }
    if (g_shootdown_targets_each_iter) {
        shootdown_target_code_tlb();
    }
    if (g_flush_call_path_each_iter) {
        flush_call_path_code();
    }
    asm volatile("mfence\n\tlfence" ::: "memory");

    run_strategy(strategy, seed);
    run_delay(delay, seed);
}

static uint64_t measure_region_counter(int fd, StrategyKind strategy, DelayKind delay, int seed) {
    if (fd < 0) {
        return 0;
    }
    prepare_measurement(strategy, delay, seed);
    if (g_measure_serial_entry) {
        serialize_cpuid();
    }
    perf_counter_reset_enable(fd);
    (void)call_measured_targets(seed);
    perf_counter_disable(fd);
    return perf_counter_read_value(fd);
}

static Stats run_one_case(StrategyKind strategy, DelayKind delay, int iterations) {
    Stats stats;
    memset(&stats, 0, sizeof(stats));
    stats.cycles = calloc((size_t)iterations, sizeof(stats.cycles[0]));
    if (!stats.cycles) {
        fprintf(stderr, "calloc failed\n");
        exit(1);
    }
    if (g_collect_perf_each_iter) {
        stats.itlb_stlb_hit = calloc((size_t)iterations, sizeof(stats.itlb_stlb_hit[0]));
        stats.itlb_walk = calloc((size_t)iterations, sizeof(stats.itlb_walk[0]));
        stats.itlb_miss_est = calloc((size_t)iterations, sizeof(stats.itlb_miss_est[0]));
        stats.l2_code_miss = calloc((size_t)iterations, sizeof(stats.l2_code_miss[0]));
        stats.llc_miss = calloc((size_t)iterations, sizeof(stats.llc_miss[0]));
        if (!stats.itlb_stlb_hit || !stats.itlb_walk || !stats.itlb_miss_est ||
            !stats.l2_code_miss || !stats.llc_miss) {
            fprintf(stderr, "calloc failed\n");
            exit(1);
        }
    }
    if (g_collect_prepare_perf) {
        stats.prep_itlb_walk = calloc((size_t)iterations, sizeof(stats.prep_itlb_walk[0]));
        stats.prep_dtlb_walk = calloc((size_t)iterations, sizeof(stats.prep_dtlb_walk[0]));
        stats.prep_branch_miss = calloc((size_t)iterations, sizeof(stats.prep_branch_miss[0]));
        if (!stats.prep_itlb_walk || !stats.prep_dtlb_walk || !stats.prep_branch_miss) {
            fprintf(stderr, "calloc failed\n");
            exit(1);
        }
    }

    for (int i = 0; i < iterations; ++i) {
        g_state = xorshift64(g_state + (uint64_t)i + 1u);
        int seed = (int)g_state;

        prepare_measurement(strategy, delay, seed);
        if (g_measure_serial_entry) {
            serialize_cpuid();
        }
        uint64_t t0 = rdtsc_begin();
        (void)call_measured_targets(seed);
        uint64_t t1 = rdtsc_end();
        stats.cycles[i] = t1 - t0;

        if (g_collect_perf_each_iter && g_perf_group.leader >= 0) {
            stats.itlb_miss_est[i] = measure_region_counter(g_perf_group.itlb_miss, strategy, delay, seed);
            stats.itlb_walk[i] = measure_region_counter(g_perf_group.itlb_walk, strategy, delay, seed);
            stats.l2_code_miss[i] = measure_region_counter(g_perf_group.l2_code_miss, strategy, delay, seed);
            stats.llc_miss[i] = measure_region_counter(g_perf_group.llc_miss, strategy, delay, seed);
        }
    }

    return compute_stats(stats, iterations);
}

static Stats run_one_case_once_process(StrategyKind strategy, DelayKind delay) {
    Stats stats;
    memset(&stats, 0, sizeof(stats));
    stats.cycles = calloc(1, sizeof(stats.cycles[0]));
    if (!stats.cycles) {
        fprintf(stderr, "calloc failed\n");
        exit(1);
    }
    if (g_collect_perf_each_iter) {
        stats.itlb_stlb_hit = calloc(1, sizeof(stats.itlb_stlb_hit[0]));
        stats.itlb_walk = calloc(1, sizeof(stats.itlb_walk[0]));
        stats.itlb_miss_est = calloc(1, sizeof(stats.itlb_miss_est[0]));
        stats.l2_code_miss = calloc(1, sizeof(stats.l2_code_miss[0]));
        stats.llc_miss = calloc(1, sizeof(stats.llc_miss[0]));
        if (!stats.itlb_stlb_hit || !stats.itlb_walk || !stats.itlb_miss_est ||
            !stats.l2_code_miss || !stats.llc_miss) {
            fprintf(stderr, "calloc failed\n");
            exit(1);
        }
    }
    if (g_collect_prepare_perf) {
        stats.prep_itlb_walk = calloc(1, sizeof(stats.prep_itlb_walk[0]));
        stats.prep_dtlb_walk = calloc(1, sizeof(stats.prep_dtlb_walk[0]));
        stats.prep_branch_miss = calloc(1, sizeof(stats.prep_branch_miss[0]));
        if (!stats.prep_itlb_walk || !stats.prep_dtlb_walk || !stats.prep_branch_miss) {
            fprintf(stderr, "calloc failed\n");
            exit(1);
        }
    }

    g_state = xorshift64(g_state + 1u);
    int seed = (int)g_state;

    if (g_collect_prepare_perf && g_perf_group.leader >= 0) {
        perf_counter_reset_enable(g_perf_group.itlb_walk);
        perf_counter_reset_enable(g_perf_group.dtlb_load_walk);
        perf_counter_reset_enable(g_perf_group.branch_miss);
    }
    prepare_measurement(strategy, delay, seed);
    if (g_collect_prepare_perf && g_perf_group.leader >= 0) {
        perf_counter_disable(g_perf_group.branch_miss);
        perf_counter_disable(g_perf_group.dtlb_load_walk);
        perf_counter_disable(g_perf_group.itlb_walk);
        stats.prep_itlb_walk[0] = perf_counter_read_value(g_perf_group.itlb_walk);
        stats.prep_dtlb_walk[0] = perf_counter_read_value(g_perf_group.dtlb_load_walk);
        stats.prep_branch_miss[0] = perf_counter_read_value(g_perf_group.branch_miss);
    }
    if (g_measure_serial_entry) {
        serialize_cpuid();
    }
    if (g_collect_perf_each_iter && g_perf_group.leader >= 0) {
        perf_counter_reset_enable(g_perf_group.itlb_miss);
        perf_counter_reset_enable(g_perf_group.itlb_walk);
        perf_counter_reset_enable(g_perf_group.l2_code_miss);
        perf_counter_reset_enable(g_perf_group.llc_miss);
    }
    uint64_t t0 = rdtsc_begin();
    (void)call_measured_targets(seed);
    uint64_t t1 = rdtsc_end();
    if (g_collect_perf_each_iter && g_perf_group.leader >= 0) {
        perf_counter_disable(g_perf_group.llc_miss);
        perf_counter_disable(g_perf_group.l2_code_miss);
        perf_counter_disable(g_perf_group.itlb_walk);
        perf_counter_disable(g_perf_group.itlb_miss);
    }

    stats.cycles[0] = t1 - t0;
    if (g_collect_perf_each_iter && g_perf_group.leader >= 0) {
        stats.itlb_miss_est[0] = perf_counter_read_value(g_perf_group.itlb_miss);
        stats.itlb_walk[0] = perf_counter_read_value(g_perf_group.itlb_walk);
        stats.l2_code_miss[0] = perf_counter_read_value(g_perf_group.l2_code_miss);
        stats.llc_miss[0] = perf_counter_read_value(g_perf_group.llc_miss);
    }

    return compute_stats(stats, 1);
}

static void print_stats_csv(StrategyKind strategy, DelayKind delay, int iterations,
                            size_t evict_kib, const Stats *s) {
    printf("%s,%s,%d,%zu,%.2f,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu",
           strategy_name(strategy),
           delay_name(delay),
           iterations,
           evict_kib,
           s->latency.mean,
           (unsigned long long)s->latency.min,
           (unsigned long long)s->latency.p05,
           (unsigned long long)s->latency.p25,
           (unsigned long long)s->latency.p50,
           (unsigned long long)s->latency.p75,
           (unsigned long long)s->latency.p95,
           (unsigned long long)s->latency.p99,
           (unsigned long long)s->latency.max);
    if (g_collect_perf_each_iter) {
        printf(",%llu,%llu,%llu,%llu",
               (unsigned long long)s->itlb_miss_est_summary.p50,
               (unsigned long long)s->itlb_walk_summary.p50,
               (unsigned long long)s->l2_code_miss_summary.p50,
               (unsigned long long)s->llc.p50);
    }
    if (g_collect_prepare_perf) {
        printf(",%llu,%llu,%llu",
               (unsigned long long)s->prep_itlb_walk_summary.p50,
               (unsigned long long)s->prep_dtlb_walk_summary.p50,
               (unsigned long long)s->prep_branch_miss_summary.p50);
    }
    putchar('\n');
}

static void free_stats(Stats *s) {
    if (!s) {
        return;
    }
    free(s->cycles);
    free(s->l1i_miss);
    free(s->itlb_miss);
    free(s->itlb_stlb_hit);
    free(s->itlb_walk);
    free(s->itlb_miss_est);
    free(s->prep_itlb_walk);
    free(s->prep_dtlb_walk);
    free(s->prep_branch_miss);
    free(s->l2_code_rd);
    free(s->l2_code_miss);
    free(s->l2_all_miss);
    free(s->llc_load_miss);
    free(s->llc_miss);
    free(s->insn);
    memset(s, 0, sizeof(*s));
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
        if (strstr(cold_mode, "shootdown_targets")) {
            g_shootdown_targets_each_iter = 1;
        }
        if (strstr(cold_mode, "flush_callpath")) {
            g_flush_call_path_each_iter = 1;
        }
        if (strstr(cold_mode, "one_target")) {
            g_measure_one_target = 1;
        }
        if (strstr(cold_mode, "fixed_targets")) {
            g_measure_fixed_targets = 1;
        }
        if (strstr(cold_mode, "bar_only")) {
            g_measure_bar_only = 1;
        }
        if (strstr(cold_mode, "perf")) {
            g_collect_perf_each_iter = 1;
        }
        if (strstr(cold_mode, "prep_perf")) {
            g_collect_prepare_perf = 1;
        }
        if (strstr(cold_mode, "once")) {
            g_measure_once_process = 1;
            iterations = 1;
        }
        if (strstr(cold_mode, "measure_serial")) {
            g_measure_serial_entry = 1;
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
    if (g_collect_perf_each_iter) {
        g_perf_group = perf_group_open(0, -1);
        if (g_perf_group.leader < 0) {
            g_collect_perf_each_iter = 0;
        }
    }

    fprintf(stderr, "INFO: CPU PREFETCHI support: %s\n", has_prefetchi() ? "yes" : "no");
    fprintf(stderr, "INFO: iterations=%d evict_kib=%zu cpu=%d\n", iterations, evict_kib, cpu);
    fprintf(stderr, "INFO: delay_filter=%s strategy_filter=%s\n",
            delay_filter ? delay_filter : "all",
            strategy_filter ? strategy_filter : "all");
    fprintf(stderr, "INFO: cold_mode=%s flush_targets=%d shootdown_targets=%d flush_callpath=%d\n",
            cold_mode ? cold_mode : "evict_only",
            g_flush_targets_each_iter,
            g_shootdown_targets_each_iter,
            g_flush_call_path_each_iter);
    fprintf(stderr, "INFO: measure_one_target=%d\n", g_measure_one_target);
    fprintf(stderr, "INFO: measure_fixed_targets=%d\n", g_measure_fixed_targets);
    fprintf(stderr, "INFO: measure_bar_only=%d\n", g_measure_bar_only);
    fprintf(stderr, "INFO: region_perf=%d\n", g_collect_perf_each_iter);
    fprintf(stderr, "INFO: prepare_perf=%d\n", g_collect_prepare_perf);
    fprintf(stderr, "INFO: once_process=%d\n", g_measure_once_process);
    fprintf(stderr, "INFO: measure_serial=%d\n", g_measure_serial_entry);
    fprintf(stderr, "INFO: targets bar=%p foo=%p baz=%p\n", (void *)bar, (void *)foo, (void *)baz);

    if (g_collect_perf_each_iter) {
        if (g_collect_prepare_perf) {
            puts("strategy,delay,iters,evict_kib,mean,min,p05,p25,p50,p75,p95,p99,max,itlb_miss_p50,stlb_miss_p50,l2_code_miss_p50,llc_miss_p50,prep_itlb_walk_p50,prep_dtlb_walk_p50,prep_branch_miss_p50");
        } else {
            puts("strategy,delay,iters,evict_kib,mean,min,p05,p25,p50,p75,p95,p99,max,itlb_miss_p50,stlb_miss_p50,l2_code_miss_p50,llc_miss_p50");
        }
    } else {
        puts("strategy,delay,iters,evict_kib,mean,min,p05,p25,p50,p75,p95,p99,max");
    }

    for (int d = 0; d < DELAY_COUNT; ++d) {
        if (!matches_filter(delay_name((DelayKind)d), delay_filter)) {
            continue;
        }
        for (int s = 0; s < STRATEGY_COUNT; ++s) {
            if (!matches_filter(strategy_name((StrategyKind)s), strategy_filter)) {
                continue;
            }
            Stats stats = g_measure_once_process
                ? run_one_case_once_process((StrategyKind)s, (DelayKind)d)
                : run_one_case((StrategyKind)s, (DelayKind)d, iterations);
            print_stats_csv((StrategyKind)s, (DelayKind)d, iterations, evict_kib, &stats);
            free_stats(&stats);
        }
    }

    perf_group_close(&g_perf_group);
    if (g_evict_code) {
        munmap(g_evict_code, g_evict_bytes);
    }
    if (g_chase) {
        munmap(g_chase, g_chase_len * sizeof(g_chase[0]));
    }
    return 0;
}
