// prefetchi_test.c
// build: gcc -c -mprefetchi -m64 -march=x86-64 -o prefetchi_test.o prefetch_test.c
// check: objdump -dr -Mintel prefetchi_test.o
 #include <x86intrin.h>

void* p;

int bar (int a){
  a = a+1;
 return a+1;
}
int foo (int a){
  a = a+1;
 return a+1;
}
int baz (int a){
  a = a+1;
 return a+1;
}

static inline void prefetch_by_id(int id) {
    switch (id) {
    case 0: __builtin_ia32_prefetchi(foo, 3); break; 
    case 1: __builtin_ia32_prefetchi(bar, 3); break;
    case 2: __builtin_ia32_prefetchi(baz, 3); break;
    default: break;
    }
}

void t0(void);
void t1(void);
void t2(void);

static void prefetch_t0(void){ __builtin_ia32_prefetchi(t0, 3); }
static void prefetch_t1(void){ __builtin_ia32_prefetchi(t1, 3); }
static void prefetch_t2(void){ __builtin_ia32_prefetchi(t2, 3); }

int (* const kAllTasks[])(int) = { bar, bar+1, bar+2 };

void run_prefetch() {
  for (int i = 0; i < 50; ++i) {
    if (i%2 == 0)
      __builtin_ia32_prefetchi(kAllTasks[i%3], 3);
  }
}

int main() {
  __builtin_ia32_prefetchi(kAllTasks[0], 3);
  void * a = &bar;
  __builtin_ia32_prefetchi(a, 3);

  for (int i = 0; i < 3; ++i) {
    __builtin_ia32_prefetchi(kAllTasks[i], 3);
  }

  run_prefetch();
  return 0;
}


    // static void* next_target = NULL;
//works
  // __builtin_ia32_prefetchi (p, 3);   //don't work
  // next_target = (void*)bar;
  // __builtin_ia32_prefetchi (next_target, 3);   //don't work