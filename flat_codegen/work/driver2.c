#include <stdlib.h>
#include <stdio.h>
extern void TestHarness_eval(void *);
int main(int argc, char **argv) {
  long n = argc > 1 ? atol(argv[1]) : 10000;
  unsigned char *st = calloc(1, 1199257 + 64);
  st[1] = 1; /* reset high */
  for (int i = 0; i < 20; i++) { st[0] = 1; TestHarness_eval(st); st[0] = 0; TestHarness_eval(st); }
  st[1] = 0; /* release reset */
  for (long i = 0; i < n; i++) { st[0] = 1; TestHarness_eval(st); st[0] = 0; TestHarness_eval(st); }
  printf("cycles=%ld\n", n);
  return 0;
}
