#!/usr/bin/env bash
# The remaining CAPACITY-class (A) workloads, in descending MPKI: media compose-review alone (3.8), media rating alone (2.2).
# Per workload: base MPKI at the alone operating point, then the two mechanisms that are cheap to build and have precedent -
# the sequential stream restricted to the functions that actually execute, and the cold pass (own lines + callee entries) - each with
# its NOP twin, 5 interleaved reps.
set -u
D=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919
MDIR=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media
until grep -qE "MEDIAHI_DONE|MEDIAHI_FAILED" $MDIR/logs/chain_media_hi.log 2>/dev/null; do sleep 60; done
for spec in "compose-review-service|ComposeReviewService|crs" "rating-service|RatingService|rts"; do
  SVC=${spec%%|*}; rest=${spec#*|}; SVCBIN=${rest%%|*}; OUTPFX=${rest#*|}
  export SVC SVCBIN OUTPFX SVC_CORES=0-1 POOL=2-31 CL_CORES=32-35 RATE=2000
  source $MDIR/media_env.sh
  O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920/$OUTPFX; mkdir -p $O/plans $O/traces
  echo "[$(date +%T)] ===== $SVC ($SVCBIN) alone on $SVC_CORES"
  cd $DB
  if [[ ! -x $DB/out_${OUTPFX}_gs/$SVCBIN ]]; then
    echo "[$(date +%T)] build gs"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh gs dsb-deps-jammy "" 2>&1 | tail -2
  fi
  if [[ ! -x $DB/out_${OUTPFX}_gs/$SVCBIN ]]; then echo "  gs build failed, skipping $SVC"; continue; fi
  echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
  bash $MDIR/media_stack.sh down; bash $MDIR/media_stack.sh up gs; bash $MDIR/media_stack.sh init; cstate 1
  bash $MDIR/media_stack.sh smoke
  echo "[$(date +%T)] rate trace (executed functions)"; MODE=rate WIN=25 timeout 900 bash $MDIR/media_trace.sh $O/traces/rate gs 2>&1 | grep -E "^rate:" | cut -c1-140
  awk '!/^#/{print $2}' $O/traces/rate/rates.txt 2>/dev/null | sort -u > $O/plans/funcs_exec.txt
  echo "  executed functions: $(grep -c . $O/plans/funcs_exec.txt)"
  cd $DB
  for v in "seq|PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=20 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_SEQ_FUNCTIONS_FILE=$O/plans/funcs_exec.txt" \
           "cold|PREFETCHIT_COLD=1 PREFETCHIT_COLD_OWN_LINES=8 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=4 PREFETCHIT_COLD_MIN_INSNS=32"; do
    L=${v%%|*}; E=${v#*|}
    if [[ ! -x $DB/out_${OUTPFX}_$L/$SVCBIN ]]; then echo "[$(date +%T)] build $L"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $L dsb-deps-jammy "$E" 2>&1 | tail -2; fi
  done
  bash $MDIR/media_stack.sh recreate gs > /dev/null; pin_all
  ARMS="gs"; for a in seq seqnop cold coldnop; do if [[ -x $DB/out_${OUTPFX}_$a/$SVCBIN ]]; then ARMS="$ARMS $a"; fi; done
  echo "[$(date +%T)] A/B $SVC: $ARMS"; timeout 9000 bash $MDIR/media_ab.sh $O/ab 5 $ARMS 2>&1 | tail -12
  cstate 0
done
bash $MDIR/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] CLASSA_MEDIA_DONE"
