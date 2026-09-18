#!/usr/bin/env bash
# After round 20: counter decomposition g vs gs vs cold3 (why does fat-static gain?), 2 reps.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD4_DONE logs/chain_cold4.log 2>/dev/null; do sleep 15; done
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35
echo "[$(date +%T)] counters"; ./cold_counters.sh results/counters_cold 2 g=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g cold3=$DB/out_utl_cold3:$DB/libs_utl_g:dsb-deps-g > logs/counters_cold.log 2>&1
grep -E " r[0-9]:" logs/counters_cold.log | cut -c1-220; echo "[$(date +%T)] CHAIN_COLD5_DONE"
