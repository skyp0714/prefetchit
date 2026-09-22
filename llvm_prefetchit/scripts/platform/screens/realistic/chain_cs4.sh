#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CS3_CHAIN_DONE $R/logs/chain_cs3.log 2>/dev/null; do sleep 30; done
for b in web-search data-serving; do echo "[$(date +%T)] $b (fixed)"; CORES=4-7 $R/cloudsuite_fix2.sh $R/cloudsuite_4core.csv $b 2>&1 | grep -vE "^\s*$" | cut -c1-220; done
echo "[$(date +%T)] CS4_CHAIN_DONE"
