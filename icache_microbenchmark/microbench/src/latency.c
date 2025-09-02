// latency.c  (C11/gnu11)
// Build example:
//   gcc -O3 -std=gnu11 -m64 -mprefetchi -no-pie -fno-plt \
//       -DENABLE_PREFETCHI_INTRIN \
//       latency.c -o lat_bench
// Optional:  -DPREFETCHI_HINT=_MM_HINT_IT1

#define _GNU_SOURCE
#define _DEFAULT_SOURCE 

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <sched.h>
#include <unistd.h>
#include <sys/mman.h>
#include <time.h>
#include <signal.h>
#include <stdlib.h>
#include <pthread.h>
#include <sys/stat.h>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>

typedef void (*TaskFn)(void);
static volatile uint64_t g_sink = 0;

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

#ifndef TASK_NOP_B
#define TASK_NOP_B 128
#endif
#define STR2(x) #x
#define STR(x) STR2(x)

#ifndef TASKS_SECTION
#define TASKS_SECTION ".text.tasks"
#endif
#ifndef TASK_CODE_ALIGN
#define TASK_CODE_ALIGN 256
#endif

#ifndef CODE_PAD_B
#define CODE_PAD_B 256
#endif

#define INSERT_TASK_PAD(NAME, B)                                         \
  asm(                                                                    \
    ".pushsection " TASKS_SECTION ",\"ax\",@progbits\n\t"                 \
    ".p2align 6\n\t"                                                      \
    ".globl " #NAME "\n\t"                                                \
    ".type  " #NAME ", @function\n\t"                                     \
    #NAME ":\n\t"                                                         \
    ".fill " STR(B) ", 1, 0x90\n\t" /* B bytes of NOP (0x90) */           \
    ".size  " #NAME ", . - " #NAME "\n\t"                                 \
    ".popsection\n\t" )

#ifndef TASKS
#define TASKS(X) \
  X(0)   X(1)   X(2)   X(3)   X(4)   X(5)   X(6)   X(7)   X(8)   X(9)   X(10)  X(11)  X(12)  X(13)  X(14)  X(15)  \
  X(16)  X(17)  X(18)  X(19)  X(20)  X(21)  X(22)  X(23)  X(24)  X(25)  X(26)  X(27)  X(28)  X(29)  X(30)  X(31)  \
  X(32)  X(33)  X(34)  X(35)  X(36)  X(37)  X(38)  X(39)  X(40)  X(41)  X(42)  X(43)  X(44)  X(45)  X(46)  X(47)  \
  X(48)  X(49)  X(50)  X(51)  X(52)  X(53)  X(54)  X(55)  X(56)  X(57)  X(58)  X(59)  X(60)  X(61)  X(62)  X(63)  \
  X(64)  X(65)  X(66)  X(67)  X(68)  X(69)  X(70)  X(71)  X(72)  X(73)  X(74)  X(75)  X(76)  X(77)  X(78)  X(79)  \
  X(80)  X(81)  X(82)  X(83)  X(84)  X(85)  X(86)  X(87)  X(88)  X(89)  X(90)  X(91)  X(92)  X(93)  X(94)  X(95)  \
  X(96)  X(97)  X(98)  X(99)  X(100) X(101) X(102) X(103) X(104) X(105) X(106) X(107) X(108) X(109) X(110) X(111) \
  X(112) X(113) X(114) X(115) X(116) X(117) X(118) X(119) X(120) X(121) X(122) X(123) X(124) X(125) X(126) X(127) \
  X(128) X(129) X(130) X(131) X(132) X(133) X(134) X(135) X(136) X(137) X(138) X(139) X(140) X(141) X(142) X(143) \
  X(144) X(145) X(146) X(147) X(148) X(149) X(150) X(151) X(152) X(153) X(154) X(155) X(156) X(157) X(158) X(159) \
  X(160) X(161) X(162) X(163) X(164) X(165) X(166) X(167) X(168) X(169) X(170) X(171) X(172) X(173) X(174) X(175) \
  X(176) X(177) X(178) X(179) X(180) X(181) X(182) X(183) X(184) X(185) X(186) X(187) X(188) X(189) X(190) X(191) \
  X(192) X(193) X(194) X(195) X(196) X(197) X(198) X(199) X(200) X(201) X(202) X(203) X(204) X(205) X(206) X(207) \
  X(208) X(209) X(210) X(211) X(212) X(213) X(214) X(215) X(216) X(217) X(218) X(219) X(220) X(221) X(222) X(223) \
  X(224) X(225) X(226) X(227) X(228) X(229) X(230) X(231) X(232) X(233) X(234) X(235) X(236) X(237) X(238) X(239) \
  X(240) X(241) X(242) X(243) X(244) X(245) X(246) X(247) X(248) X(249) X(250) X(251) X(252) X(253) X(254) X(255)
