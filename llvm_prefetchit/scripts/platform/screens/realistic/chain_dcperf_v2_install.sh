#!/usr/bin/env bash
# DCPerf v2 (worktree benchmarks/dcperf_v2 = origin/v2-beta b109b09): install DjangoBench v2, FeedSim v2 (feedsim_dlrm) and TaoBench,
# builds restricted to cores 12-35 (socket 1), after the stack C6-off diagnostic frees 0-42. Non-interactive sudo via the shim.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2
until grep -q STACKDIAG_DONE $R/logs/chain_stackdiag.log 2>/dev/null; do sleep 60; done
cd $V; export PATH=$R/shim:$PATH DEBIAN_FRONTEND=noninteractive
for job in django_workload_default feedsim_dlrm tao_bench_standalone; do
  echo "[$(date +%T)] install $job"; taskset -c 12-35 python3 ./benchpress_cli.py install $job > $R/logs/v2_install_$job.log 2>&1; echo "  exit=$? free=$(df --output=avail -BG / | tail -1)"
  grep -iE "error:|Error [0-9]|FAILED|No such file|not found" $R/logs/v2_install_$job.log | grep -v "^+ " | tail -3 | cut -c1-200
done
cat $V/benchmark_installs.txt 2>/dev/null; echo "[$(date +%T)] V2_INSTALL_DONE"
