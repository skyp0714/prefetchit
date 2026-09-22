#!/usr/bin/env bash
# Round 2: dense wake-stream via the pass plan (function-entry sites along the PT first-touch order). Waits for round 1 to finish,
# builds arm wsp (= marks source + PREFETCHIT_COLD_PLAN=plan_pass.json), makes the NOP-twin dir, then A/B base=wsm / wsp / wspnop.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
export RATE=${RATE:-600}; REPS=${REPS:-3}
until grep -q "WS_CHAIN1_DONE" $WS/logs/chain1.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] build wsp"
cd $DB && STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh wsp dsb-deps-jammy "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_pass.json" 2>&1 | tail -4
grep -E "prefetchit-cold-plan" $DB/out_mid_wsp/build.log | grep -v "^$" | sort | uniq -c | sort -rn | head -8
n=$(objdump -d $DB/out_mid_wsp/MovieIdService | grep -c prefetcht1); echo "wsp prefetcht1 in exe: $n"
[[ -f $DB/out_mid_wsp/MovieIdService.nop ]] || { echo "no twin built"; echo "[$(date +%T)] WS_CHAIN2_FAILED"; exit 1; }
rm -rf $DB/out_mid_wspnop && mkdir -p $DB/out_mid_wspnop && cp -p $DB/out_mid_wsp/MovieIdService.nop $DB/out_mid_wspnop/MovieIdService && [[ -d $DB/libs_mid_wspnop ]] || cp -a $DB/libs_mid_wsp $DB/libs_mid_wspnop
echo "[$(date +%T)] A/B round 2"
timeout 5400 bash $WS/ws_ab.sh $WS/ab2 $REPS base=wsm wsp=wsp wspnop=wspnop 2>&1 | tail -14
echo "[$(date +%T)] WS_CHAIN2_DONE"
