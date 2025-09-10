#define _GNU_SOURCE
#define _DEFAULT_SOURCE 

#include "utils.h"
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <sched.h>
#include <unistd.h>
#include <sys/mman.h>
#include <time.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <string.h>

// ---------- sys helpers ----------
bool pin_to_cpu(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        fprintf(stderr, "WARN: sched_setaffinity(%d) failed: %s\n", cpu, strerror(errno));
        return false;
    }
    return true;
}

bool elevate_realtime(int prio) {
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

void lock_and_prefault(size_t bytes) {
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

// ---------- File I/O helpers ----------
bool write_file(const char* path, const char* val) {
    FILE* f = fopen(path, "w");
    if (!f) return false;
    bool ok = (fputs(val, f) >= 0);
    fclose(f);
    return ok;
}

bool read_u64_from_file(const char* path, uint64_t* out) {
    FILE* f = fopen(path, "r");
    if (!f) return false;
    unsigned long long v = 0;
    int rc = fscanf(f, "%llu", &v);
    fclose(f);
    if (rc != 1) return false;
    *out = (uint64_t)v;
    return true;
}

// ---------- CPU frequency management ----------
bool lock_cpu_freq(int cpu, uint64_t* hz_out) {
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

// ---------- Timer utilities ----------
uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

// ---------- Cache management ----------
CacheSizes detect_cache_sizes(void) {
    CacheSizes sizes = {0};
    
    // Try to detect via CPUID first (more reliable)
    uint32_t eax, ebx, ecx, edx;
    
    // Check if CPUID cache info is available (leaf 4)
    eax = 4; ecx = 0;  // L1 instruction cache
    __asm__ volatile("cpuid" : "=a"(eax), "=b"(ebx), "=c"(ecx), "=d"(edx) : "a"(eax), "c"(ecx));
    
    if ((eax & 0x1F) == 2) {  // Instruction cache type
        uint32_t ways = ((ebx >> 22) & 0x3FF) + 1;
        uint32_t line_size = (ebx & 0xFFF) + 1;
        uint32_t sets = ecx + 1;
        sizes.l1i_size = ways * line_size * sets;
    } else {
        sizes.l1i_size = 32 * 1024;  // Default 32KB
    }
    
    // Try L2 cache (leaf 4, index 1)
    eax = 4; ecx = 1;
    __asm__ volatile("cpuid" : "=a"(eax), "=b"(ebx), "=c"(ecx), "=d"(edx) : "a"(eax), "c"(ecx));
    
    if ((eax & 0x1F) == 3) {  // Unified cache type
        uint32_t ways = ((ebx >> 22) & 0x3FF) + 1;
        uint32_t line_size = (ebx & 0xFFF) + 1;
        uint32_t sets = ecx + 1;
        sizes.l2_size = ways * line_size * sets;
    } else {
        sizes.l2_size = 256 * 1024;  // Default 256KB
    }
    
    // Try L3 cache (leaf 4, index 2)
    eax = 4; ecx = 2;
    __asm__ volatile("cpuid" : "=a"(eax), "=b"(ebx), "=c"(ecx), "=d"(edx) : "a"(eax), "c"(ecx));
    
    if ((eax & 0x1F) == 3) {  // Unified cache type
        uint32_t ways = ((ebx >> 22) & 0x3FF) + 1;
        uint32_t line_size = (ebx & 0xFFF) + 1;
        uint32_t sets = ecx + 1;
        sizes.l3_size = ways * line_size * sets;
    } else {
        sizes.l3_size = 8 * 1024 * 1024;  // Default 8MB
    }
    
    return sizes;
}

void flush_icache(void) {
    // Detect actual cache sizes via CPUID
    CacheSizes sizes = detect_cache_sizes();
    
    // L2 is unified (data + instruction), so we need to account for both
    // Use L1I + L2 total size, with 2x multiplier for complete eviction
    const size_t FLUSH_SIZE = (sizes.l1i_size + sizes.l2_size) * 2;
    
    fprintf(stderr, "INFO: Detected cache sizes - L1I: %uKB, L2: %uKB, L3: %uMB\n",
            sizes.l1i_size / 1024, sizes.l2_size / 1024, sizes.l3_size / (1024*1024));
    fprintf(stderr, "INFO: Flushing instruction caches with %.1f MB of code\n", 
            (double)FLUSH_SIZE / (1024.0 * 1024.0));
    
    // Allocate executable memory
    void* flush_mem = mmap(NULL, FLUSH_SIZE, PROT_READ | PROT_WRITE | PROT_EXEC,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    
    if (flush_mem == MAP_FAILED) {
        fprintf(stderr, "WARN: icache flush failed to allocate memory: %s\n", strerror(errno));
        return;
    }
    
    // Fill with varied NOP patterns to avoid optimization
    unsigned char* code = (unsigned char*)flush_mem;
    for (size_t i = 0; i < FLUSH_SIZE - 1; i += 4) {
        code[i]   = 0x90;  // NOP
        code[i+1] = 0x90;  // NOP  
        code[i+2] = 0x66;  // 16-bit prefix
        code[i+3] = 0x90;  // NOP (becomes 2-byte NOP with prefix)
    }
    // Add return instruction at the end
    code[FLUSH_SIZE - 1] = 0xC3;  // RET
    
    // Memory barrier to ensure writes are complete
    __builtin___clear_cache((char*)flush_mem, (char*)flush_mem + FLUSH_SIZE);
    
    // Execute the code to force instruction cache population/eviction
    void (*flush_func)(void) = (void(*)(void))flush_mem;
    
    uint64_t start_ns = now_ns();
    flush_func();
    uint64_t end_ns = now_ns();
    
    fprintf(stderr, "INFO: I-cache flush completed in %llu ns\n", 
            (unsigned long long)(end_ns - start_ns));
    
    // Clean up
    munmap(flush_mem, FLUSH_SIZE);
}

// ---------- Performance counters ----------
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
    return perf_event_open_sys(&pe, 0 /*self*/, 0 /*CPU 0*/, group_fd, 0);
}

static int open_hw_evt(uint64_t hw_config, int group_fd) {
    struct perf_event_attr pe;
    memset(&pe, 0, sizeof(pe));
    pe.type = PERF_TYPE_HARDWARE;
    pe.size = sizeof(pe);
    pe.config = hw_config;
    pe.disabled = 1;
    pe.exclude_kernel = 1;
    pe.exclude_hv = 1;
    return perf_event_open_sys(&pe, 0 /*self*/, 0 /*CPU 0*/, group_fd, 0);
}

static int read_counter64(int fd, uint64_t* out) {
    ssize_t r = read(fd, out, sizeof(*out));
    return (r == (ssize_t)sizeof(*out)) ? 0 : -1;
}

PerfGroup perf_group_open(void) {
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

void perf_group_enable(int leader_fd) {
    if (leader_fd >= 0) {
        ioctl(leader_fd, PERF_EVENT_IOC_RESET,  PERF_IOC_FLAG_GROUP);
        ioctl(leader_fd, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
    }
}

void perf_group_disable(int leader_fd) {
    if (leader_fd >= 0) {
        ioctl(leader_fd, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
    }
}

void perf_group_read(const PerfGroup* pg, uint64_t* l1i, uint64_t* itlb, uint64_t* insn) {
    if (l1i)  { *l1i  = 0; if (pg->l1i_miss  >= 0) (void)read_counter64(pg->l1i_miss,  l1i); }
    if (itlb) { *itlb = 0; if (pg->itlb_miss >= 0) (void)read_counter64(pg->itlb_miss, itlb); }
    if (insn) { *insn = 0; if (pg->leader    >= 0) (void)read_counter64(pg->leader,    insn); }
}

void perf_group_close(PerfGroup* pg) {
    if (!pg) return;
    if (pg->l1i_miss  >= 0) { close(pg->l1i_miss);  pg->l1i_miss = -1; }
    if (pg->itlb_miss >= 0) { close(pg->itlb_miss); pg->itlb_miss = -1; }
    if (pg->leader    >= 0) { close(pg->leader);    pg->leader = -1; }
}