#endif

// Forward declarations (symbol names are used for prefetch)
#define DECL_TASK(N) void task_##N(void);
TASKS(DECL_TASK)
#undef DECL_TASK

// ---------- PREFETCHI (intrinsic path) ----------
#if defined(ENABLE_PREFETCHI_INTRIN)
#include <x86intrin.h>
#ifndef PREFETCHI_HINT
#define PREFETCHI_HINT _MM_HINT_IT0  
#endif

// Prefetch by symbol id (emits prefetchit0/1 to &task_N)
__attribute__((target("prefetchi"), always_inline))
static inline void prefetch_i_by_id(int id) {
    switch (id) {
    #define CASE_ID(N) case N: _mm_prefetch((const void*)&task_##N, PREFETCHI_HINT); break;
        TASKS(CASE_ID)
    #undef CASE_ID
    default: break;
    }
}
#endif  // ENABLE_PREFETCHI_INTRIN

// ---------- NOP window ----------
#define PREFETCH_NOPS_WINDOW 32
static int g_prefetch_pos = PREFETCH_NOPS_WINDOW / 2;
static int g_prefetch_enable = 1;

#define EMIT_NOPS_CASE(N) case N: asm volatile( \
    ".rept " STR(N) "\n\t" "nop\n\t" ".endr\n\t" ::: "memory"); break;

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

// ---------- prefetch injection ----------
// Replace pointer-based prefetch with symbol-id based one
static inline void pre_call_dummy_by_id(int id, int pos) {
    if (pos < 0) pos = 0;
    if (pos > PREFETCH_NOPS_WINDOW) pos = PREFETCH_NOPS_WINDOW;
    emit_nops_exact(pos);
    if (g_prefetch_enable) {
    #if defined(ENABLE_PREFETCHI_INTRIN)
        prefetch_i_by_id(id);
    #endif
    }
    emit_nops_exact(PREFETCH_NOPS_WINDOW - pos);
}

// ---------- prefetch_all_tasks ----------
// __attribute__((noinline))
// void prefetch_all_tasks(void) {
// #if defined(ENABLE_PREFETCHI_INTRIN)
//   // Iterate all tasks via TASKS
//   #define TO_FN(N) task_##N,
//   static TaskFn const all[] = { TASKS(TO_FN) };
//   #undef TO_FN
//   for (unsigned i = 0; i < sizeof(all)/sizeof(all[0]); ++i)
//     prefetch_i_symbol(all[i]);
// #else
//   (void)0;
// #endif
// }

// ---------- task definitions ----------
#define DEFINE_TASK(N) \
void __attribute__((noinline, section(TASKS_SECTION), aligned(TASK_CODE_ALIGN))) task_##N(void) { \
    uint64_t x = (uint64_t)(0x9e3779b97f4a7c15ULL ^ (N * 1315423911u)); \
    for (int i = 0; i < 128 + (N % 7); ++i) { \
        x ^= (x << ((N % 5) + 1)); \
        x += (uint64_t)(i * (N + 3) + 0x27d4eb2d); \
        x ^= (x >> ((N % 6) + 1)); \
    } \
    g_sink += x; \
    asm volatile( \
        ".rept "  STR(TASK_NOP_B) "\n\t" \
        "nop\n\t" \
        ".endr\n\t" ::: "memory"); \
} \
\
INSERT_TASK_PAD(task_pad_##N, CODE_PAD_B);

#define DEF_TASK(N) DEFINE_TASK(N)
TASKS(DEF_TASK)
#undef DEF_TASK

// ---------- sys helpers ----------
static bool pin_to_cpu(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        fprintf(stderr, "WARN: sched_setaffinity(%d) failed: %s\n", cpu, strerror(errno));
        return false;
    }
    return true;
}
static bool elevate_realtime(int prio) {
    struct sched_param sp;
    memset(&sp, 0, sizeof(sp));
    sp.sched_priority = prio;
    if (sched_setscheduler(0, SCHED_FIFO, &sp) != 0) {
        fprintf(stderr, "WARN: sched_setscheduler(SCHED_FIFO,%d) failed: %s\n",
                prio, strerror(errno));
        return false;
    }
    return true;
}
static void lock_and_prefault(size_t bytes) {
    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        fprintf(stderr, "WARN: mlockall failed: %s\n", strerror(errno));
    }
    long page = sysconf(_SC_PAGESIZE);
    volatile uint8_t* buf = (volatile uint8_t*) mmap(NULL, bytes, PROT_READ | PROT_WRITE,
                                                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (buf == MAP_FAILED) {
        fprintf(stderr, "WARN: mmap prefault buffer failed: %s\n", strerror(errno));
        return;
    }
    for (size_t off = 0; off < bytes; off += (size_t)page) buf[off] = (uint8_t)(off);
}

