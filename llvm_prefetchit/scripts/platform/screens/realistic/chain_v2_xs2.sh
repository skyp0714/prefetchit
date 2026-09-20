#!/usr/bin/env bash
# xsbench rerun with a 10x longer history so the run outlives the measurement windows (default 500k lookups ends in ~10 s).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q GAP_DONE $R/logs/chain_v2_gap.log 2>/dev/null; do sleep 60; done
JY=jobs_mem.yml BY=benchmarks_mem.yml timeout 1800 bash $R/dcperf_v2_batch.sh xsbench 8-11 20 60 -i '{"thread_cnt": "4", "history": "5000000"}'
echo "[$(date +%T)] XS2_DONE"
