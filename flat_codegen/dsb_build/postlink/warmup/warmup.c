/* LD_PRELOAD wake-up warm-up: after a blocking call returns (recv/read/poll/epoll_wait/cond wait/...),
 * if the call took longer than WARMUP_MIN_CYCLES (i.e. the thread slept and the core was reused),
 * issue prefetcht1 for the first WARMUP_N code lines of the per-hook list (WARMUP_LIST: "hook dso offset" per line,
 * ordered by first use after the wake). Compile with -DNOPTWIN to replace prefetcht1 by a same-size NOP. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/epoll.h>
#include <sys/uio.h>
#include <pthread.h>
#include <x86intrin.h>

enum { H_RECV, H_READ, H_POLL, H_EPOLL, H_COND, H_ANY, H_MAX };
static const char *hook_names[H_MAX] = {"recv", "read", "poll", "epoll_wait", "cond", "any"};
static uintptr_t *lines[H_MAX]; static int nlines[H_MAX];
static long min_cycles = 20000; static int burst_n = 64; static int stage_n = 0; static int pace = 0; /* pause iterations between 32-line batches (0 = no pacing) */
static long stat_calls[H_MAX], stat_warm[H_MAX];
static char dso_names[64][128]; static uintptr_t dso_base[64]; static int ndso;

static int cb(struct dl_phdr_info *info, size_t sz, void *data) {
  const char *n = info->dlpi_name; if (!n || !*n) n = "MAIN";
  const char *b = strrchr(n, '/'); b = b ? b + 1 : n;
  if (ndso < 64) { strncpy(dso_names[ndso], b, 127); dso_base[ndso] = info->dlpi_addr; ndso++; }
  return 0;
}
static uintptr_t base_of(const char *dso) {
  size_t n = strlen(dso);
  for (int i = 0; i < ndso; i++) { size_t m = strlen(dso_names[i]); size_t k = n < m ? n : m;
    if (!strncmp(dso_names[i], dso, k) && (k >= 8 || !strcmp(dso_names[i], dso))) return dso_base[i] + 1; } /* prefix match: libX.so.6 vs libX.so.6.0.30; +1 marks found */
  return 0;
}
__attribute__((constructor)) static void init(void) {
  const char *e;
  if ((e = getenv("WARMUP_MIN_CYCLES"))) min_cycles = atol(e);
  if ((e = getenv("WARMUP_N"))) burst_n = atoi(e);
  if ((e = getenv("WARMUP_STAGE"))) stage_n = atoi(e);
  if ((e = getenv("WARMUP_PACE"))) pace = atoi(e);
  dl_iterate_phdr(cb, NULL);
  const char *lf = getenv("WARMUP_LIST"); if (!lf) return;
  FILE *f = fopen(lf, "r"); if (!f) return;
  char hook[32], dso[128]; unsigned long off; int cap[H_MAX] = {0};
  while (fscanf(f, "%31s %127s %lx", hook, dso, &off) == 3) {
    int h = -1; for (int i = 0; i < H_MAX; i++) if (!strcmp(hook, hook_names[i])) h = i;
    if (h < 0) continue;
    uintptr_t b = base_of(dso); if (!b) continue; b -= 1;
    if (nlines[h] >= cap[h]) { cap[h] = cap[h] ? cap[h] * 2 : 256; lines[h] = realloc(lines[h], cap[h] * sizeof(uintptr_t)); }
    lines[h][nlines[h]++] = b + off;
  }
  fclose(f);
  if (getenv("WARMUP_VERBOSE")) { fprintf(stderr, "warmup: dsos=%d", ndso); for (int i = 0; i < H_MAX; i++) fprintf(stderr, " %s=%d", hook_names[i], nlines[i]); fprintf(stderr, " N=%d min=%ld\n", burst_n, min_cycles); }
}
static inline void pf(uintptr_t a) {
#ifdef NOPTWIN
  __asm__ volatile("nopl (%0)" :: "r"(a));
#else
  __asm__ volatile("prefetcht1 (%0)" :: "r"(a));
#endif
}
static inline void warm(int h, uint64_t dt) {
  stat_calls[h]++;
  if (dt < (uint64_t)min_cycles) return;
  stat_warm[h]++;
  int hh = nlines[h] ? h : H_ANY; int n = nlines[hh] < burst_n ? nlines[hh] : burst_n;
  uintptr_t *L = lines[hh];
  if (pace > 0) {
    for (int i = 0; i < n; i++) { pf(L[i]); if ((i & 31) == 31) for (int k = 0; k < pace; k++) __builtin_ia32_pause(); }
  } else {
    for (int i = 0; i < n; i++) pf(L[i]);
  }
  if (stage_n > 0 && nlines[hh] > n) {  /* second stage after a short pause: lines n..n+stage_n */
    for (int k = 0; k < 64; k++) __builtin_ia32_pause();
    int m = nlines[hh] - n < stage_n ? nlines[hh] - n : stage_n;
    for (int i = 0; i < m; i++) pf(L[n + i]);
  }
}
__attribute__((destructor)) static void fini(void) {
  if (!getenv("WARMUP_VERBOSE")) return;
  for (int i = 0; i < H_MAX; i++) if (stat_calls[i]) fprintf(stderr, "warmup: %s calls=%ld warm=%ld\n", hook_names[i], stat_calls[i], stat_warm[i]);
}
#define WRAP(ret, name, hook, params, args) \
  ret name params { static ret (*real) params; if (!real) real = dlsym(RTLD_NEXT, #name); \
    uint64_t t0 = __rdtsc(); ret r = real args; warm(hook, __rdtsc() - t0); return r; }
WRAP(ssize_t, recv, H_RECV, (int fd, void *buf, size_t len, int flags), (fd, buf, len, flags))
WRAP(ssize_t, recvfrom, H_RECV, (int fd, void *buf, size_t len, int flags, struct sockaddr *a, socklen_t *al), (fd, buf, len, flags, a, al))
#ifdef WITH_READ
WRAP(ssize_t, read, H_READ, (int fd, void *buf, size_t len), (fd, buf, len))
WRAP(ssize_t, readv, H_READ, (int fd, const struct iovec *iov, int cnt), (fd, iov, cnt))
#endif
WRAP(int, poll, H_POLL, (struct pollfd *fds, nfds_t n, int timeout), (fds, n, timeout))
WRAP(int, epoll_wait, H_EPOLL, (int ep, struct epoll_event *ev, int max, int timeout), (ep, ev, max, timeout))
#ifdef WITH_FSYNC
#include <unistd.h>
WRAP(int, fsync, H_POLL, (int fd), (fd))
WRAP(int, fdatasync, H_POLL, (int fd), (fd))
WRAP(ssize_t, pwrite, H_POLL, (int fd, const void *buf, size_t n, off_t off), (fd, buf, n, off))
WRAP(ssize_t, pread, H_READ, (int fd, void *buf, size_t n, off_t off), (fd, buf, n, off))
#endif
#ifdef WITH_COND
WRAP(int, pthread_cond_wait, H_COND, (pthread_cond_t *c, pthread_mutex_t *m), (c, m))
WRAP(int, pthread_cond_timedwait, H_COND, (pthread_cond_t *c, pthread_mutex_t *m, const struct timespec *t), (c, m, t))
#endif
