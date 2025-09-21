// prefetchi_test.c
// build: clang -march=graniterapids -m64 -no-pie -fno-plt -mprefetchi prefetch_test.c utils.c -o prefetch_test
// check: objdump -dr -Mintel prefetch_test
#define _GNU_SOURCE
#include <stdio.h>
#include <x86intrin.h>
#include <immintrin.h>
#include <sys/types.h>
#include <unistd.h>
#include <sys/mman.h>
#include <string.h>
#include "utils.h"



static inline void spin_loop_1000_cycles(void) {
    // Spin loop for approximately 1000 cycles using a tight loop
    // Each iteration takes approximately 1 cycle on modern CPUs
    asm volatile(
        "mov $1000, %%eax\n\t"
        "1:\n\t"
        "dec %%eax\n\t"
        "jnz 1b\n\t"
        :
        :
        : "eax", "memory"
    );
}

static inline void nop_delay_256(void) {
    // Insert exactly 256 NOPs for prefetch delay
    asm volatile(
        ".rept 1024\n\t"
        "nop\n\t"
        ".endr"
        ::: "memory"
    );
}

// Dummy functions with actual instructions (no complex control flow)
__attribute__((section(".text.dummy4"), aligned(4096)))
int dummy_4_instructions(int x) {
    x += 42;      // add
    x ^= 0x5A;    // xor
    x *= 3;       // mul
    return x;     // ret
}

__attribute__((section(".text.dummy8"), aligned(4096)))
int dummy_8_instructions(int x) {
    x += 42;      // 1
    x ^= 0x5A;    // 2
    x *= 3;       // 3
    x -= 17;      // 4
    x |= 0x0F;    // 5
    x <<= 2;      // 6
    x &= 0xFF;    // 7
    return x;     // 8
}

__attribute__((section(".text.dummy16"), aligned(4096)))
int dummy_16_instructions(int x) {
    x += 42;      // 1
    x ^= 0x5A;    // 2
    x *= 3;       // 3
    x -= 17;      // 4
    x |= 0x0F;    // 5
    x <<= 2;      // 6
    x &= 0xFF;    // 7
    x += 100;     // 8
    x ^= 0xAA;    // 9
    x *= 5;       // 10
    x -= 33;      // 11
    x |= 0xF0;    // 12
    x >>= 1;      // 13
    x &= 0x7F;    // 14
    x += 7;       // 15
    return x;     // 16
}

__attribute__((section(".text.dummy32"), aligned(4096)))
int dummy_32_instructions(int x) {
    x += 42; x ^= 0x5A; x *= 3; x -= 17;           // 1-4
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;       // 5-8
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;         // 9-12
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;         // 13-16
    x *= 2; x -= 11; x |= 0x08; x <<= 1;           // 17-20
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;        // 21-24
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;        // 25-28
    x += 13; x ^= 0x77; x *= 4; return x;          // 29-32
}

__attribute__((section(".text.dummy64"), aligned(4096)))
int dummy_64_instructions(int x) {
    // Block 1 (1-16)
    x += 42; x ^= 0x5A; x *= 3; x -= 17;
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;

    // Block 2 (17-32)
    x *= 2; x -= 11; x |= 0x08; x <<= 1;
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;
    x += 13; x ^= 0x77; x *= 4; x -= 44;

    // Block 3 (33-48)
    x |= 0x02; x <<= 3; x &= 0x7FF; x += 88;
    x ^= 0xBB; x *= 6; x -= 66; x |= 0x01;
    x >>= 3; x &= 0x1F; x += 25; x ^= 0xCC;
    x *= 8; x -= 99; x |= 0x80; x <<= 1;

    // Block 4 (49-64)
    x &= 0x3FF; x += 77; x ^= 0xDD; x *= 9;
    x -= 111; x |= 0x40; x >>= 4; x &= 0x0F;
    x += 39; x ^= 0xEE; x *= 11; x -= 123;
    x |= 0x20; x <<= 2; x &= 0xFF; return x;
}

