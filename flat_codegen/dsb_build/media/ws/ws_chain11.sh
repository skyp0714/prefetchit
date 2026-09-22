#!/usr/bin/env bash
# Round 11 (after round 10): PEBS data-miss sample, then arms: p11a = p6c + post-call sites (run starts), pstat = trace-free static plan.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q "WS_CHAIN10_DONE" $WS/logs/chain10.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] PEBS data sample on wsm"; bash $WS/ws_pebs_data.sh wsm $WS/pebs_wsm 64 10 2>&1 | tail -3
for arm in p11a pstat; do
  [[ -s $WS/plan_$arm.json ]] || { echo "no plan for $arm"; continue; }
  echo "[$(date +%T)] deps+service build $arm"
  cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_$arm.log 2>&1; tail -1 $WS/logs/deps_$arm.log
  STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $arm dsb-deps-tmp "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_$arm.json" 2>&1 | tail -1
  echo "$arm prefetcht1 in exe: $(objdump -d $DB/out_mid_$arm/MovieIdService 2>/dev/null | grep -c prefetcht1); after_call_missing: $(grep -o 'after_call_missing=[0-9]*' $DB/out_mid_$arm/build.log $WS/logs/deps_$arm.log | awk -F= '{s+=$2} END {print s+0}')"
  if [[ -f $DB/out_mid_$arm/MovieIdService.nop ]]; then rm -rf $DB/out_mid_${arm}nop && mkdir -p $DB/out_mid_${arm}nop && cp -p $DB/out_mid_$arm/MovieIdService.nop $DB/out_mid_${arm}nop/MovieIdService; [[ -d $DB/libs_mid_${arm}nop ]] || cp -a $DB/libs_mid_$arm $DB/libs_mid_${arm}nop; fi
  docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1
done
ARMS="base=wsm p6c=p6c"; for a in p11a p11anop pstat pstatnop; do [[ -x $DB/out_mid_$a/MovieIdService ]] && ARMS="$ARMS $a=$a"; done
echo "[$(date +%T)] A/B round 11: $ARMS"
timeout 7200 bash $WS/ws_ab.sh $WS/ab11 $REPS $ARMS 2>&1 | tail -14
echo "[$(date +%T)] WS_CHAIN11_DONE"
