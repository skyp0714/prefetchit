#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CS3_CHAIN_DONE $R/logs/chain_cs3.log 2>/dev/null && grep -q JVM2_DONE $R/logs/chain_jvm2.log 2>/dev/null && grep -q DCPERF_INSTALL_DONE $R/logs/dcperf_install_chain.log 2>/dev/null && grep -q MUSUITE_CHAIN_DONE $R/logs/chain_musuite.log 2>/dev/null; do sleep 30; done
for c in $(docker ps --format '{{.Names}}'); do docker update --cpuset-cpus 0-85 $c > /dev/null 2>&1; done
$R/dcperf_runs.sh 2>&1 | grep -vE "^\s*$"
echo "[$(date +%T)] DCPERF_CHAIN_DONE"
