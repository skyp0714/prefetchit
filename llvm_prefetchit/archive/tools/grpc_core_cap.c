#define _GNU_SOURCE

#include <dlfcn.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static unsigned configured_cap(void) {
  const char *value = getenv("PREFETCHIT_GRPC_CORE_CAP");
  char *end = NULL;
  unsigned long parsed;

  if (value == NULL || *value == '\0') {
    return 0;
  }
  parsed = strtoul(value, &end, 10);
  if (end == value || *end != '\0' || parsed == 0 || parsed > 1024) {
    fprintf(stderr, "invalid PREFETCHIT_GRPC_CORE_CAP=%s\n", value);
    abort();
  }
  return (unsigned)parsed;
}

unsigned gpr_cpu_num_cores(void) {
  unsigned cap = configured_cap();
  if (cap != 0) {
    return cap;
  }

  typedef unsigned (*gpr_cpu_num_cores_fn)(void);
  static gpr_cpu_num_cores_fn next_fn;
  if (next_fn == NULL) {
    next_fn = (gpr_cpu_num_cores_fn)dlsym(RTLD_NEXT, "gpr_cpu_num_cores");
  }
  if (next_fn == NULL) {
    fprintf(stderr, "could not resolve gpr_cpu_num_cores\n");
    abort();
  }
  return next_fn();
}

unsigned gpr_cpu_current_cpu(void) {
  unsigned cap = configured_cap();
  if (cap != 0) {
    int cpu = sched_getcpu();
    return cpu < 0 ? 0 : (unsigned)cpu % cap;
  }

  typedef unsigned (*gpr_cpu_current_cpu_fn)(void);
  static gpr_cpu_current_cpu_fn next_fn;
  if (next_fn == NULL) {
    next_fn = (gpr_cpu_current_cpu_fn)dlsym(RTLD_NEXT,
                                            "gpr_cpu_current_cpu");
  }
  if (next_fn == NULL) {
    fprintf(stderr, "could not resolve gpr_cpu_current_cpu\n");
    abort();
  }
  return next_fn();
}

long sysconf(int name) {
  unsigned cap = configured_cap();
  if (cap != 0 &&
      (name == _SC_NPROCESSORS_CONF || name == _SC_NPROCESSORS_ONLN)) {
    return (long)cap;
  }

  typedef long (*sysconf_fn)(int);
  static sysconf_fn next_fn;
  if (next_fn == NULL) {
    next_fn = (sysconf_fn)dlsym(RTLD_NEXT, "sysconf");
  }
  if (next_fn == NULL) {
    fprintf(stderr, "could not resolve sysconf\n");
    abort();
  }
  return next_fn(name);
}