// simple file IO in C
static bool write_file(const char* path, const char* val) {
    FILE* f = fopen(path, "w");
    if (!f) return false;
    bool ok = (fputs(val, f) >= 0);
    fclose(f);
    return ok;
}
static bool read_u64_from_file(const char* path, uint64_t* out) {
    FILE* f = fopen(path, "r");
    if (!f) return false;
    unsigned long long v = 0;
    int rc = fscanf(f, "%llu", &v);
    fclose(f);
    if (rc != 1) return false;
    *out = (uint64_t)v;
    return true;
}

// Try to lock CPU frequency to max and return current Hz
static bool lock_cpu_freq(int cpu, uint64_t* hz_out) {
    char base[256];
    snprintf(base, sizeof(base), "/sys/devices/system/cpu/cpu%d/cpufreq", cpu);
    struct stat st;
    if (stat(base, &st) != 0) {
        fprintf(stderr, "WARN: cpufreq path not found for cpu %d\n", cpu);
        return false;
    }
    char path[512];

    // governor -> performance
    snprintf(path, sizeof(path), "%s/scaling_governor", base);
    (void)write_file(path, "performance\n");

    // read max kHz
    uint64_t max_khz = 0;
    snprintf(path, sizeof(path), "%s/cpuinfo_max_freq", base);
    if (!read_u64_from_file(path, &max_khz)) {
        snprintf(path, sizeof(path), "%s/scaling_max_freq", base);
        if (!read_u64_from_file(path, &max_khz)) {
            fprintf(stderr, "WARN: cannot read max freq\n");
            return false;
        }
    }
    // set min/max = max
    char buf[64];
    snprintf(buf, sizeof(buf), "%llu", (unsigned long long)max_khz);
    snprintf(path, sizeof(path), "%s/scaling_min_freq", base);
    (void)write_file(path, buf);
    snprintf(path, sizeof(path), "%s/scaling_max_freq", base);
    (void)write_file(path, buf);

    // confirm current kHz
    uint64_t cur_khz = 0;
    snprintf(path, sizeof(path), "%s/scaling_cur_freq", base);
    if (!read_u64_from_file(path, &cur_khz)) cur_khz = max_khz;

    // Use current frequency for fixed_hz to match the printed target
    *hz_out = cur_khz * 1000ull;
    fprintf(stderr, "INFO: CPU%d freq locked target ~ %llu kHz\n",
            cpu, (unsigned long long)cur_khz);
    return true;
}

// ---------- queue ----------
typedef struct {
    TaskFn fn;
    int    id; // symbol id (index into TASKS order)
} QueueItem;

// Change queue to carry (fn, id)
#define TASK_ELEM(N) task_##N,
static TaskFn const kAllTasks[] = { TASKS(TASK_ELEM) };
#undef TASK_ELEM
enum { kNumTasks = (int)(sizeof(kAllTasks)/sizeof(kAllTasks[0])) };

static QueueItem* build_queue(int count) {
    QueueItem* q = (QueueItem*)malloc((size_t)count * sizeof(QueueItem));
    if (!q) return NULL;
    for (int i = 0; i < count; ++i) {
        int id = i % kNumTasks;
        q[i].fn = kAllTasks[id];
        q[i].id = id;
    }
    return q;
}
static inline void run_queue(QueueItem* q, int len) {
    for (int i = 0; i < len; ++i) {
        const QueueItem it = q[i];
        pre_call_dummy_by_id(it.id, g_prefetch_pos);
        it.fn();
    }
}

static inline uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

