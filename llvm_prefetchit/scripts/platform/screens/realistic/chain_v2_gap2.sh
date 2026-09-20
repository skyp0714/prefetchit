#!/usr/bin/env bash
# gapbs_bc / graph500 reruns at sizes that outlive the measurement windows (scale 22 / 20 ended within 30 s). After the cdn_bench screen.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; S=$R/dcperf_v2_batch.sh
until grep -q CDN2_DONE $R/logs/chain_cdn2.log 2>/dev/null; do sleep 60; done
WIN=15 JY=jobs_mem.yml BY=benchmarks_mem.yml timeout 2400 bash $S gapbs_bc 8-11 15 60 -i '{"scale": "25", "trials": "10"}'
WIN=15 timeout 1800 bash $S graph500_omp_csr 8-11 20 60 -i '{"scale": "24"}'
echo "[$(date +%T)] GAP2_DONE"
