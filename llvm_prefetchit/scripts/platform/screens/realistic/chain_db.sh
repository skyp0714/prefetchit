#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink
until grep -q CHAIN_REAL2_DONE $PL/logs/chain_real2.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] PG screen"; CORES=4-7 $R/pg_realistic_screen.sh $R/db_4core.csv 2>&1 | grep -E "^pg |DONE"
echo "[$(date +%T)] DB_CHAIN_DONE"
