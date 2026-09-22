#!/usr/bin/env bash
# Round 5: coverage (post-mark run labels, 128 B pairs, gap filler), overhead (fall-through skip), lead (d 8 -> 16 pairs).
# Each arm = archives rebuilt with its plan (temporary image, removed after the service build) + service build. Then A/B vs base and wsp3.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
for arm in p5a p5b p5c; do
  echo "[$(date +%T)] deps+service build $arm"
  cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_$arm.log 2>&1; tail -1 $WS/logs/deps_$arm.log
  STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-tmp "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" 2>&1 | tail -2
  n=$(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1); echo "$arm prefetcht1 in exe: $n"
  if [[ $arm == p5a && -f $DB/out_mid_$arm/MovieIdService.nop ]]; then rm -rf $DB/out_mid_${arm}nop && mkdir -p $DB/out_mid_${arm}nop && cp -p $DB/out_mid_$arm/MovieIdService.nop $DB/out_mid_${arm}nop/MovieIdService; [[ -d $DB/libs_mid_${arm}nop ]] || cp -a $DB/libs_mid_$arm $DB/libs_mid_${arm}nop; fi
  docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1; df -h /home | tail -1
done
until grep -q "WS_UP_DONE" $WS/logs/ws_up2.log 2>/dev/null; do sleep 10; done
ARMS="base=wsm wsp3=wsp3"; for a in p5a p5anop p5b p5c; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 5: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab5 $REPS $ARMS 2>&1 | tail -20
echo "[$(date +%T)] WS_CHAIN5_DONE"
