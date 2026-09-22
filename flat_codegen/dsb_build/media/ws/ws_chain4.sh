#!/usr/bin/env bash
# Round 4: static archives (thrift/jaeger/opentracing/yaml/mongoc/bson/hiredis/redis++) rebuilt WITH the pass and the plan, so that
# library functions on the run path can host bursts too (plan_pass3: sites in service objects + archives). Then wsp3 vs base vs twin.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q -E "WS_CHAIN3_DONE|WS_CHAIN3_FAILED" $WS/logs/chain3.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] rebuild deps with the plan -> image dsb-deps-ws3"
cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_pass3.json" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-ws3 - > $WS/logs/deps_ws3.log 2>&1; tail -2 $WS/logs/deps_ws3.log
docker image inspect dsb-deps-ws3 > /dev/null 2>&1 || { echo "deps image missing"; echo "[$(date +%T)] WS_CHAIN4_FAILED"; exit 1; }
echo "[$(date +%T)] build wsp3"
STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh wsp3 dsb-deps-ws3 "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_pass3.json" 2>&1 | tail -3
n=$(objdump -d $DB/out_mid_wsp3/MovieIdService | grep -c prefetcht1); echo "wsp3 prefetcht1 in exe: $n"
[[ -f $DB/out_mid_wsp3/MovieIdService.nop ]] || { echo "no twin built"; echo "[$(date +%T)] WS_CHAIN4_FAILED"; exit 1; }
rm -rf $DB/out_mid_wsp3nop && mkdir -p $DB/out_mid_wsp3nop && cp -p $DB/out_mid_wsp3/MovieIdService.nop $DB/out_mid_wsp3nop/MovieIdService; [[ -d $DB/libs_mid_wsp3nop ]] || cp -a $DB/libs_mid_wsp3 $DB/libs_mid_wsp3nop
echo "[$(date +%T)] A/B round 4"
timeout 5400 bash $WS/ws_ab.sh $WS/ab4 $REPS base=wsm wsp3=wsp3 wsp3nop=wsp3nop wsp2=wsp2 2>&1 | tail -16
echo "[$(date +%T)] WS_CHAIN4_DONE"
