#ifndef UTILS_H
#define UTILS_H

#include <stdint.h>
#include <stdbool.h>
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif

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
    int leader;       // INSTRUCTIONS (leader)
    int l1i_miss;     // member
    int itlb_miss;    // generic iTLB-load-misses
    int itlb_stlb_hit;// member: ITLB_MISSES.STLB_HIT
    int itlb_walk;    // member: ITLB_MISSES.WALK_COMPLETED, i.e. STLB miss
    int dtlb_load_walk; // member: DTLB_LOAD_MISSES.WALK_COMPLETED
    int branch_miss;  // member: branch-misses
    int l2_lines_in;  // legacy raw counter; not used in current plots
    int l2_miss;      // legacy raw counter; not used in current plots
    int l2_code_rd;   // member: l2_rqsts.all_code_rd
    int l2_code_miss; // member: L2_RQSTS.CODE_RD_MISS
    int l2_all_miss;  // member: L2_RQSTS.MISS
    int llc_load_miss;// member: LLC-load-misses
    int llc_miss;     // member: longest_lat_cache.miss
} PerfGroup;

PerfGroup perf_group_open(pid_t tid, int cpu);
void perf_group_enable(int leader_fd);
void perf_group_disable(int leader_fd);
void perf_group_enable_all(const PerfGroup* pg);
void perf_group_disable_all(const PerfGroup* pg);
void perf_counter_reset_enable(int fd);
void perf_counter_disable(int fd);
uint64_t perf_counter_read_value(int fd);
void perf_group_read(const PerfGroup* pg, uint64_t* l1i, uint64_t* itlb, uint64_t* l2_lines_in, uint64_t* l2_miss, uint64_t* insn);
void perf_group_read_extended(const PerfGroup* pg, uint64_t* l1i, uint64_t* itlb,
                              uint64_t* l2_lines_in, uint64_t* l2_miss,
                              uint64_t* l2_code_rd, uint64_t* llc_load_miss,
                              uint64_t* llc_miss, uint64_t* insn);
void perf_group_read_tlb(const PerfGroup* pg, uint64_t* itlb_stlb_hit,
                         uint64_t* itlb_walk);
void perf_group_read_misses(const PerfGroup* pg, uint64_t* l2_code_miss,
                            uint64_t* l2_all_miss, uint64_t* llc_miss);
void perf_group_close(PerfGroup* pg);

#ifdef __cplusplus
}
#endif

#endif // UTILS_H