// perf helpers
static int perf_event_open_sys(struct perf_event_attr* attr, pid_t pid, int cpu, int group_fd, unsigned long flags) {
    return (int)syscall(SYS_perf_event_open, attr, pid, cpu, group_fd, flags);
}
static int open_cache_evt(uint32_t cache, uint32_t op, uint32_t res, int group_fd) {
    struct perf_event_attr pe;
    memset(&pe, 0, sizeof(pe));
    pe.type = PERF_TYPE_HW_CACHE;
    pe.size = sizeof(pe);
    pe.config = ((uint64_t)cache) | ((uint64_t)op << 8) | ((uint64_t)res << 16);
    pe.disabled = 1;
    pe.exclude_kernel = 1;
    pe.exclude_hv = 1;
    return perf_event_open_sys(&pe, 0 /*self*/, -1 /*any cpu*/, group_fd, 0);
}
// PERF_TYPE_HARDWARE generic open (e.g., INSTRUCTIONS)
static int open_hw_evt(uint64_t hw_config, int group_fd) {
    struct perf_event_attr pe;
    memset(&pe, 0, sizeof(pe));
    pe.type = PERF_TYPE_HARDWARE;
    pe.size = sizeof(pe);
    pe.config = hw_config;
    pe.disabled = 1;
    pe.exclude_kernel = 1;
    pe.exclude_hv = 1;
    return perf_event_open_sys(&pe, 0 /*self*/, -1 /*any cpu*/, group_fd, 0);
}
static inline int read_counter64(int fd, uint64_t* out) {
    ssize_t r = read(fd, out, sizeof(*out));
    return (r == (ssize_t)sizeof(*out)) ? 0 : -1;
}

// Simplified perf group helpers
typedef struct PerfGroup {
    int leader;    // INSTRUCTIONS (leader)
    int l1i_miss;  // member
    int itlb_miss; // member
} PerfGroup;

