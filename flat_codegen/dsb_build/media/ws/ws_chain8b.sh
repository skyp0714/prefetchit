#!/usr/bin/env bash
# Round 8 (retry): stage-0 add-on on p9. The first PT capture of p9 was mostly empty (16 MB, 72 runs); retry until the trace holds enough runs.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}; BEST=p9
for attempt in 1 2 3; do
  rm -rf $WS/pt_$BEST; echo "[$(date +%T)] stage-0 trace attempt $attempt"
  bash $WS/ws_stage0.sh $BEST 0.15 2>&1 | grep -E "^runs|^site|^next|STAGE0" | head -24
  n=$(grep -c " => " $WS/pt_$BEST/branches.txt 2>/dev/null || echo 0); echo "branch records: $n"
  [[ $n -ge 600000 ]] && break
done
grep -c "^L" $WS/plan_$BEST.list; grep -E "^[SN]" $WS/plan_$BEST.list | head -20
echo "[$(date +%T)] A/B round 8"
timeout 7200 bash $WS/ws_ab.sh $WS/ab8 $REPS base=wsm p6c=p6c p9=p9 p9s16=p9:$WS/libws2.so:$WS/plan_p9.list:16:8 p9s32=p9:$WS/libws2.so:$WS/plan_p9.list:32:8 p9s16nop=p9:$WS/libws2_nop.so:$WS/plan_p9.list:16:8 2>&1 | tail -14
echo "[$(date +%T)] WS_CHAIN8_DONE"
