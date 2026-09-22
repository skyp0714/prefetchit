#!/usr/bin/env bash
# Iteration 2 at the interleaved (high-MPKI) operating point. Iteration 1 tested the site/target plan; this one tests the two
# mechanisms that have actually worked elsewhere:
#   seq  - the sequential stream that wins on the flattened simulators, restricted to the functions the service actually executes
#          (selection by execution, not by miss location - the lesson from the Verilator selection rounds)
#   cold - the cold-path pass: at each function entry, its own next lines plus the entries of the callees reached outside loops
# In the interleaved regime the miss pattern is a cold-start burst over the whole request path after every wake, which is much closer
# to a stream than the scattered per-line misses of the alone regime.
set -u
export SVC_CORES=0-7 POOL=0-7 CL_CORES=32-35
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
O=/home/hnpark2/prefetchit/llvm_prefetchit/results/capacity_media_20260920
until grep -qE "MEDIAHI_DONE|MEDIAHI_FAILED" $MD/logs/chain_media_hi.log 2>/dev/null; do sleep 60; done
RATE=$(grep -o "at R=[0-9]*" $MD/logs/chain_media_hi.log | tail -1 | cut -d= -f2); RATE=${RATE:-400}; export RATE
echo "[$(date +%T)] iteration 2 at R=$RATE"
echo ps101899 | sudo -S -p '' env MODE=2ghz /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
bash $MD/media_stack.sh down; bash $MD/media_stack.sh up gs; bash $MD/media_stack.sh init; cstate 1
echo "[$(date +%T)] rate trace (which functions actually execute)"
MODE=rate WIN=25 timeout 900 bash $MD/media_trace.sh $O/traces/rate_hi gs 2>&1 | grep -E "^rate:" | cut -c1-150
awk '!/^#/{print $2}' $O/traces/rate_hi/rates.txt | sort -u > $O/plans/funcs_exec.txt
echo "  executed functions: $(grep -c . $O/plans/funcs_exec.txt)"
cd $DB
for spec in "seqk20|PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=20 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_SEQ_FUNCTIONS_FILE=$O/plans/funcs_exec.txt" \
            "seqk40|PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_SEQ_FUNCTIONS_FILE=$O/plans/funcs_exec.txt" \
            "coldp|PREFETCHIT_COLD=1 PREFETCHIT_COLD_OWN_LINES=8 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=4 PREFETCHIT_COLD_MIN_INSNS=32"; do
  L=${spec%%|*}; E=${spec#*|}
  if [[ ! -x $DB/out_${OUTPFX}_$L/$SVCBIN ]]; then
    echo "[$(date +%T)] build $L"; STACK=mediaMicroservices SVCBIN=$SVCBIN OUTPFX=$OUTPFX OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh $L dsb-deps-jammy "$E" 2>&1 | tail -2
  fi
done
bash $MD/media_stack.sh recreate gs > /dev/null; pin_all
ARMS="gs"; for a in seqk20 seqk20nop seqk40 coldp coldpnop; do if [[ -x $DB/out_${OUTPFX}_$a/$SVCBIN ]]; then ARMS="$ARMS $a"; fi; done
echo "[$(date +%T)] A/B iteration 2: $ARMS"; timeout 9000 bash $MD/media_ab.sh $O/ab_it2 5 $ARMS 2>&1 | tail -14
cstate 0; bash $MD/media_stack.sh down
echo ps101899 | sudo -S -p '' env MODE=restore /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh > /dev/null 2>&1
echo "[$(date +%T)] MEDIA_IT2_DONE"
