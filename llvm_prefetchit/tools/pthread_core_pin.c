#define _GNU_SOURCE

#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum { MAX_PIN_CORES = CPU_SETSIZE };

struct pinned_start {
    void *(*start_routine)(void *);
    void *argument;
    int core;
    size_t core_index;
};

static int pin_cores[MAX_PIN_CORES];
static unsigned char pin_core_in_use[MAX_PIN_CORES];
static size_t pin_core_count;
static pthread_mutex_t pin_core_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t init_once = PTHREAD_ONCE_INIT;
static int pin_after_fork;
static int pin_enabled = 1;
static int (*real_pthread_create)(pthread_t *, const pthread_attr_t *,
                                  void *(*)(void *), void *);

static void reset_after_fork(void) {
    memset(pin_core_in_use, 0, sizeof(pin_core_in_use));
    pin_core_lock = (pthread_mutex_t)PTHREAD_MUTEX_INITIALIZER;
    pin_enabled = 1;
}

static void parse_core_list(const char *spec) {
    char *copy = strdup(spec);
    char *save = NULL;
    char *part = NULL;

    if (copy == NULL) {
        return;
    }
    for (part = strtok_r(copy, ",", &save); part != NULL;
         part = strtok_r(NULL, ",", &save)) {
        char *dash = strchr(part, '-');
        char *end = NULL;
        long first = strtol(part, &end, 10);
        long last = first;
        if (end == part) {
            continue;
        }
        if (dash != NULL) {
            last = strtol(dash + 1, &end, 10);
        }
        if (first < 0 || last < first || last >= CPU_SETSIZE) {
            continue;
        }
        for (long core = first;
             core <= last && pin_core_count < MAX_PIN_CORES; ++core) {
            pin_cores[pin_core_count++] = (int)core;
        }
    }
    free(copy);
}

static void initialize(void) {
    const char *spec = getenv("PREFETCHIT_THREAD_PIN_CORES");
    const char *after_fork = getenv("PREFETCHIT_THREAD_PIN_AFTER_FORK");
    *(void **)(&real_pthread_create) = dlsym(RTLD_NEXT, "pthread_create");
    pin_after_fork = after_fork != NULL && strcmp(after_fork, "0") != 0;
    if (pin_after_fork) {
        pin_enabled = 0;
    }
    pthread_atfork(NULL, NULL, reset_after_fork);
    if (spec != NULL && *spec != '\0') {
        parse_core_list(spec);
    }
}

static size_t reserve_core(void) {
    size_t index = MAX_PIN_CORES;
    pthread_mutex_lock(&pin_core_lock);
    for (size_t i = 0; i < pin_core_count; ++i) {
        if (!pin_core_in_use[i]) {
            pin_core_in_use[i] = 1;
            index = i;
            break;
        }
    }
    pthread_mutex_unlock(&pin_core_lock);
    return index;
}

static void release_start(void *opaque) {
    struct pinned_start *start = opaque;
    pthread_mutex_lock(&pin_core_lock);
    pin_core_in_use[start->core_index] = 0;
    pthread_mutex_unlock(&pin_core_lock);
    free(start);
}

static void *run_pinned(void *opaque) {
    struct pinned_start *start = opaque;
    void *(*start_routine)(void *) = start->start_routine;
    void *argument = start->argument;
    void *result;
    cpu_set_t mask;

    CPU_ZERO(&mask);
    CPU_SET(start->core, &mask);
    if (sched_setaffinity(0, sizeof(mask), &mask) != 0) {
        _exit(126);
    }
    pthread_cleanup_push(release_start, start);
    result = start_routine(argument);
    pthread_cleanup_pop(1);
    return result;
}

int pthread_create(pthread_t *thread, const pthread_attr_t *attr,
                   void *(*start_routine)(void *), void *argument) {
    struct pinned_start *start;
    pthread_attr_t pinned_attr;
    const pthread_attr_t *create_attr = attr;
    int has_pinned_attr = 0;
    size_t index;

    pthread_once(&init_once, initialize);
    if (real_pthread_create == NULL) {
        return ENOSYS;
    }
    if (pin_core_count == 0 || !pin_enabled) {
        return real_pthread_create(thread, attr, start_routine, argument);
    }
    index = reserve_core();
    if (index >= pin_core_count) {
        return EAGAIN;
    }
    start = malloc(sizeof(*start));
    if (start == NULL) {
        pthread_mutex_lock(&pin_core_lock);
        pin_core_in_use[index] = 0;
        pthread_mutex_unlock(&pin_core_lock);
        return ENOMEM;
    }
    start->start_routine = start_routine;
    start->argument = argument;
    start->core = pin_cores[index];
    start->core_index = index;
    if (attr == NULL) {
        cpu_set_t mask;
        CPU_ZERO(&mask);
        CPU_SET(start->core, &mask);
        if (pthread_attr_init(&pinned_attr) == 0) {
            if (pthread_attr_setaffinity_np(&pinned_attr, sizeof(mask), &mask) == 0) {
                create_attr = &pinned_attr;
                has_pinned_attr = 1;
            } else {
                pthread_attr_destroy(&pinned_attr);
            }
        }
    }
    int rc = real_pthread_create(thread, create_attr, run_pinned, start);
    if (has_pinned_attr) {
        pthread_attr_destroy(&pinned_attr);
    }
    if (rc != 0) {
        release_start(start);
    }
    return rc;
}
