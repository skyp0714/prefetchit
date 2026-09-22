#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; S=$R/dcperf_v2_batch.sh
timeout 1500 bash $S xsbench 8-11 20 60 -i '{"thread_cnt": "4"}'
timeout 1500 bash $S liblinear_synthetic 8-11 20 60
timeout 900 bash $S syscall_single_core 8-11 15 40
timeout 900 bash $S schbench_default 8-11 10 30
echo "[$(date +%T)] V2_BATCH_DONE"
