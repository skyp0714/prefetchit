#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q DS3_DONE $R/logs/chain_ds3.log 2>/dev/null; do sleep 120; done
for c in $(docker ps --format '{{.Names}}'); do docker update --cpuset-cpus 0-85 $c > /dev/null 2>&1; done
$R/dcperf_runs2.sh 2>&1 | grep -vE "^\s*$"
echo "[$(date +%T)] DCPERF2_CHAIN_DONE"
