#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
bash $R/cdn_relink3.sh > $R/logs/cdn_relink3.log 2>&1
until grep -q GAP2_DONE $R/logs/chain_v2_gap2.log 2>/dev/null; do sleep 60; done
grep -q "test rc=124" $R/logs/cdn_relink3.log || { echo "content_server still broken; skip"; echo "[$(date +%T)] CDN3_DONE"; exit 0; }
CORES=8-11 timeout 2400 bash $R/cdn_bench_screen.sh; echo "[$(date +%T)] CDN3_DONE"
