#!/usr/bin/env bash
# Round 6: the coverage improvements WITHOUT 128 B pairing (labels for markless runs, gap filler), d=8 vs d=12 lines.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q "WS_CHAIN5_DONE" $WS/logs/chain5.log 2>/dev/null; do sleep 15; done
for arm in p6a p6b p6c; do
  echo "[$(date +%T)] deps+service build $arm"
  cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_$arm.log 2>&1; tail -1 $WS/logs/deps_$arm.log
  STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-tmp "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" 2>&1 | tail -1
  n=$(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1); echo "$arm prefetcht1 in exe: $n"
  if [[ $arm == p6a && -f $DB/out_mid_$arm/MovieIdService.nop ]]; then rm -rf $DB/out_mid_${arm}nop && mkdir -p $DB/out_mid_${arm}nop && cp -p $DB/out_mid_$arm/MovieIdService.nop $DB/out_mid_${arm}nop/MovieIdService; [[ -d $DB/libs_mid_${arm}nop ]] || cp -a $DB/libs_mid_$arm $DB/libs_mid_${arm}nop; fi
  docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1
done
ARMS="base=wsm wsp3=wsp3"; for a in p6a p6anop p6b p6c; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 6: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab6 $REPS $ARMS 2>&1 | tail -16
echo "[$(date +%T)] WS_CHAIN6_DONE"
