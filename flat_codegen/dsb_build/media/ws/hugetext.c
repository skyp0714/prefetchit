/* hugetext.c — LD_PRELOAD: ask the kernel to back the executable text of the main program and of the listed shared libraries with
 * transparent huge pages (madvise(MADV_HUGEPAGE) on the 2 MB-aligned interior of each r-x file mapping). With CONFIG_READ_ONLY_THP_FOR_FS
 * khugepaged collapses read-only file-backed text asynchronously; progress is visible as FilePmdMapped in /proc/PID/smaps.
 * Env: HUGETEXT_LIBS="libc.so.6,libmemcached" (substrings; default: main program only), HUGETEXT_VERBOSE=1. */
#define _GNU_SOURCE
#include <link.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <stdint.h>
static const char *libs; static int verbose;
static int cb(struct dl_phdr_info *info, size_t sz, void *data) {
  const char *n = info->dlpi_name; int is_main = !n || !*n;
  if (!is_main) { if (!libs) return 0; const char *b = strrchr(n, '/'); b = b ? b + 1 : n; int hit = 0; char buf[512]; strncpy(buf, libs, 511); buf[511] = 0;
    for (char *t = strtok(buf, ","); t; t = strtok(NULL, ",")) if (strstr(b, t)) hit = 1; if (!hit) return 0; }
  for (int i = 0; i < info->dlpi_phnum; i++) {
    const ElfW(Phdr) *p = &info->dlpi_phdr[i];
    if (p->p_type != PT_LOAD || !(p->p_flags & PF_X)) continue;
    uintptr_t a = info->dlpi_addr + p->p_vaddr, e = a + p->p_memsz;
    uintptr_t a2 = (a + (2u << 20) - 1) & ~((uintptr_t)(2u << 20) - 1), e2 = e & ~((uintptr_t)(2u << 20) - 1);
    int r = -1; if (e2 > a2) r = madvise((void *)a2, e2 - a2, MADV_HUGEPAGE);
    if (verbose) fprintf(stderr, "hugetext: %s text %#lx-%#lx (%.1f MB) aligned %#lx-%#lx -> madvise %d\n", is_main ? "MAIN" : n, a, e, (e - a) / 1048576.0, a2, e2, r);
  }
  return 0;
}
__attribute__((constructor)) static void init(void) { libs = getenv("HUGETEXT_LIBS"); verbose = getenv("HUGETEXT_VERBOSE") != NULL; dl_iterate_phdr(cb, NULL); }
