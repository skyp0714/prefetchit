// prefetchi_test.c
// build:  clang -march=x86-64-v4 -m64 -no-pie -fno-plt -mprefetchi prefetch_test.c utils.c -o prefetch_test
// check: objdump -dr -Mintel prefetch_test
#define _GNU_SOURCE
#include <stdio.h>
#include <x86intrin.h>
#include <sys/types.h>
#include <unistd.h>
#include <sys/mman.h>
#include <string.h>
#include "utils.h"

void* p;

// Place functions in distant sections with 4KB+ spacing
__attribute__((section(".text.bar"), aligned(4096)))
int bar(int a) {
  return a + 1;
}

// 4KB padding between functions
__attribute__((section(".text.padding1")))
static const char padding1[4096] = {0};

__attribute__((section(".text.foo"), aligned(4096)))
int foo(int a) {
  return a + 1;
}

// 4KB padding between functions
__attribute__((section(".text.padding2")))
static const char padding2[4096] = {0};

__attribute__((section(".text.baz"), aligned(4096)))
int baz(int a) {
  return a + 1;
}

static inline void prefetch_by_id(int id) {
    switch (id) {
    case 0: __builtin_ia32_prefetchi(foo, 3); break;
    case 1: __builtin_ia32_prefetchi(bar, 3); break;
    case 2: __builtin_ia32_prefetchi(baz, 3); break;
    default: break;
    }
}

// void t0(void);
// void t1(void);
// void t2(void);

// static void prefetch_t0(void){ __builtin_ia32_prefetchi(t0, 3); }
// static void prefetch_t1(void){ __builtin_ia32_prefetchi(t1, 3); }
// static void prefetch_t2(void){ __builtin_ia32_prefetchi(t2, 3); }

// int (* const kAllTasks[])(int) = { bar, bar+1, bar+2 };

// void run_prefetch() {
//   for (int i = 0; i < 50; ++i) {
//     __builtin_ia32_prefetchi(kAllTasks[i%3], 3);
//   }
// }

int main() {
  // System setup: pin to CPU 10, disable kernel preemption, lock memory
  pin_to_cpu(10);
  elevate_realtime(80);
  lock_and_prefault(8ull * 1024 * 1024);


  // Prefetch distant bar function
  // __builtin_ia32_prefetchi(bar, 3);
  // __builtin_ia32_prefetchi(bar+1, 3);
  // __builtin_ia32_prefetchi(foo, 3);
  // __builtin_ia32_prefetchi(foo+1, 3);
  // __builtin_ia32_prefetchi(baz, 3);
  // __builtin_ia32_prefetchi(baz+1, 3);
  // usleep(1);

  // Setup perf monitoring
  pid_t main_tid = gettid();
  PerfGroup pg = perf_group_open(main_tid, 10);
  if (pg.leader >= 0) {
    perf_group_enable(pg.leader);
  }

  // =================ROI start====================

  // TSC timing measurement for bar(1) - should cause TLB miss without prefetch
  unsigned lo_start, hi_start, lo_end, hi_end;
  asm volatile("cpuid" ::: "rax","rbx","rcx","rdx","memory");
  asm volatile("rdtsc" : "=a"(lo_start), "=d"(hi_start) :: "memory");

  bar(1);
  foo(1);
  baz(1);


  asm volatile("rdtscp" : "=a"(lo_end), "=d"(hi_end) :: "rcx","memory");
  asm volatile("cpuid" ::: "rax","rbx","rcx","rdx","memory");
  uint64_t tsc_start = ((uint64_t)hi_start << 32) | lo_start;
  uint64_t tsc_end = ((uint64_t)hi_end << 32) | lo_end;
  uint64_t bar_cycles = tsc_end - tsc_start;

  // =================ROI end====================

  // Stop perf monitoring and read results
  if (pg.leader >= 0) {
    perf_group_disable(pg.leader);
  }

  uint64_t l1i_miss_val = 0, itlb_miss_val = 0, insn_val = 0;
  perf_group_read(&pg, &l1i_miss_val, &itlb_miss_val, &insn_val);

  // Report results
  if (pg.l1i_miss >= 0) {
    double mpki = (insn_val ? (double)l1i_miss_val * 1000.0 / (double)insn_val : 0.0);
    double miss_rate = (insn_val > 0) ? (double)l1i_miss_val / (double)insn_val : 0.0;
    printf("L1I-load-misses: %llu  (MPKI=%.3f, Miss-Rate=%.4f%%)\n",
           (unsigned long long)l1i_miss_val, mpki, miss_rate * 100.0);
  } else {
    printf("L1I-load-misses: N/A\n");
  }

  if (pg.itlb_miss >= 0) {
    double mpki = (insn_val ? (double)itlb_miss_val * 1000.0 / (double)insn_val : 0.0);
    double miss_rate = (insn_val > 0) ? (double)itlb_miss_val / (double)insn_val : 0.0;
    printf("iTLB-load-misses: %llu  (MPKI=%.3f, Miss-Rate=%.4f%%)\n",
           (unsigned long long)itlb_miss_val, mpki, miss_rate * 100.0);
  } else {
    printf("iTLB-load-misses: N/A\n");
  }

  if (pg.leader >= 0) {
    printf("Instructions: %llu\n", (unsigned long long)insn_val);
  }

  // Report timing
  printf("bar(1) execution time: %llu cycles\n", (unsigned long long)bar_cycles);

  // Cleanup
  perf_group_close(&pg);

  return 0;
}


    // static void* next_target = NULL;
//works
  // __builtin_ia32_prefetchi (p, 3);   //don't work
  // next_target = (void*)bar;
  // __builtin_ia32_prefetchi (next_target, 3);   //don't work