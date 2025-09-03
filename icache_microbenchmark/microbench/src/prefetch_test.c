// prefetchi_test.c
// build: gcc -c -mprefetchi -m64 -march=x86-64 -o prefetchi_test.o prefetch_test.c
// check: objdump -dr -Mintel prefetchi_test.o
 #include <x86intrin.h>

void* p;

int bar (int a){
    return a+1;
}
int main() {
    static void* next_target = NULL;
  __builtin_ia32_prefetchi(bar, 3);  //works
  __builtin_ia32_prefetchi (p, 3);   //don't work
  next_target = (void*)bar;
  __builtin_ia32_prefetchi (next_target, 3);   //don't work
  return 0;
}