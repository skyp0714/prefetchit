#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q DB_CHAIN_DONE $R/logs/chain_db.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] MariaDB screen"; CORES=4-7 $R/mariadb_realistic_screen.sh $R/db_4core.csv 2>&1 | grep -E "^mariadb |DONE"
echo "[$(date +%T)] DB2_CHAIN_DONE"
