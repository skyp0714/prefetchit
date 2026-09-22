#!/usr/bin/env bash
# Top-up of the final round: 3 more clean reps of the same arms appended to ab12 (reps 2-4 of the first pass were lost to a full disk).
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; export RATE=${RATE:-600}
until grep -q "WS_CHAIN13_DONE" $WS/logs/chain13.log 2>/dev/null; do sleep 20; done
echo "[$(date +%T)] final top-up 3 reps"; timeout 7200 bash $WS/ws_ab.sh $WS/ab12 3 base=wsm wsp3=wsp3 p6c=p6c p11a=p11a pstat=pstat 2>&1 | tail -8
echo "[$(date +%T)] WS_CHAIN14_DONE"
