#!/usr/bin/env bash
# Round 38: 5-rep confirmation of the pruned plan v10 (cold14: same miss reduction as v4 at half the instruction overhead).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD23_DONE logs/chain_cold23.log 2>/dev/null; do sleep 15; done
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold14=$DB/out_utl_cold14:$L:dsb-deps-g:-:-:64:0:20000:0 cold14_nop=$DB/out_utl_cold14nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round38 arms: $ARMS"; rm -rf results/round38; ./dsb_warm_ab2.sh results/round38 5 $ARMS > logs/round38.log 2>&1
python3 summarize_ab.py results/round38/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] CHAIN_COLD24_DONE"
