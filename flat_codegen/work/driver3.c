#include <stdlib.h>
#include <stdio.h>
extern void TestHarness_eval(void *);
extern void TestHarness_clock(void *);
extern void TestHarness_clock_0(void *);
extern void TestHarness_clock_1(void *);
static inline void step(void *st) {
  TestHarness_eval(st);
  TestHarness_clock(st);
  TestHarness_clock_0(st);
  TestHarness_clock_1(st);
}
int main(int argc, char **argv) {
  long n = argc > 1 ? atol(argv[1]) : 10000;
  unsigned char *st = calloc(1, 1199257 + 64);
  st[1] = 1;
  for (int i = 0; i < 50; i++) step(st);
  st[1] = 0;
  for (long i = 0; i < n; i++) step(st);
  printf("cycles=%ld\n", n);
  return 0;
}
