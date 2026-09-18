#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q DB2_CHAIN_DONE $R/logs/chain_db2.log 2>/dev/null && grep -q DCPERF_INSTALL_DONE $R/logs/dcperf_install_chain.log 2>/dev/null; do sleep 20; done
echo "[$(date +%T)] DSB socialNetwork realistic screen"; $R/dsb_realistic_screen.sh $R/dsb_social.csv 4000 6000 8000 10000 12000 2>&1 | grep -vE "^\s*$"
echo "[$(date +%T)] DSB_CHAIN_DONE"