__attribute__((section(".text.dummy128"), aligned(4096)))
int dummy_128_instructions(int x) {
    // Blocks 1-4 (1-64) - same as dummy_64_instructions
    x += 42; x ^= 0x5A; x *= 3; x -= 17;
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;
    x *= 2; x -= 11; x |= 0x08; x <<= 1;
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;
    x += 13; x ^= 0x77; x *= 4; x -= 44;
    x |= 0x02; x <<= 3; x &= 0x7FF; x += 88;
    x ^= 0xBB; x *= 6; x -= 66; x |= 0x01;
    x >>= 3; x &= 0x1F; x += 25; x ^= 0xCC;
    x *= 8; x -= 99; x |= 0x80; x <<= 1;
    x &= 0x3FF; x += 77; x ^= 0xDD; x *= 9;
    x -= 111; x |= 0x40; x >>= 4; x &= 0x0F;
    x += 39; x ^= 0xEE; x *= 11; x -= 123;
    x |= 0x20; x <<= 2; x &= 0xFF; x += 200;

    // Blocks 5-8 (65-128)
    x ^= 0x11; x *= 12; x -= 200; x |= 0x10;
    x <<= 1; x &= 0x7FF; x += 150; x ^= 0x22;
    x *= 13; x -= 175; x |= 0x08; x >>= 1;
    x &= 0x3FF; x += 125; x ^= 0x44; x *= 14;
    x -= 225; x |= 0x04; x <<= 2; x &= 0x1FF;
    x += 175; x ^= 0x88; x *= 15; x -= 250;
    x |= 0x02; x >>= 2; x &= 0xFF; x += 225;
    x ^= 0x55; x *= 16; x -= 300; x |= 0x01;
    x <<= 3; x &= 0x7FF; x += 275; x ^= 0x66;
    x *= 17; x -= 350; x |= 0x80; x >>= 3;
    x &= 0x3FF; x += 325; x ^= 0x99; x *= 18;
    x -= 400; x |= 0x40; x <<= 1; x &= 0x1FF;
    x += 375; x ^= 0xAA; x *= 19; x -= 450;
    x |= 0x20; x >>= 1; x &= 0xFF; x += 425;
    x ^= 0xBB; x *= 20; x -= 500; x |= 0x10;
    x <<= 2; x &= 0x7FF; x += 475; return x;
}

__attribute__((section(".text.dummy256"), aligned(4096)))
int dummy_256_instructions(int x) {
    // First 128 instructions (same as dummy_128_instructions)
    x += 42; x ^= 0x5A; x *= 3; x -= 17;
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;
    x *= 2; x -= 11; x |= 0x08; x <<= 1;
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;
    x += 13; x ^= 0x77; x *= 4; x -= 44;
    x |= 0x02; x <<= 3; x &= 0x7FF; x += 88;
    x ^= 0xBB; x *= 6; x -= 66; x |= 0x01;
    x >>= 3; x &= 0x1F; x += 25; x ^= 0xCC;
    x *= 8; x -= 99; x |= 0x80; x <<= 1;
    x &= 0x3FF; x += 77; x ^= 0xDD; x *= 9;
    x -= 111; x |= 0x40; x >>= 4; x &= 0x0F;
    x += 39; x ^= 0xEE; x *= 11; x -= 123;
    x |= 0x20; x <<= 2; x &= 0xFF; x += 200;
    x ^= 0x11; x *= 12; x -= 200; x |= 0x10;
    x <<= 1; x &= 0x7FF; x += 150; x ^= 0x22;
    x *= 13; x -= 175; x |= 0x08; x >>= 1;
    x &= 0x3FF; x += 125; x ^= 0x44; x *= 14;
    x -= 225; x |= 0x04; x <<= 2; x &= 0x1FF;
    x += 175; x ^= 0x88; x *= 15; x -= 250;
    x |= 0x02; x >>= 2; x &= 0xFF; x += 225;
    x ^= 0x55; x *= 16; x -= 300; x |= 0x01;
    x <<= 3; x &= 0x7FF; x += 275; x ^= 0x66;
    x *= 17; x -= 350; x |= 0x80; x >>= 3;
    x &= 0x3FF; x += 325; x ^= 0x99; x *= 18;
    x -= 400; x |= 0x40; x <<= 1; x &= 0x1FF;
    x += 375; x ^= 0xAA; x *= 19; x -= 450;
    x |= 0x20; x >>= 1; x &= 0xFF; x += 425;
    x ^= 0xBB; x *= 20; x -= 500; x |= 0x10;
    x <<= 2; x &= 0x7FF; x += 475; x ^= 0xCC;

    // Second 128 instructions (129-256)
    x *= 21; x -= 550; x |= 0x08; x >>= 2;
    x &= 0x3FF; x += 525; x ^= 0xDD; x *= 22;
    x -= 600; x |= 0x04; x <<= 3; x &= 0x1FF;
    x += 575; x ^= 0xEE; x *= 23; x -= 650;
    x |= 0x02; x >>= 3; x &= 0xFF; x += 625;
    x ^= 0x77; x *= 24; x -= 700; x |= 0x01;
    x <<= 1; x &= 0x7FF; x += 675; x ^= 0x88;
    x *= 25; x -= 750; x |= 0x80; x >>= 1;
    x &= 0x3FF; x += 725; x ^= 0x99; x *= 26;
    x -= 800; x |= 0x40; x <<= 2; x &= 0x1FF;
    x += 775; x ^= 0x11; x *= 27; x -= 850;
    x |= 0x20; x >>= 2; x &= 0xFF; x += 825;
    x ^= 0x22; x *= 28; x -= 900; x |= 0x10;
    x <<= 3; x &= 0x7FF; x += 875; x ^= 0x33;
    x *= 29; x -= 950; x |= 0x08; x >>= 3;
    x &= 0x3FF; x += 925; x ^= 0x44; x *= 30;
    x -= 1000; x |= 0x04; x <<= 1; x &= 0x1FF;
    x += 975; x ^= 0x55; x *= 31; x -= 1050;
    x |= 0x02; x >>= 1; x &= 0xFF; x += 1025;
    x ^= 0x66; x *= 32; x -= 1100; x |= 0x01;
    x <<= 2; x &= 0x7FF; x += 1075; x ^= 0x77;
    x *= 33; x -= 1150; x |= 0x80; x >>= 2;
    x &= 0x3FF; x += 1125; x ^= 0x88; x *= 34;
    x -= 1200; x |= 0x40; x <<= 3; x &= 0x1FF;
    x += 1175; x ^= 0x99; x *= 35; x -= 1250;
    x |= 0x20; x >>= 3; x &= 0xFF; x += 1225;
    x ^= 0xAA; x *= 36; x -= 1300; x |= 0x10;
    x <<= 1; x &= 0x7FF; x += 1275; x ^= 0xBB;
    x *= 37; x -= 1350; x |= 0x08; x >>= 1;
    x &= 0x3FF; x += 1325; x ^= 0xCC; x *= 38;
    x -= 1400; x |= 0x04; x <<= 2; x &= 0x1FF;
    x += 1375; x ^= 0xDD; x *= 39; return x;
}

