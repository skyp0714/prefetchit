#!/usr/bin/env bash
# Round 39: closing the loop against the original shared-library build — g (clang-19 rebuild, shared libs) vs gs vs the best plan (cold14), 3 reps.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD24_DONE logs/chain_cold24.log 2>/dev/null; do sleep 15; done
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g
ARMS="g=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g:-:-:64:0:20000:0 gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold14=$DB/out_utl_cold14:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round39 arms: $ARMS"; rm -rf results/round39; ./dsb_warm_ab2.sh results/round39 3 $ARMS > logs/round39.log 2>&1
python3 summarize_ab.py results/round39/runs.csv g 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] CHAIN_COLD25_DONE"
