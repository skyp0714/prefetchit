#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CDN4_DONE $R/logs/chain_cdn4.log 2>/dev/null; do sleep 60; done
CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh; echo "[$(date +%T)] CDN5_DONE"
