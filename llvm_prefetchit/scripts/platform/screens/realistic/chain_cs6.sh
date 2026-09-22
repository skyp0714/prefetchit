#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q DS3_DONE $R/logs/chain_ds3.log 2>/dev/null; do sleep 60; done
sed -i 's/for rps in 100000 200000 400000 700000 1000000; do/for rps in 200000 400000 700000; do/' $R/cloudsuite_dc2.sh
echo "[$(date +%T)] data-caching (bare-wait fixed)"; CORES=4-7 timeout 1500 $R/cloudsuite_dc2.sh $R/cloudsuite_4core.csv 2>&1 | grep -vE "^\s*$" | cut -c1-200
docker rm -f cs-dc-server cs-dc-client > /dev/null 2>&1; echo "[$(date +%T)] CS6_DONE"
