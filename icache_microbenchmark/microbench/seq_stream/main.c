#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
extern void stream_fn(unsigned char *state);
int main(int argc, char **argv) {
  int reps = argc > 1 ? atoi(argv[1]) : 20;
  size_t data_mb = getenv("DATA_MB") ? (size_t)atof(getenv("DATA_MB")) : 0;
  size_t bytes = (data_mb ? data_mb << 20 : 0) + (1 << 20);
  unsigned char *state = aligned_alloc(4096, bytes);
  memset(state, 0x5a, bytes);
  struct timespec t0, t1;
  stream_fn(state); /* warm data, page in code */
  clock_gettime(CLOCK_MONOTONIC, &t0);
  for (int i = 0; i < reps; i++) stream_fn(state);
  clock_gettime(CLOCK_MONOTONIC, &t1);
  double s = (t1.tv_sec - t0.tv_sec) + 1e-9 * (t1.tv_nsec - t0.tv_nsec);
  printf("reps=%d sec=%.4f sec_per_rep=%.5f state0=%u\n", reps, s, s / reps, state[0x100]);
  return 0;
}
