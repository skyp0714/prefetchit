#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; S=$R/dcperf_v2_batch.sh
until grep -q XS_CDN_DONE $R/logs/chain_xs_cdn.log 2>/dev/null; do sleep 60; done
JY=jobs_mem.yml BY=benchmarks_mem.yml timeout 2400 bash $S gapbs_bc 8-11 30 90 -i '{"scale": "22", "trials": "3"}'
timeout 1800 bash $S graph500_omp_csr 8-11 30 90
echo "[$(date +%T)] GAP_DONE"
