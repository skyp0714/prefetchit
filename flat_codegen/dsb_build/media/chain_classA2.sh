#!/usr/bin/env bash
# Capacity-class (A) media services, corrected: every file the pass has to READ (function lists, plans) is staged into dsb_build, which
# is the only host directory mounted into the build container (/dsb). The previous run passed host paths that do not exist inside the
# container, so the pass silently injected nothing - out_mid_p4 had zero prefetches.
# Per service: base, sequential stream over the functions that actually execute, cold pass (own lines + callee entries), NOP twins, 5 reps.
set -u
D=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_django_20260919
MDIR=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media
DBROOT=/home/hnpark2/prefetchit/flat_codegen/dsb_build
for spec in "compose-review-service|ComposeReviewService|crs|2000" "movie-id-service|MovieIdService|mid|2000" "rating-service|RatingService|rts|2000"; do
  SVC=${spec%%|*}; r=${spec#*|}; SVCBIN=${r%%|*}; r=${r#*|}; OUTPFX=${r%%|*}; RATE=${r#*|}
  export SVC SVCBIN OUTPFX RATE SVC_CORES=0-1 POOL=2-31 CL_CORES=32-35
  source $MDIR/media_env.sh
  O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920/$OUTPFX; mkdir -p $O/plans $O/traces
  echo "[$(date +%T)] ===== $SVC alone on $SVC_CORES, R=$RATE"
  cd $DB
  if [[ ! -x $DB/out_${OUTPFX}_gs/$SVCBIN ]]; then STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh gs dsb-deps-jammy "" 2>&1 | tail -1; fi
  if [[ ! -x $DB/out_${OUTPFX}_gs/$SVCBIN ]]; then echo "  gs build failed, skipping"; continue; fi
  echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
  bash $MDIR/media_stack.sh down; bash $MDIR/media_stack.sh up gs; bash $MDIR/media_stack.sh init; cstate 1
  bash $MDIR/media_stack.sh smoke
  echo "[$(date +%T)] rate trace"; MODE=rate WIN=25 timeout 900 bash $MDIR/media_trace.sh $O/traces/rate gs 2>&1 | grep -E "^rate:" | cut -c1-130
  awk '!/^#/{print $2}' $O/traces/rate/rates.txt 2>/dev/null | sort -u > $DBROOT/staged/${OUTPFX}_funcs_exec.txt
  echo "  executed functions: $(grep -c . $DBROOT/staged/${OUTPFX}_funcs_exec.txt)"
  cd $DB
  for v in "seq|PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=20 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_SEQ_FUNCTIONS_FILE=/dsb/staged/${OUTPFX}_funcs_exec.txt" \
           "seqw|PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_SEQ_FUNCTIONS='.*'" \
           "cold|PREFETCHIT_COLD=1 PREFETCHIT_COLD_OWN_LINES=8 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=4 PREFETCHIT_COLD_MIN_INSNS=32"; do
    L=${v%%|*}; E=${v#*|}
    if [[ ! -x $DB/out_${OUTPFX}_$L/$SVCBIN ]]; then
      echo "[$(date +%T)] build $L"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $L dsb-deps-jammy "$E" 2>&1 | grep -E "prefetcht1|DONE" | head -2
    fi
    n=$(objdump -d $DB/out_${OUTPFX}_$L/$SVCBIN 2>/dev/null | grep -c prefetcht1); echo "  $L: $n prefetcht1 in the binary"
  done
  sleep 40   # let the twin watcher materialise out_*nop
  bash $MDIR/media_stack.sh recreate gs > /dev/null; pin_all
  ARMS="gs"; for a in seq seqnop seqw cold coldnop; do if [[ -x $DB/out_${OUTPFX}_$a/$SVCBIN ]]; then ARMS="$ARMS $a"; fi; done
  echo "[$(date +%T)] A/B $SVC: $ARMS"; timeout 9000 bash $MDIR/media_ab.sh $O/ab 5 $ARMS 2>&1 | tail -12
  cstate 0
done
bash $MDIR/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] CLASSA_MEDIA_DONE"
