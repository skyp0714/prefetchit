#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
until grep -q CSDIAG_DONE $R/logs/chain_csdiag.log 2>/dev/null; do sleep 120; done
grep -v "^data-serving," $R/cloudsuite_4core.csv > $R/cloudsuite_4core.tmp && mv $R/cloudsuite_4core.tmp $R/cloudsuite_4core.csv
echo "[$(date +%T)] data-serving (warm-up fixed)"; CORES=4-7 $R/cloudsuite_fix2.sh $R/cloudsuite_4core.csv data-serving 2>&1 | grep -vE "^\s*$" | cut -c1-200
echo "[$(date +%T)] DS3_DONE"
