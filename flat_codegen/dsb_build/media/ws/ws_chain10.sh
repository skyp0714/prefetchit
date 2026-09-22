#!/usr/bin/env bash
# Round 10: page-touch (ITLB), shadow lines (non-executed fall-through), gap-k 24 (libc stretches) on top of p6c settings.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
for arm in p10a p10b p10c; do
  echo "[$(date +%T)] deps+service build $arm"
  cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_$arm.log 2>&1; tail -1 $WS/logs/deps_$arm.log
  STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-tmp "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" 2>&1 | tail -1
  echo "$arm prefetcht1 in exe: $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1)"
  docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1
done
until grep -q "WS_UP_DONE" $WS/logs/ws_up4.log 2>/dev/null; do sleep 10; done
ARMS="base=wsm p6c=p6c"; for a in p10a p10b p10c; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 10: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab10 $REPS $ARMS 2>&1 | tail -12
echo "[$(date +%T)] WS_CHAIN10_DONE"
