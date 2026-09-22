// latency.c  (C11/gnu11)
// Build example:
//   gcc -O2 -march=graniterapids -m64 -no-pie -fno-plt -mprefetchi \
//          -DENABLE_PREFETCHI latency.c utils.c -o lat_bench
// Optional:  -DPREFETCHI_HINT=_MM_HINT_IT1
// check prefetch instruction in objdump:
// objdump -d -Mintel ./lat_bench | grep -n 'prefetchit'
// Run example:
//   ./lat_bench [rounds] [qlen]

#define _GNU_SOURCE
#define _DEFAULT_SOURCE 

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <signal.h>
#include <stdlib.h>
#include <pthread.h>
#include <sys/types.h>
#include <unistd.h>
#include "utils.h"
#include "tasks.h"

typedef void (*TaskFn)(void);
static volatile bool g_prefetch_thread_running = true;

// ---------- TSC helpers ----------
static inline uint64_t rdtsc_begin(void) {
    unsigned lo, hi;
    asm volatile("cpuid" ::: "rax","rbx","rcx","rdx","memory");
    asm volatile("rdtsc" : "=a"(lo), "=d"(hi) :: "memory");
    return ((uint64_t)hi << 32) | lo;
}
static inline uint64_t rdtsc_end(void) {
    unsigned lo, hi;
    asm volatile("rdtscp" : "=a"(lo), "=d"(hi) :: "rcx","memory");
    asm volatile("cpuid" ::: "rax","rbx","rcx","rdx","memory");
    return ((uint64_t)hi << 32) | lo;
}

// ---------- CPUID: PREFETCHI ----------
static bool has_prefetchi(void){
    unsigned eax = 7, ebx, ecx = 1, edx;
    __asm__ volatile("cpuid"
                     : "+a"(eax), "=b"(ebx), "+c"(ecx), "=d"(edx)
                     :
                     : "memory");
    return ((edx >> 14) & 1u) != 0;
}



// Task function declarations
TASKS(DECL_TASK)

#if defined(ENABLE_PREFETCHI)
// Prefetch function declarations
TASKS(DECL_PREFETCH_TASK)
#endif

// ---------- PREFETCHI (intrinsic path) ----------
#if defined(ENABLE_PREFETCHI)
#include <x86intrin.h>
#endif  // ENABLE_PREFETCHI

// ---------- NOP window ----------
// static int g_prefetch_pos = PREFETCH_NOPS_WINDOW / 2;

static inline __attribute__((always_inline)) void emit_nops_exact(int n) {
    switch (n) {
        case 0: break;
        EMIT_NOPS_CASE(1)  EMIT_NOPS_CASE(2)  EMIT_NOPS_CASE(3)  EMIT_NOPS_CASE(4)
        EMIT_NOPS_CASE(5)  EMIT_NOPS_CASE(6)  EMIT_NOPS_CASE(7)  EMIT_NOPS_CASE(8)
        EMIT_NOPS_CASE(9)  EMIT_NOPS_CASE(10) EMIT_NOPS_CASE(11) EMIT_NOPS_CASE(12)
        EMIT_NOPS_CASE(13) EMIT_NOPS_CASE(14) EMIT_NOPS_CASE(15) EMIT_NOPS_CASE(16)
        EMIT_NOPS_CASE(17) EMIT_NOPS_CASE(18) EMIT_NOPS_CASE(19) EMIT_NOPS_CASE(20)
        EMIT_NOPS_CASE(21) EMIT_NOPS_CASE(22) EMIT_NOPS_CASE(23) EMIT_NOPS_CASE(24)
        EMIT_NOPS_CASE(25) EMIT_NOPS_CASE(26) EMIT_NOPS_CASE(27) EMIT_NOPS_CASE(28)
        EMIT_NOPS_CASE(29) EMIT_NOPS_CASE(30) EMIT_NOPS_CASE(31) EMIT_NOPS_CASE(32)
        default: break;
    }
}

#if defined(ENABLE_PREFETCHI)
// ---------- prefetch all tasks ----------
__attribute__((noinline))
void prefetch_all_tasks(void) {
    // Prefetch all task functions using RIP-relative addressing
    // This can be used to warm up the instruction cache before benchmarking
    #define PREFETCH_TASK(N) __builtin_ia32_prefetchi(task_##N, 3);
    TASKS(PREFETCH_TASK)
    #undef PREFETCH_TASK
}
#endif

#if defined(ENABLE_PREFETCHI)
// ---------- prefetch all prefetch tasks ----------
__attribute__((noinline))
void prefetch_all_prefetch_tasks(void) {
    // Prefetch all prefetch_task functions to warm up instruction cache
    #define PREFETCH_PREFETCH_TASK(N) __builtin_ia32_prefetchi(prefetch_task_##N, 3);
    TASKS(PREFETCH_PREFETCH_TASK)
    #undef PREFETCH_PREFETCH_TASK
}

