#!/usr/bin/env bash
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918
for app in Router SetAlgebra HDSearch; do echo "[$(date +%T)] $app"; CORES=36-39 $R/musuite_realistic_sweep.sh $R/musuite_4core.csv $app 1000 2000 3000 4000 6000 8000 12000 2>&1 | grep -E "qps=|limit|DONE"; done
echo "[$(date +%T)] MUSUITE_CHAIN_DONE"
