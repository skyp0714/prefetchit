#!/usr/bin/env bash
# Round 3: plan restricted to instrumentable sites (consistent offset shifts), wider window (dmax 32, k 8): arm wsp2 vs base vs twin.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q -E "WS_CHAIN2_DONE|WS_CHAIN2_FAILED" $WS/logs/chain2.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] build wsp2"
cd $DB && STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh wsp2 dsb-deps-jammy "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_pass2.json" 2>&1 | tail -3
n=$(objdump -d $DB/out_mid_wsp2/MovieIdService | grep -c prefetcht1); echo "wsp2 prefetcht1 in exe: $n"
[[ -f $DB/out_mid_wsp2/MovieIdService.nop ]] || { echo "no twin built"; echo "[$(date +%T)] WS_CHAIN3_FAILED"; exit 1; }
rm -rf $DB/out_mid_wsp2nop && mkdir -p $DB/out_mid_wsp2nop && cp -p $DB/out_mid_wsp2/MovieIdService.nop $DB/out_mid_wsp2nop/MovieIdService; [[ -d $DB/libs_mid_wsp2nop ]] || cp -a $DB/libs_mid_wsp2 $DB/libs_mid_wsp2nop
echo "[$(date +%T)] A/B round 3"
timeout 5400 bash $WS/ws_ab.sh $WS/ab3 $REPS base=wsm wsp2=wsp2 wsp2nop=wsp2nop 2>&1 | tail -14
echo "[$(date +%T)] WS_CHAIN3_DONE"
