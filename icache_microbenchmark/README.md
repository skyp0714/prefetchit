# icache_microbenchmark — stage 1: when does an instruction prefetch actually land?

Microbenchmark for Xeon 6787P (Granite Rapids) isolating prefetch instruction
behaviour on code addresses: `prefetcht0/t1` vs `prefetchit0/1`, TLB-warmth
gating, and prefetch placement inside a branch window.

Key findings that shaped the project:

- `prefetchit0/1` does not warm the iTLB/STLB and, on this CPU, does not move
  L1I/L2I miss counts (later confirmed on tomcat/cassandra with the C2 patch);
  the data-prefetch variants do — hence `prefetcht1` for code everywhere else.
- Prefetches issued too close to the miss (inside the branch window) are
  dropped/ineffective; lead time must be ≫ one branch.

## Build / run

```bash
make -C microbench/src all prefetch_test icache_flush_dummy      # clang, -march=graniterapids
sudo ./set_perf_cpus.sh 0-3                                      # or scripts/platform/freeze_platform.sh
cd microbench/src
sudo python3 run_process_prefetch_experiment.py                  # sweep, writes CSV
python3 run_prefetch_stats.py --help
```

Experiment log with the raw observations: `microbench/prefetch_test_experiment_log.md`.
