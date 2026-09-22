#!/usr/bin/env bash
# Round 8: stage-0 add-on (LD_PRELOAD wake replay, N0 lines at each wake using the next-run queue set by the marks) on top of the best
# pass arm. Needs a PT trace of that binary (layout-specific lists). Waits for round 7.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}; BEST=${BEST:-p6a}
until grep -q "WS_CHAIN9_DONE" $WS/logs/chain9.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] stage-0 lists for $BEST"
bash $WS/ws_stage0.sh $BEST 0.1 2>&1 | tail -14
[[ -s $WS/plan_$BEST.list ]] || { echo "no list"; echo "[$(date +%T)] WS_CHAIN8_FAILED"; exit 1; }
echo "[$(date +%T)] A/B round 8"
timeout 7200 bash $WS/ws_ab.sh $WS/ab8 $REPS base=wsm p6c=p6c $BEST=$BEST ${BEST}s16=$BEST:$WS/libws2.so:$WS/plan_$BEST.list:16:8 ${BEST}s32=$BEST:$WS/libws2.so:$WS/plan_$BEST.list:32:8 ${BEST}s16nop=$BEST:$WS/libws2_nop.so:$WS/plan_$BEST.list:16:8 2>&1 | tail -14
echo "[$(date +%T)] WS_CHAIN8_DONE"
