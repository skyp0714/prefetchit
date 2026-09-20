#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2
until grep -q V2_ADSIM7_DONE $R/logs/chain_v2_adsim7.log 2>/dev/null; do sleep 60; done
[[ -x $V/benchmarks/adsim/adsim_server ]] || { echo "adsim_server not built; skip"; ls $V/benchmarks/adsim 2>&1 | head -5; echo "[$(date +%T)] ADSIM_SCREEN_DONE"; exit 0; }
CORES=8-11 timeout 1200 bash $R/adsim_screen.sh; echo "[$(date +%T)] ADSIM_CHAIN_DONE"