static PerfGroup perf_group_open(void) {
    PerfGroup pg = { .leader = -1, .l1i_miss = -1, .itlb_miss = -1 };
    // Leader: INSTRUCTIONS
    int leader = open_hw_evt(PERF_COUNT_HW_INSTRUCTIONS, -1);
    if (leader < 0) {
        fprintf(stderr, "WARN: perf: failed to open INSTRUCTIONS leader; perf disabled.\n");
        return pg;
    }
    pg.leader = leader;
    // Members: L1I-load-misses, iTLB-load-misses (best-effort)
    int l1i = open_cache_evt(PERF_COUNT_HW_CACHE_L1I,
                             PERF_COUNT_HW_CACHE_OP_READ,
                             PERF_COUNT_HW_CACHE_RESULT_MISS,
                             pg.leader);
    if (l1i >= 0) pg.l1i_miss = l1i;

    int itlb = open_cache_evt(PERF_COUNT_HW_CACHE_ITLB,
                              PERF_COUNT_HW_CACHE_OP_READ,
                              PERF_COUNT_HW_CACHE_RESULT_MISS,
                              pg.leader);
    if (itlb >= 0) pg.itlb_miss = itlb;

    fprintf(stderr, "INFO: perf opened. members: L1I=%s, ITLB=%s\n",
            (pg.l1i_miss >= 0 ? "ok" : "N/A"),
            (pg.itlb_miss >= 0 ? "ok" : "N/A"));
    return pg;
}
static inline void perf_group_enable(int leader_fd) {
    if (leader_fd >= 0) {
        ioctl(leader_fd, PERF_EVENT_IOC_RESET,  PERF_IOC_FLAG_GROUP);
        ioctl(leader_fd, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
    }
}
static inline void perf_group_disable(int leader_fd) {
    if (leader_fd >= 0) {
        ioctl(leader_fd, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
    }
}
static void perf_group_read(const PerfGroup* pg, uint64_t* l1i, uint64_t* itlb, uint64_t* insn) {
    if (l1i)  { *l1i  = 0; if (pg->l1i_miss  >= 0) (void)read_counter64(pg->l1i_miss,  l1i); }
    if (itlb) { *itlb = 0; if (pg->itlb_miss >= 0) (void)read_counter64(pg->itlb_miss, itlb); }
    if (insn) { *insn = 0; if (pg->leader    >= 0) (void)read_counter64(pg->leader,    insn); }
}
static void perf_group_close(PerfGroup* pg) {
    if (!pg) return;
    if (pg->l1i_miss  >= 0) { close(pg->l1i_miss);  pg->l1i_miss = -1; }
    if (pg->itlb_miss >= 0) { close(pg->itlb_miss); pg->itlb_miss = -1; }
    if (pg->leader    >= 0) { close(pg->leader);    pg->leader = -1; }
}

// ---------- main ----------
int main(int argc, char** argv) {
    int cpu = 0;
    int rounds = 1;
    int qlen = 256;
    int rt_prio = 80;

    if (argc > 1) { int v = atoi(argv[1]); if (v > 0) rounds = v; }
    if (argc > 2) { int v = atoi(argv[2]); if (v > 0) qlen   = v; }
    if (argc > 3) { int p = atoi(argv[3]); if (p < 0) p = 0; if (p > PREFETCH_NOPS_WINDOW) p = PREFETCH_NOPS_WINDOW; g_prefetch_pos = p; }
    if (argc > 4) { int e = atoi(argv[4]); g_prefetch_enable = (e != 0); }

    bool cpu_has = has_prefetchi();
    fprintf(stderr, "INFO: CPU PREFETCHI (prefetchit0/1) support: %s\n", cpu_has ? "yes" : "no");

    // signals
    sigset_t set; sigemptyset(&set);
    sigaddset(&set, SIGALRM); sigaddset(&set, SIGCHLD);
    pthread_sigmask(SIG_BLOCK, &set, NULL);

    pin_to_cpu(cpu);
    elevate_realtime(rt_prio);
    lock_and_prefault(8ull * 1024 * 1024);

    uint64_t fixed_hz = 0;
    bool freq_locked = (geteuid() == 0) && lock_cpu_freq(cpu, &fixed_hz);
    if (!freq_locked) {
        fprintf(stderr, "WARN: CPU freq lock failed or not root; proceeding without fixed freq.\n");
    }

    QueueItem* queue = build_queue(qlen);
    if (!queue) {
        fprintf(stderr, "FATAL: queue alloc failed\n");
        return 1;
    }

    // --- perf icache metrics setup (simplified) ---
    PerfGroup pg = perf_group_open();
    if (pg.leader >= 0) perf_group_enable(pg.leader);

    uint64_t tsc_start = rdtsc_begin();
    uint64_t ns_start  = now_ns();
    for (int r = 0; r < rounds; ++r) run_queue(queue, qlen);
    uint64_t ns_end    = now_ns();
    uint64_t tsc_end   = rdtsc_end();

    if (pg.leader >= 0) perf_group_disable(pg.leader);

    uint64_t l1i_miss_val = 0, itlb_miss_val = 0, insn_val = 0;
    perf_group_read(&pg, &l1i_miss_val, &itlb_miss_val, &insn_val);

    // Report: absolute misses and MPKI
    if (pg.l1i_miss >= 0) {
        double mpki = (insn_val ? (double)l1i_miss_val * 1000.0 / (double)insn_val : 0.0);
        printf("L1I-load-misses: %llu  (MPKI=%.3f)\n",
               (unsigned long long)l1i_miss_val, mpki);
    } else {
        printf("L1I-load-misses: N/A\n");
    }
    if (pg.itlb_miss >= 0) {
        double mpki = (insn_val ? (double)itlb_miss_val * 1000.0 / (double)insn_val : 0.0);
        printf("iTLB-load-misses: %llu  (MPKI=%.3f)\n",
               (unsigned long long)itlb_miss_val, mpki);
    } else {
        printf("iTLB-load-misses: N/A\n");
    }
    if (pg.leader >= 0) {
        printf("Instructions: %llu\n", (unsigned long long)insn_val);
    }

    uint64_t ns  = ns_end - ns_start;
    uint64_t cyc = tsc_end - tsc_start;
    uint64_t ops = (uint64_t)qlen * (uint64_t)rounds;

    printf("Ran %llu tasks (%d funcs RR) in %d rounds on CPU %d\n",
           (unsigned long long)ops, kNumTasks, rounds, cpu);
    printf("Time(monotonic): %llu ns, TSC: %llu cycles\n",
           (unsigned long long)ns, (unsigned long long)cyc);

    if (ns) {
        double cyc_per_ns   = (double)cyc / (double)ns;
        double ns_per_task  = (double)ns  / (double)ops;
        printf("Raw Cycles/ns: %.3f  |  ns/task(raw): %.3f\n", cyc_per_ns, ns_per_task);
    }
    if (freq_locked && fixed_hz) {
        long double fixed_ns = (long double)cyc * 1.0e9L / (long double)fixed_hz;
        long double fixed_ns_per_task = fixed_ns / (long double)ops;
        printf("Fixed CPU freq: %.3f MHz\n", (double)fixed_hz / 1.0e6);
        printf("Time(from fixed freq): %.0Lf ns  |  ns/task(fixed): %.3Lf\n",
               fixed_ns, fixed_ns_per_task);
    }

    printf("sink=%llu\n", (unsigned long long)g_sink);

    // perf fd cleanup
    perf_group_close(&pg);

    free(queue);
    return 0;
}