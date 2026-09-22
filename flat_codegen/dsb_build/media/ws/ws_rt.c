/* ws_rt.c — wake-stream runtime (LD_PRELOAD). Class-B (interleaving) instruction prefetch for a thrift service.
 *
 * Stage 0: wrappers around the blocking calls (recv/recvfrom/read/readv/poll/epoll_wait[/pthread_cond_*]) measure the call with rdtsc;
 *          if it took longer than WS_MIN_CYCLES the thread slept (the core was reused by a neighbour and our code lines were evicted
 *          from L2). Then the per-hook FIRST-TOUCH list (from run_paths.py on an Intel PT trace of the interleaved regime) is
 *          replayed from index 0: the first WS_N0 lines are issued with prefetcht1 (fill queue limit: 32-48 outstanding).
 * Marks:   the binary may call ws_mark(id) at program points (dispatch of a method, handler steps, sub-RPC returns). A mark
 *          switches to the method-specific list if the site table says so and issues the next WS_QM lines from max(cursor, pos).
 *
 * WS_LIST file format (one entry per line):
 *   L <key> <dso-basename> <elf-vaddr-hex>      ordered first-touch lines of list <key> (keys: recv, poll, futex, ..., recv_UploadMovieId)
 *   S <id> <key|-> <pos>                        site table: mark id -> (list to switch to or '-', position in that list)
 * Env: WS_LIST, WS_N0 (default 32), WS_QM (default 32), WS_MIN_CYCLES (default 20000), WS_VERBOSE.  Build with -DNOPTWIN for the twin. */
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

enum { H_RECV, H_READ, H_POLL, H_EPOLL, H_FUTEX, H_MAX };
static const char *hook_names[H_MAX] = {"recv", "read", "poll", "epoll_wait", "futex"};

struct list { char key[48]; uintptr_t *a; int n, cap; };
static struct list lists[64]; static int nlists;
struct site { int id; int list; int pos; int nq[4]; int nqn; };   /* nq = lists for the next wakes of this thread */
static struct site sites[256]; static int nsites;
static int hook_list[H_MAX]; static int any_list = -1;
static long min_cycles = 20000; static int n0 = 32, qm = 32, verbose = 0;
static long st_calls[H_MAX], st_wakes[H_MAX], st_lines[H_MAX], st_marks, st_mark_lines;

static __thread int cur = -1;      /* current list */
static __thread int cursor = 0;    /* next index not yet issued in cur */
static __thread int nq[4], nqn = 0, nqi = 0;   /* pending next-wake lists */

