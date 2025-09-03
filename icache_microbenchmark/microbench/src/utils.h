#ifndef UTILS_H
#define UTILS_H

#include <stdint.h>
#include <stdbool.h>
#include <sys/types.h>

// System utilities
bool pin_to_cpu(int cpu);
bool elevate_realtime(int prio);
void lock_and_prefault(size_t bytes);

// File I/O helpers
bool write_file(const char* path, const char* val);
bool read_u64_from_file(const char* path, uint64_t* out);

// CPU frequency management
bool lock_cpu_freq(int cpu, uint64_t* hz_out);

// Timer utilities
uint64_t now_ns(void);

// Cache management
typedef struct {
    uint32_t l1i_size;    // L1I cache size in bytes
    uint32_t l2_size;     // L2 cache size in bytes (unified)
    uint32_t l3_size;     // L3 cache size in bytes (unified)
} CacheSizes;

CacheSizes detect_cache_sizes(void);
void flush_icache(void);

// Performance counters
typedef struct PerfGroup {
    int leader;    // INSTRUCTIONS (leader)
    int l1i_miss;  // member
    int itlb_miss; // member
} PerfGroup;

PerfGroup perf_group_open(void);
void perf_group_enable(int leader_fd);
void perf_group_disable(int leader_fd);
void perf_group_read(const PerfGroup* pg, uint64_t* l1i, uint64_t* itlb, uint64_t* insn);
void perf_group_close(PerfGroup* pg);

#endif // UTILS_H