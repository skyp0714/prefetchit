#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CS2_CHAIN_DONE $R/logs/chain_cs2.log 2>/dev/null; do sleep 30; done
echo "[$(date +%T)] web-serving (fixed)"; CORES=4-7 $R/cloudsuite_ws2.sh $R/cloudsuite_4core.csv 2>&1 | grep -vE "^\s*$" | cut -c1-220
echo "[$(date +%T)] CS3_CHAIN_DONE"