static char dso_names[64][128]; static uintptr_t dso_base[64]; static int ndso;
static int cb(struct dl_phdr_info *info, size_t sz, void *data) {
  const char *n = info->dlpi_name; if (!n || !*n) n = "MAIN";
  const char *b = strrchr(n, '/'); b = b ? b + 1 : n;
  if (ndso < 64) { strncpy(dso_names[ndso], b, 127); dso_base[ndso] = info->dlpi_addr; ndso++; }
  return 0;
}
static int base_of(const char *dso, uintptr_t *out) {
  if (!strcmp(dso, "MAIN") || !strncmp(dso, "MovieIdService", 14) || !strncmp(dso, "ComposeReviewService", 20) || !strncmp(dso, "UserTimelineService", 19) || !strncmp(dso, "ComposePostService", 18)) { *out = dso_base[0]; return 1; }
  for (int i = 0; i < ndso; i++) if (!strcmp(dso_names[i], dso)) { *out = dso_base[i]; return 1; }
  size_t n = strlen(dso);
  for (int i = 0; i < ndso; i++) { size_t m = strlen(dso_names[i]); size_t k = n < m ? n : m; if (k >= 8 && !strncmp(dso_names[i], dso, k)) { *out = dso_base[i]; return 1; } }
  return 0;
}
static int list_of(const char *key) {
  for (int i = 0; i < nlists; i++) if (!strcmp(lists[i].key, key)) return i;
  if (nlists >= 64) return -1;
  strncpy(lists[nlists].key, key, 47); return nlists++;
}
__attribute__((constructor)) static void init(void) {
  const char *e;
  if ((e = getenv("WS_MIN_CYCLES"))) min_cycles = atol(e);
  if ((e = getenv("WS_N0"))) n0 = atoi(e);
  if ((e = getenv("WS_QM"))) qm = atoi(e);
  verbose = getenv("WS_VERBOSE") != NULL;
  for (int i = 0; i < H_MAX; i++) hook_list[i] = -1;
  dl_iterate_phdr(cb, NULL);
  const char *lf = getenv("WS_LIST"); if (!lf) return;
  FILE *f = fopen(lf, "r"); if (!f) { if (verbose) fprintf(stderr, "ws: cannot open %s\n", lf); return; }
  char kind[4], key[64], dso[128]; unsigned long v; int id, pos, skipped = 0;
  char line[512];
  while (fgets(line, sizeof line, f)) {
    if (sscanf(line, "L %63s %127s %lx", key, dso, &v) == 3) {
      uintptr_t b; if (!base_of(dso, &b)) { skipped++; continue; }
      int li = list_of(key); if (li < 0) continue; struct list *L = &lists[li];
      if (L->n >= L->cap) { L->cap = L->cap ? L->cap * 2 : 512; L->a = realloc(L->a, L->cap * sizeof(uintptr_t)); }
      L->a[L->n++] = b + v;
    } else if (sscanf(line, "S %d %63s %d", &id, key, &pos) == 3) {
      if (nsites < 256) { sites[nsites].id = id; sites[nsites].list = strcmp(key, "-") ? list_of(key) : -1; sites[nsites].pos = pos; sites[nsites].nqn = 0; nsites++; }
    } else if (line[0] == 'N') {   /* N <mark> <key1> [<key2> ...]: lists of the runs that follow this mark on the same thread */
      char *sp = line + 1; id = (int)strtol(sp, &sp, 10); struct site *S = NULL;
      for (int i = 0; i < nsites; i++) if (sites[i].id == id) S = &sites[i];
      if (!S && nsites < 256) { S = &sites[nsites++]; S->id = id; S->list = -1; S->pos = -1; S->nqn = 0; }
      if (S) { char k[64]; int used; while (S->nqn < 4 && sscanf(sp, "%63s%n", k, &used) == 1) { S->nq[S->nqn++] = list_of(k); sp += used; } }
    }
  }
  fclose(f);
  for (int i = 0; i < H_MAX; i++) hook_list[i] = list_of(hook_names[i]);   /* creates empty lists if absent */
  any_list = list_of("any");
  if (verbose) { fprintf(stderr, "ws: dsos=%d lists=%d sites=%d skipped=%d N0=%d QM=%d min=%ld |", ndso, nlists, nsites, skipped, n0, qm, min_cycles);
    for (int i = 0; i < nlists; i++) fprintf(stderr, " %s=%d", lists[i].key, lists[i].n); fprintf(stderr, "\n"); }
}
static inline void pf(uintptr_t a) {
#ifdef NOPTWIN
  __asm__ volatile("nopl (%0)" :: "r"(a));
#else
  __asm__ volatile("prefetcht1 (%0)" :: "r"(a));
#endif
}
static inline int issue(int li, int from, int count) {
  if (li < 0) return 0;
  struct list *L = &lists[li]; int end = from + count; if (end > L->n) end = L->n;
  for (int i = from; i < end; i++) pf(L->a[i]);
  return end > from ? end - from : 0;
}
static inline void wake(int h, uint64_t dt) {
  st_calls[h]++;
  if (dt < (uint64_t)min_cycles) return;
  st_wakes[h]++;
  if (verbose && (st_wakes[h] & 8191) == 0) {   /* periodic stats to stderr (docker logs): the process is killed by SIGTERM, no destructor */
    long w = 0, l = 0; for (int i = 0; i < H_MAX; i++) { w += st_wakes[i]; l += st_lines[i]; }
    fprintf(stderr, "ws: stats wakes=%ld wake_lines=%ld marks=%ld mark_lines=%ld (recv %ld/%ld poll %ld/%ld futex %ld/%ld read %ld/%ld)\n", w, l, st_marks, st_mark_lines,
            st_wakes[H_RECV], st_calls[H_RECV], st_wakes[H_POLL], st_calls[H_POLL], st_wakes[H_FUTEX], st_calls[H_FUTEX], st_wakes[H_READ], st_calls[H_READ]);
  }
  int li = nqi < nqn ? nq[nqi++] : hook_list[h];
  if (li < 0 || lists[li].n == 0) li = any_list;
  cur = li; cursor = issue(li, 0, n0); st_lines[h] += cursor;
}
/* exported for in-binary marks: resolved by the service through dlsym or a weak reference */
void ws_mark(int id) {
  st_marks++;
  for (int i = 0; i < nsites; i++) if (sites[i].id == id) {
    if (sites[i].nqn) { for (int k = 0; k < sites[i].nqn; k++) nq[k] = sites[i].nq[k]; nqn = sites[i].nqn; nqi = 0; }
    if (sites[i].pos < 0) return;
    int li = sites[i].list >= 0 ? sites[i].list : cur; if (li < 0) return;
    if (li != cur) { cur = li; cursor = 0; }
    int from = cursor > sites[i].pos ? cursor : sites[i].pos;
    int n = issue(li, from, qm); if (n) { cursor = from + n; st_mark_lines += n; }
    return;
  }
}
__attribute__((destructor)) static void fini(void) {
  if (!verbose) return;
  for (int i = 0; i < H_MAX; i++) if (st_calls[i]) fprintf(stderr, "ws: %s calls=%ld wakes=%ld lines=%ld\n", hook_names[i], st_calls[i], st_wakes[i], st_lines[i]);
  fprintf(stderr, "ws: marks=%ld mark_lines=%ld\n", st_marks, st_mark_lines);
}
#define WRAP(ret, name, hook, params, args) \
  ret name params { static ret (*real) params; if (!real) real = dlsym(RTLD_NEXT, #name); \
    uint64_t t0 = __rdtsc(); ret r = real args; wake(hook, __rdtsc() - t0); return r; }
WRAP(ssize_t, recv, H_RECV, (int fd, void *buf, size_t len, int flags), (fd, buf, len, flags))
WRAP(ssize_t, recvfrom, H_RECV, (int fd, void *buf, size_t len, int flags, struct sockaddr *a, socklen_t *al), (fd, buf, len, flags, a, al))
WRAP(ssize_t, read, H_READ, (int fd, void *buf, size_t len), (fd, buf, len))
WRAP(ssize_t, readv, H_READ, (int fd, const struct iovec *iov, int cnt), (fd, iov, cnt))
WRAP(int, poll, H_POLL, (struct pollfd *fds, nfds_t n, int timeout), (fds, n, timeout))
WRAP(int, epoll_wait, H_EPOLL, (int ep, struct epoll_event *ev, int max, int timeout), (ep, ev, max, timeout))
#ifdef WITH_COND
/* pthread_cond_wait is a versioned symbol: dlsym(RTLD_NEXT) may return the pre-2.3.2 version and break the server; use dlvsym. */
int pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m) {
  static int (*real)(pthread_cond_t *, pthread_mutex_t *); if (!real) real = dlvsym(RTLD_NEXT, "pthread_cond_wait", "GLIBC_2.3.2");
  uint64_t t0 = __rdtsc(); int r = real(c, m); wake(H_FUTEX, __rdtsc() - t0); return r; }
int pthread_cond_timedwait(pthread_cond_t *c, pthread_mutex_t *m, const struct timespec *t) {
  static int (*real)(pthread_cond_t *, pthread_mutex_t *, const struct timespec *); if (!real) real = dlvsym(RTLD_NEXT, "pthread_cond_timedwait", "GLIBC_2.3.2");
  uint64_t t0 = __rdtsc(); int r = real(c, m, t); wake(H_FUTEX, __rdtsc() - t0); return r; }
#endif
