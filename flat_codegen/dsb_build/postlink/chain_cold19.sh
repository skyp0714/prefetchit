#!/usr/bin/env bash
# Round 29b: wake burst (LD_PRELOAD list regenerated for the fat-static layout) on top of the best plan arm and on gs; 3 reps.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD18_DONE logs/chain_cold18.log 2>/dev/null; do sleep 15; done
BEST=$(grep -m1 "best=" logs/chain_cold18.log | sed 's/.*best=\([a-z0-9]*\).*/\1/'); [[ -z $BEST ]] && BEST=cold8
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; WL=/dsb/postlink/warmup
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BEST=$DB/out_utl_$BEST:$L:dsb-deps-g:-:-:64:0:20000:0 ${BEST}w32=$DB/out_utl_$BEST:$L:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:32:0:20000:0 ${BEST}w64=$DB/out_utl_$BEST:$L:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:64:0:20000:0 gsw32=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:32:0:20000:0"
echo "[$(date +%T)] round29b arms (best=$BEST): $ARMS"; ./dsb_warm_ab2.sh results/round29b 3 $ARMS > logs/round29b.log 2>&1
python3 summarize_ab.py results/round29b/runs.csv gs 2>/dev/null | sed -n 3,8p
echo "[$(date +%T)] CHAIN_COLD19_DONE"
