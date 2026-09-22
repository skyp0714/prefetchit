#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CLOUDSUITE_CHAIN_DONE $R/logs/chain_cloudsuite.log 2>/dev/null; do sleep 30; done
echo "[$(date +%T)] data-caching (fixed client)"; CORES=4-7 $R/cloudsuite_dc2.sh $R/cloudsuite_4core.csv 2>&1 | grep -vE "^\s*$" | cut -c1-220
echo "[$(date +%T)] CS2_CHAIN_DONE"
