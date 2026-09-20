#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; cd $V
echo "[$(date +%T)] xsbench manual install"; taskset -c 12-35 timeout 1200 bash packages/xsbench/install_xsbench.sh > $R/logs/v2_install_xsbench_manual.log 2>&1; echo "  exit=$?"; ls benchmarks/xsbench 2>&1 | head -3
JY=jobs_mem.yml BY=benchmarks_mem.yml timeout 1500 bash $R/dcperf_v2_batch.sh xsbench 8-11 20 60 -i '{"thread_cnt": "4"}'
CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh
echo "[$(date +%T)] XS_CDN_DONE"
