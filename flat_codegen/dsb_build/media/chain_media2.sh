#!/usr/bin/env bash
# media round 2: the same trace plan and static plan, but with the burst placed at the latest loop-free common dominator of the target
# call sites instead of the function entry, and a fresh stack (round 1 degraded in the last two reps: p99 in seconds, non-2xx).
set -u; source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920; MDB=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_mariadb_20260920
until grep -qE "MARIADB_DONE|MARIADB_BUILD_FAILED" $MDB/logs/chain_mariadb.log 2>/dev/null; do sleep 60; done
PLACE="PREFETCHIT_COLD_PLACEMENT=dominator PREFETCHIT_COLD_PLACE_MIN_LEAD=20 PREFETCHIT_COLD_PLACE_MAX_LEAD=2000"
cd $DB
for a in "p4d|$O/plans/plan_v4.json" "st1d|$O/plans/plan_static.json"; do
  L=${a%%|*}; J=${a#*|}; [[ -s $J ]] || { echo "missing $J"; continue; }
  echo "[$(date +%T)] build $L"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $L dsb-deps-jammy "PREFETCHIT_COLD_PLAN=$J $PLACE" 2>&1 | tail -3
  grep -ho "moved=[0-9]* loop_levels_saved=[0-9]*" $DB/out_${OUTPFX}_$L/build.log | awk -F'[= ]' '{m+=$2; l+=$4} END{print "  placement: moved "m" sites, saved "l" loop levels"}'
done
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
bash $MD/media_stack.sh down; bash $MD/media_stack.sh up gs; bash $MD/media_stack.sh init; cstate 1; bash $MD/media_stack.sh smoke
ARMS="gs p4"; for a in p4d st1 st1d; do [[ -x $DB/out_${OUTPFX}_$a/$SVCBIN ]] && ARMS="$ARMS $a"; done
echo "[$(date +%T)] A/B: $ARMS"; timeout 7200 bash $MD/media_ab.sh $O/ab_round2 3 $ARMS 2>&1 | tail -14
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] MEDIA2_DONE"
