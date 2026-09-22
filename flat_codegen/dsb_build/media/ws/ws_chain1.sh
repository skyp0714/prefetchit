#!/usr/bin/env bash
# wake-stream prototype round 1 on movie-id (interleaved, R=600): lists from the wsm PT trace -> A/B of
#   base  = wsm binary, no preload
#   ws32  = libws.so, stage-0 N0=32 + marks QM=32
#   ws64  = libws.so, N0=64, QM=32
#   nop   = libws_nop.so with N0=64/QM=32 (same instruction stream, prefetches replaced by NOPs)
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}
REPS=${REPS:-3}; TR=${TR:-$WS/pt6}
python3 $WS/ws_lists.py $TR/runs $WS/plan_wsm.list --p-min ${PMIN:-0.5} ${PAIR:+--pair} --auto-sites $WS/marks_wsm.txt --next $TR/runs/next.tsv 2>&1 | tail -20
grep -c "^L" $WS/plan_wsm.list; grep -E "^[SN]" $WS/plan_wsm.list
timeout 5400 bash $WS/ws_ab.sh $WS/ab1 $REPS base=wsm ws32=wsm:$WS/libws.so:$WS/plan_wsm.list:32:32 ws64=wsm:$WS/libws.so:$WS/plan_wsm.list:64:32 nop=wsm:$WS/libws_nop.so:$WS/plan_wsm.list:64:32 2>&1 | tail -20
echo "[$(date +%T)] WS_CHAIN1_DONE"
