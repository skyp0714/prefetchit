#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CDN2_REBUILT $R/logs/cdn_relink2.log 2>/dev/null && grep -q XS2_DONE $R/logs/chain_v2_xs2.log 2>/dev/null; do sleep 60; done
grep -q "test rc=124" $R/logs/cdn_relink2.log || { echo "content_server still broken; skip"; echo "[$(date +%T)] CDN2_DONE"; exit 0; }
CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh; echo "[$(date +%T)] CDN2_DONE"
