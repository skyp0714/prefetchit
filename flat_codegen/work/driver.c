#include <stdlib.h>
#include <stdio.h>
extern void TestHarness_eval(void *);
int main(int argc, char **argv) {
  long n = argc > 1 ? atol(argv[1]) : 100000;
  void *st = calloc(1, 730833 + 64);
  for (long i = 0; i < n; i++) TestHarness_eval(st);
  printf("cycles=%ld\n", n);
  return 0;
}
