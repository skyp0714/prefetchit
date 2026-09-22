#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q SN2_CHAIN_DONE $R/logs/chain_sn2.log 2>/dev/null; do sleep 60; done
echo "[$(date +%T)] data-caching (fixed, rerun)"; CORES=4-7 $R/cloudsuite_dc2.sh $R/cloudsuite_4core.csv 2>&1 | grep -vE "^\s*$" | cut -c1-220
echo "[$(date +%T)] CS5_CHAIN_DONE"
