#!/usr/bin/env bash
# Utilization sweeps of user-timeline (fat-static base) on 1 core and on 2 cores, read-only load.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; cd $PL
echo "[$(date +%T)] 1 core"; CORES=36 NC=1 ./utl_load_sweep.sh results/sweep_1core 2000 3000 4000 4500 5000 5500 6000 2>&1 | grep -E "^R=|saturated"
echo "[$(date +%T)] 2 cores"; CORES=36-37 NC=2 ./utl_load_sweep.sh results/sweep_2core 5000 6000 7000 8000 9000 2>&1 | grep -E "^R=|saturated"
echo "[$(date +%T)] SWEEP12_DONE"