// Place functions in distant sections with 4KB+ spacing
__attribute__((section(".text.bar"), aligned(4096)))
int bar(int a) {
  return a + 1;
}

// 4KB padding between functions
// __attribute__((section(".text.padding1")))
// static const char padding1[4096] = {0};

__attribute__((section(".text.foo"), aligned(4096)))
int foo(int a) {
  return a + 1;
}

// 4KB padding between functions
// __attribute__((section(".text.padding2")))
// static const char padding2[4096] = {0};

__attribute__((section(".text.baz"), aligned(4096)))
int baz(int a) {
  return a + 1;
}

// Complex control flow function for realistic instruction cache behavior
__attribute__((section(".text.complex"), aligned(4096)))
int complex_function(int input) {
    int result = input;

    // Multiple nested branches
    if (result > 100) {
        for (int i = 0; i < 10; i++) {
            if (i % 2 == 0) {
                result += i * 3;
                if (result > 200) {
                    result -= 50;
                    switch (result % 4) {
                        case 0: result *= 2; break;
                        case 1: result += 7; break;
                        case 2: result -= 3; break;
                        default: result /= 2; break;
                    }
                }
            } else {
                result *= 2;
                if (result < 500) {
                    result += 25;
                } else {
                    result -= 75;
                }
            }
        }
    } else if (result > 50) {
        // Another branch with different control flow
        int temp = result;
        while (temp > 0) {
            temp -= 7;
            result += temp % 3;
            if (temp % 5 == 0) {
                result ^= 0x55;
            }
        }

        // Nested loops with conditions
        for (int j = 0; j < 5; j++) {
            for (int k = 0; k < 3; k++) {
                if ((j + k) % 2) {
                    result += j * k;
                } else {
                    result -= j + k;
                }
            }
        }
    } else {
        // Third major branch
        result *= 3;
        if (result & 1) {
            result <<= 2;
            result += 0xAA;
        } else {
            result >>= 1;
            result ^= 0x33;
        }

        // Function calls within branches
        result += bar(result % 10);
        result += foo(result % 20);
    }

    // Final complex computation
    if (result % 2) {
        result = (result * 17) % 1000;
    } else {
        result = (result * 23) % 1000;
    }

    return result;
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
  _mm_prefetch(bar, _MM_HINT_IT0);
  _mm_prefetch(foo, _MM_HINT_IT0);
  _mm_prefetch(baz, _MM_HINT_IT0);
  dummy_256_instructions(1);
//   complex_function(1);
  // bar(1);
  // foo(1);
  // baz(1);

  // 256 NOPs to allow prefetch to complete before monitoring starts
//   nop_delay_256();
  // spin_loop_1000_cycles();
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

  uint64_t l1i_miss_val = 0, itlb_miss_val = 0, l2_lines_in_val = 0, l2_miss_val = 0, insn_val = 0;
  perf_group_read(&pg, &l1i_miss_val, &itlb_miss_val, &l2_lines_in_val, &l2_miss_val, &insn_val);

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

  if (pg.l2_lines_in >= 0) {
    printf("L2-lines-in.all: %llu\n",
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