#!/usr/bin/env bash
# Round 45: the realistic baseline pushed harder — 1 core at 7,000 req/s (~86% util): gs / plan v10 / realistic-trace plan / twin, 3 reps.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_REAL_DONE logs/chain_realistic.log 2>/dev/null; do sleep 15; done
export LUA=$PL/utl_read.lua WRK_URL=http://localhost:8080 CONN=256 R=7000 SHARED_CORES=36; CORES=36
L=$DB/libs_utl_g; S=":-:-:64:0:20000:0"; ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g$S@$CORES cold14=$DB/out_utl_cold14:$L:dsb-deps-g$S@$CORES"
[[ -f $DB/out_utl_cold21/UserTimelineService ]] && ARMS="$ARMS cold21=$DB/out_utl_cold21:$L:dsb-deps-g$S@$CORES cold21_nop=$DB/out_utl_cold21nop:$L:dsb-deps-g$S@$CORES"
echo "[$(date +%T)] round45 arms (1 core, R=7000): $ARMS"; rm -rf results/round45; ./dsb_warm_ab2.sh results/round45 3 $ARMS > logs/round45.log 2>&1
python3 summarize_ab.py results/round45/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_REAL2_DONE"
