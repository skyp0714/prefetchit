#!/usr/bin/env bash
# Round 13: the pass's plan-free static mode (callee-entry burst at every direct call, archives included) as the second static data point.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q "WS_CHAIN12_DONE" $WS/logs/chain12.log 2>/dev/null; do sleep 20; done
for spec in "pstat2:PREFETCHIT_CALLEE_BURST_LINES=4" "pstat3:PREFETCHIT_CALLEE_BURST_LINES=8"; do
  arm=${spec%%:*}; env=${spec#*:}
  echo "[$(date +%T)] deps+service build $arm ($env)"
  cd $DB && EXTRA_PASS_ENV="$env" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_$arm.log 2>&1; tail -1 $WS/logs/deps_$arm.log
  STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-tmp "$env" 2>&1 | tail -1
  echo "$arm prefetcht1 in exe: $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1)"
  if [[ $arm == pstat2 && -f $DB/out_mid_$arm/MovieIdService.nop ]]; then rm -rf $DB/out_mid_${arm}nop && mkdir -p $DB/out_mid_${arm}nop && cp -p $DB/out_mid_$arm/MovieIdService.nop $DB/out_mid_${arm}nop/MovieIdService; [[ -d $DB/libs_mid_${arm}nop ]] || cp -a $DB/libs_mid_$arm $DB/libs_mid_${arm}nop; fi
  docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1
done
ARMS="base=wsm p11a=p11a"; for a in pstat2 pstat2nop pstat3; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 13: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab13 $REPS $ARMS 2>&1 | tail -10
echo "[$(date +%T)] WS_CHAIN13_DONE"
