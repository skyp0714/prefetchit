// icache_flush_dummy.c
// Executes a large generated code region on a pinned CPU.
#define _GNU_SOURCE

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sched.h>
#include <sys/mman.h>
#include <unistd.h>

static int pin_to_cpu_local(int cpu) {
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        fprintf(stderr, "WARN: sched_setaffinity(%d) failed: %s\n", cpu, strerror(errno));
        return 0;
    }
    return 1;
}

static size_t choose_stride(size_t pages) {
    size_t stride = 131;
    while (stride > 1 && pages % stride == 0) {
        stride -= 2;
    }
    return stride ? stride : 1;
}

int main(int argc, char **argv) {
    size_t code_kib = 8192;
    int cpu = 10;
    int passes = 1;

    if (argc > 1) {
        code_kib = (size_t)strtoull(argv[1], NULL, 0);
    }
    if (argc > 2) {
        cpu = atoi(argv[2]);
    }
    if (argc > 3) {
        passes = atoi(argv[3]);
    }
    if (code_kib < 4) {
        code_kib = 4;
    }
    if (passes < 1) {
        passes = 1;
    }

    pin_to_cpu_local(cpu);

    size_t bytes = code_kib * 1024ull;
    unsigned char *code = mmap(NULL, bytes, PROT_READ | PROT_WRITE | PROT_EXEC,
                               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (code == MAP_FAILED) {
        fprintf(stderr, "ERROR: mmap executable code failed: %s\n", strerror(errno));
        return 1;
    }

    for (size_t i = 0; i + 1 < bytes; ++i) {
        code[i] = 0x90;
    }
    code[bytes - 1] = 0xc3;
    __builtin___clear_cache((char *)code, (char *)code + bytes);

    void (*fn)(void) = (void (*)(void))code;
    for (int i = 0; i < passes; ++i) {
        fn();
    }

    munmap(code, bytes);

    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size > 0) {
        size_t pages = bytes / (size_t)page_size;
        if (pages < 1) {
            pages = 1;
        }
        size_t tlb_bytes = pages * (size_t)page_size;
        unsigned char *tlb_code = mmap(NULL, tlb_bytes, PROT_READ | PROT_WRITE | PROT_EXEC,
                                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (tlb_code != MAP_FAILED) {
            for (size_t page = 0; page < pages; ++page) {
                unsigned char *stub = tlb_code + page * (size_t)page_size;
                for (int i = 0; i < 63; ++i) {
                    stub[i] = 0x90;
                }
                stub[63] = 0xc3;
            }
            __builtin___clear_cache((char *)tlb_code, (char *)tlb_code + tlb_bytes);

            size_t stride = choose_stride(pages);
            for (int pass = 0; pass < passes; ++pass) {
                size_t idx = (size_t)pass % pages;
                for (size_t i = 0; i < pages; ++i) {
                    void (*stub)(void) = (void (*)(void))(tlb_code + idx * (size_t)page_size);
                    stub();
                    idx += stride;
                    idx %= pages;
                }
            }
            munmap(tlb_code, tlb_bytes);
        }
    }

    return 0;
}