// ---------- background prefetch thread ----------
void* prefetch_thread_func(void* arg) {
    // Pin this thread to CPU 64 (hyperthreading pair of CPU 0)
    pin_to_cpu(64);
    
    // Verify which CPU we're actually running on
    // int actual_cpu = sched_getcpu();
    // fprintf(stderr, "INFO: Prefetch thread pinned to CPU %d, actually running on CPU %d\n", 0, actual_cpu);
    
    // uint64_t prefetch_cycles = 0;
    
    // Continuously prefetch all tasks in round-robin fashion
    while (g_prefetch_thread_running) {
        #define PREFETCH_TASK_THREAD(N) __builtin_ia32_prefetchi(task_##N, 3);
        TASKS(PREFETCH_TASK_THREAD)
        #undef PREFETCH_TASK_THREAD
        // prefetch_cycles++;
    }
    
    // fprintf(stderr, "INFO: Prefetch thread completed %llu prefetch cycles\n", 
    //         (unsigned long long)prefetch_cycles);
    
    return NULL;
}
#endif

// ---------- task definitions ----------
#define DEF_TASK(N) DEFINE_TASK(N)
TASKS(DEF_TASK)
#undef DEF_TASK

#if defined(ENABLE_PREFETCHI)
// ---------- prefetch function definitions ----------
#define DEF_PREFETCH_TASK(N) DEFINE_PREFETCH_TASK(N)
TASKS(DEF_PREFETCH_TASK)
#undef DEF_PREFETCH_TASK
#endif


// ---------- task array ----------
#define TASK_ELEM(N) task_##N,
TaskFn const kAllTasks[] = { TASKS(TASK_ELEM) };
#undef TASK_ELEM

#if defined(ENABLE_PREFETCHI)
// ---------- prefetch function array ----------
#define PREFETCH_TASK_ELEM(N) prefetch_task_##N,
TaskFn const kAllPrefetchTasks[] = { TASKS(PREFETCH_TASK_ELEM) };
#undef PREFETCH_TASK_ELEM
#endif

enum { kNumTasks = (int)(sizeof(kAllTasks)/sizeof(kAllTasks[0])) };
static inline void run_tasks(int len) {
    for (int i = 0; i < len; ++i) {
        TaskFn current_task = kAllTasks[i % kNumTasks];
        
        // emit_nops_exact(g_prefetch_pos);
// #if defined(ENABLE_PREFETCHI)
//         TaskFn prefetch_fn = kAllPrefetchTasks[(i + 2) % kNumTasks];
//         prefetch_fn();
// #endif
        // emit_nops_exact(PREFETCH_NOPS_WINDOW - g_prefetch_pos);
        
        current_task();
    }
}


