#!/usr/bin/env bash
# Round 7: prefetchit1 vs prefetcht1 on the same direct-only plan (GOT/register forms of prefetchit are NOPs, so library lines are dropped
# from both arms). BEST = the best round-6 arm, re-measured in-round. Waits for round 6.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}; BEST=${BEST:-p6a}
until grep -q "WS_CHAIN6_DONE" $WS/logs/chain6.log 2>/dev/null; do sleep 15; done
for arm in p7t p7i; do
  MN=prefetcht1; [[ $arm == p7i ]] && MN=prefetchit1
  echo "[$(date +%T)] deps+service build $arm ($MN)"
  cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_p7d.json PREFETCHIT_SEQ_MNEMONIC=$MN" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_$arm.log 2>&1; tail -1 $WS/logs/deps_$arm.log
  STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-tmp "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_p7d.json PREFETCHIT_SEQ_MNEMONIC=$MN" 2>&1 | tail -1
  echo "$arm: prefetcht1 $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1) prefetchit1 $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetchit1)"
  docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1
done
ARMS="base=wsm $BEST=$BEST"; for a in p7t p7i; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 7: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab7 $REPS $ARMS 2>&1 | tail -12
echo "[$(date +%T)] WS_CHAIN7_DONE"
