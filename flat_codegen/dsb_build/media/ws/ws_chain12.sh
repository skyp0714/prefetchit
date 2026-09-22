#!/usr/bin/env bash
# Final confirmation: 5 interleaved reps of base / wsp3 / p6c (and p11a if it exists and is not worse) — the numbers to report.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}
until grep -q "WS_CHAIN11_DONE" $WS/logs/chain11.log 2>/dev/null; do sleep 20; done
ARMS="base=wsm wsp3=wsp3 p6c=p6c"; [[ -x $DB/out_mid_p11a/MovieIdService ]] && ARMS="$ARMS p11a=p11a"; [[ -x $DB/out_mid_pstat/MovieIdService ]] && ARMS="$ARMS pstat=pstat"
echo "[$(date +%T)] final 5-rep A/B: $ARMS"
timeout 9000 bash $WS/ws_ab.sh $WS/ab12 5 $ARMS 2>&1 | tail -10
echo "[$(date +%T)] WS_CHAIN12_DONE"
