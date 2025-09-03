// prefetchi_test.c
// build: gcc -c -mprefetchi -m64 -march=x86-64 -o prefetchi_test.o prefetch_test.c
// check: objdump -dr -Mintel prefetchi_test.o
 #include <x86intrin.h>

void* p;

int bar (int a){
  a = a+1;
 return a+1;
}
int main() {
foo:   
  __builtin_ia32_prefetchi(bar, 3);
  void * a = &bar;
  __builtin_ia32_prefetchi(a + 512, 3);
  goto foo;
  return 0;
}


    // static void* next_target = NULL;
//works
  // __builtin_ia32_prefetchi (p, 3);   //don't work
  // next_target = (void*)bar;
  // __builtin_ia32_prefetchi (next_target, 3);   //don't work