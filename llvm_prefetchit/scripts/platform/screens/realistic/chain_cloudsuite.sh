#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q STACKS_CHAIN_DONE $R/logs/chain_stacks.log 2>/dev/null; do sleep 20; done
for b in data-caching web-serving media-streaming web-search data-serving; do echo "[$(date +%T)] $b"; CORES=4-7 $R/cloudsuite_realistic.sh $R/cloudsuite_4core.csv $b 2>&1 | grep -vE "^\s*$" | cut -c1-200; done
echo "[$(date +%T)] CLOUDSUITE_CHAIN_DONE"