// ---------- main ----------
int main(int argc, char** argv) {
    // Flush instruction cache at startup for consistent measurements
    // flush_instruction_cache();
    
    int cpu = 0;
    int rounds = 100;
    int qlen = 4096;
    int rt_prio = 80;

    if (argc > 1) { int v = atoi(argv[1]); if (v > 0) rounds = v; }
    if (argc > 2) { int v = atoi(argv[2]); if (v > 0) qlen   = v; }
    // if (argc > 3) { int p = atoi(argv[3]); if (p < 0) p = 0; if (p > PREFETCH_NOPS_WINDOW) p = PREFETCH_NOPS_WINDOW; g_prefetch_pos = p; }


    bool cpu_has = has_prefetchi();
    fprintf(stderr, "INFO: CPU PREFETCHI (prefetchit0/1) support: %s\n", cpu_has ? "yes" : "no");

    // signals
    sigset_t set; sigemptyset(&set);
    sigaddset(&set, SIGALRM); sigaddset(&set, SIGCHLD);
    pthread_sigmask(SIG_BLOCK, &set, NULL);

    pin_to_cpu(cpu);
    elevate_realtime(rt_prio);
    lock_and_prefault(8ull * 1024 * 1024);

// #if defined(ENABLE_PREFETCHI)
//     // Create background prefetch thread on CPU 64
//     pthread_t prefetch_thread;
//     if (pthread_create(&prefetch_thread, NULL, prefetch_thread_func, NULL) != 0) {
//         fprintf(stderr, "WARN: Failed to create prefetch thread\n");
//     } else {
//         fprintf(stderr, "INFO: Background prefetch thread started on CPU 64\n");
//     }
// #endif

    // uint64_t fixed_hz = 0;
    // bool freq_locked = (geteuid() == 0) && lock_cpu_freq(cpu, &fixed_hz);
    // if (!freq_locked) {
    //     fprintf(stderr, "WARN: CPU freq lock failed or not root; proceeding without fixed freq.\n");
    // }


#if defined(ENABLE_PREFETCHI)
    // Prefetch all task functions to warm up instruction cache
    prefetch_all_tasks();
    // Prefetch all prefetch_task functions to warm up instruction cache
    // prefetch_all_prefetch_tasks();
    
    // Memory barrier to ensure prefetch operations complete
    // Sleep briefly to allow prefetch instructions to fetch into cache
    // usleep(10); // 10us sleep
#endif

#ifdef PERF_COLLECT
    // --- perf icache metrics setup (simplified) ---
    pid_t main_tid = gettid();
    PerfGroup pg = perf_group_open(main_tid, cpu);
    if (pg.leader >= 0) perf_group_enable(pg.leader);
#endif

    uint64_t tsc_start = rdtsc_begin();
    uint64_t ns_start  = now_ns();
    run_tasks(qlen*rounds);
    uint64_t ns_end    = now_ns();
    uint64_t tsc_end   = rdtsc_end();

#ifdef PERF_COLLECT
    if (pg.leader >= 0) perf_group_disable(pg.leader);
#endif

#ifdef PERF_COLLECT
    uint64_t l1i_miss_val = 0, itlb_miss_val = 0, l2_lines_in_val = 0, l2_miss_val = 0, insn_val = 0;
    perf_group_read(&pg, &l1i_miss_val, &itlb_miss_val, &l2_lines_in_val, &l2_miss_val, &insn_val);
#endif

#ifdef PERF_COLLECT
    // Report: absolute misses, MPKI, and miss rates
    if (pg.l1i_miss >= 0) {
        double mpki = (insn_val ? (double)l1i_miss_val * 1000.0 / (double)insn_val : 0.0);
        
        // Calculate i-cache miss rate: misses / total_accesses
        // Estimate total accesses as instructions (assuming each instruction needs to be fetched)
        double miss_rate = 0.0;
        if (insn_val > 0) {
            miss_rate = (double)l1i_miss_val / (double)insn_val;
        }
        
        printf("L1I-load-misses: %llu  (MPKI=%.3f, Miss-Rate=%.4f%%)\n",
               (unsigned long long)l1i_miss_val, mpki, miss_rate * 100.0);
    } else {
        printf("L1I-load-misses: N/A\n");
    }
    if (pg.itlb_miss >= 0) {
        double mpki = (insn_val ? (double)itlb_miss_val * 1000.0 / (double)insn_val : 0.0);
        
        // Calculate iTLB miss rate similar to i-cache
        double miss_rate = 0.0;
        if (insn_val > 0) {
            miss_rate = (double)itlb_miss_val / (double)insn_val;
        }
        
        printf("iTLB-load-misses: %llu  (MPKI=%.3f, Miss-Rate=%.4f%%)\n",
               (unsigned long long)itlb_miss_val, mpki, miss_rate * 100.0);
    } else {
        printf("iTLB-load-misses: N/A\n");
    }
    if (pg.l2_lines_in >= 0) {
        printf("L2-lines-in.all: %llu \n",
               (unsigned long long)l2_lines_in_val);
    } else {
        printf("L2-lines-in.all: N/A\n");
    }
    if (pg.l2_miss >= 0) {
        double mpki = (insn_val ? (double)l2_miss_val * 1000.0 / (double)insn_val : 0.0);
        double miss_rate = (insn_val > 0) ? (double)l2_miss_val / (double)insn_val : 0.0;
        printf("L2-misses: %llu  (MPKI=%.3f, Miss-Rate=%.4f%%)\n",
               (unsigned long long)l2_miss_val, mpki, miss_rate * 100.0);
    } else {
        printf("L2-misses: N/A\n");
    }
    if (pg.leader >= 0) {
        printf("Instructions: %llu\n", (unsigned long long)insn_val);
    }
#endif

    uint64_t ns  = ns_end - ns_start;
    uint64_t cyc = tsc_end - tsc_start;
    uint64_t ops = (uint64_t)qlen * (uint64_t)rounds;

    printf("Ran %llu tasks (%d funcs RR) in %d rounds on CPU %d\n",
           (unsigned long long)ops, kNumTasks, rounds, cpu);
    printf("Time(roi): %llu ns, TSC: %llu cycles\n",
           (unsigned long long)ns, (unsigned long long)cyc);

    // if (ns) {
    //     double cyc_per_ns   = (double)cyc / (double)ns;
    //     double ns_per_task  = (double)ns  / (double)ops;
    //     printf("Raw Cycles/ns: %.3f  |  ns/task(raw): %.3f\n", cyc_per_ns, ns_per_task);
    // }
    // if (freq_locked && fixed_hz) {
    //     long double fixed_ns = (long double)cyc * 1.0e9L / (long double)fixed_hz;
    //     long double fixed_ns_per_task = fixed_ns / (long double)ops;
    //     printf("Fixed CPU freq: %.3f MHz\n", (double)fixed_hz / 1.0e6);
    //     printf("Time(from fixed freq): %.0Lf ns  |  ns/task(fixed): %.3Lf\n",
    //            fixed_ns, fixed_ns_per_task);
    // }


#if defined(ENABLE_PREFETCHI)
    // Stop background prefetch thread
    g_prefetch_thread_running = false;
#endif

    // Flush instruction cache to clear prefetched instructions
    // flush_icache();

#ifdef PERF_COLLECT
    // perf fd cleanup
    perf_group_close(&pg);
#endif

    return 0;
}
