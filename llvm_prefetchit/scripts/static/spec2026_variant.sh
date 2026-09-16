#!/usr/bin/env bash
# SPEC CPU2026 prefetch pipeline for one benchmark (used only if the L2I-MPKI screen qualifies it):
#   STEP=trace    PEBS+LBR trace of the ref run (3 x TRACE_SEC s)            -> $OUT/traces/
#   STEP=plan     trace-guided plan (PGO ceiling) [+ static plan]             -> $OUT/plans/
#   STEP=build    rebuild the benchmark through the pass with EXTERNAL plan / seq mode (label = variant) + NOP twin
#   STEP=measure  interleaved runcpu-free timing of base / variant / twin on CORE (REPS)
#   spec2026_variant.sh BENCH STEP  (env: OUT, VARIANT, PLAN, SEQ_DISTANCE, SEQ_STRIDE, REPS, CORE)
set -euo pipefail
BENCH="${1:?bench}"; STEP="${2:?step}"
ROOT=/home/hnpark2/prefetchit; SPEC=$ROOT/benchmarks/spec2026; LLVM=$ROOT/llvm_prefetchit
OUT="${OUT:-$LLVM/results/spec2026_20260916/$BENCH}"; mkdir -p "$OUT"
CORE="${CORE:-40}"; REPS="${REPS:-3}"; TRACE_SEC="${TRACE_SEC:-60}"
cd $SPEC; source shrc
D=$SPEC/benchspec/CPU/$BENCH
RD=$(ls -d $D/run/run_base_refrate_clangbase.0000 $D/run/run_base_refspeed_clangbase.0000 2>/dev/null | head -1)
[[ -n "$RD" ]] || { runcpu --config=prefetchit-clang-2026 --size=ref --action=setup --noreportable $BENCH >/dev/null 2>&1; RD=$(ls -d $D/run/run_base_ref*_clangbase.0000 | head -1); }
CMD=$(cd $RD && specinvoke -n | grep -v '^#' | grep -v '^$' | head -1)
BASE_BIN=$(ls $D/exe/*_base.clangbase | head -1)
log(){ echo "[$(date '+%T')] [$BENCH] $*" | tee -a $OUT/run.log; }
case "$STEP" in
trace)
  for i in 1 2 3; do TD=$OUT/traces/trace0$i/l2_miss; [[ -s $TD/lbr_symbolic_dump.txt ]] && continue; mkdir -p $TD
    log "trace $i ($TRACE_SEC s)"
    (cd $RD && perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 20000 -o $TD/l2miss_profile.data -C $CORE -- \
       timeout -k 5s ${TRACE_SEC}s taskset -c $CORE bash -c "$CMD" > $TD/record.log 2>&1 || true)
    bash $ROOT/profiling/analyze_pebs_trace.sh --data $TD/l2miss_profile.data --out-dir $TD --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary $BASE_BIN > $TD/analyze.log 2>&1
    log "samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' $TD/trace_summary.md)"
  done
  python3 $ROOT/static_prefetch/tools/ret/miss_stream_characterization.py --binary $BASE_BIN --trace-dir $OUT/traces/trace01/l2_miss --out-dir $OUT/diag 2>&1 | grep -E "^\{'type'|cumulative" | cut -c1-200 | tee -a $OUT/run.log ;;
plan)
  mkdir -p $OUT/plans; TA=(); for i in 1 2 3; do TA+=(--trace-dir $OUT/traces/trace0$i/l2_miss); done
  log "PGO plan (all sample types, cov90, depth 4-24, budget 8)"
  python3 $LLVM/tools/prefetchit_trace_to_plan.py "${TA[@]}" --binary $BASE_BIN --top-k 999999 --target-coverage-pct 90 --depth 24 --depth-min 4 \
    --site-budget-per-target 8 --candidate-pool 0 --selection-mode top-sites --sites-per-depth 1 --allow-unresolved-targets \
    --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0,64 --target-ip-source sample-ip --summary-dir $OUT/plans/pgo_cov90 --output $OUT/plans/pgo_cov90.plan.json > $OUT/plans/pgo_cov90.log 2>&1 || tail -3 $OUT/plans/pgo_cov90.log
  log "$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']),'injections')" $OUT/plans/pgo_cov90.plan.json)" ;;
build)
  V="${VARIANT:?VARIANT}"; export PREFETCHIT_PLAN="${PLAN:-}"
  [[ -n "${SEQ_DISTANCE:-}" ]] && export PREFETCHIT_SEQ_DISTANCE=$SEQ_DISTANCE PREFETCHIT_SEQ_STRIDE_INSNS=${SEQ_STRIDE:-20}
  [[ -n "${BURST_LINES:-}" ]] && export PREFETCHIT_CALLEE_BURST_LINES=$BURST_LINES PREFETCHIT_CALLEE_BURST_LEAD=40
  log "build variant $V (plan=${PLAN:-none} seq=${SEQ_DISTANCE:-0})"
  runcpu --config=prefetchit-clang-2026 --action=build --tune=base --rebuild --define label=$V --define build_ncpus=24 \
    --define extra_optimize="-fpass-plugin=$LLVM/build/PrefetchITPass.so" $BENCH > $OUT/build_$V.log 2>&1 || true
  VB=$(ls $D/exe/*_base.$V 2>/dev/null | head -1); [[ -x "$VB" ]] || { log "BUILD FAILED (see $OUT/build_$V.log)"; exit 1; }
  log "$(llvm-objdump-19 -d $VB | grep -cE 'prefetcht[012]') prefetches in $VB"
  python3 $LLVM/tools/make_nop_control_binary.py --input $VB --output ${VB}_nop >/dev/null 2>&1; log "twin: $(llvm-objdump-19 -d ${VB}_nop | grep -cE 'prefetcht[012]') left" ;;
measure)
  CSV=$OUT/measure/runs.csv; mkdir -p $OUT/measure; [[ -s $CSV ]] || echo "variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc,status" > $CSV
  run_one(){ local v=$1 rep=$2 bin=$3; grep -q "^$v,$rep," $CSV && return; local c=${CMD/..\/run_base_ref*_clangbase.0000\/*_base.clangbase/$bin}
    # replace the executable path in the spec command with the variant binary
    c=$(echo "$CMD" | sed -E "s#\.\./run_base_ref[a-z]+_clangbase\.0000/[^ ]+#$bin#")
    local s e; s=$(date +%s.%N); (cd $RD && taskset -c $CORE perf stat -x, -o $OUT/measure/${v}_rep$rep.perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -- bash -c "$c" > $OUT/measure/${v}_rep$rep.log 2>&1); rc=$?; e=$(date +%s.%N)
    python3 - $CSV $v $rep $s $e $OUT/measure/${v}_rep$rep.perf.csv $rc <<'PY'
import csv,sys
out,v,rep,s,e,p,rc=sys.argv[1:]; ev={}
for row in csv.reader(open(p)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0); el=float(e)-float(s)
csv.writer(open(out,"a",newline="")).writerow([v,rep,f"{el:.3f}",int(ins),int(cyc),int(miss),f"{1000*miss/ins if ins else 0:.3f}",f"{ins/cyc if cyc else 0:.3f}","ok" if rc=="0" else f"rc{rc}"])
print(f"{v} rep{rep}: {el:.1f}s MPKI={1000*miss/ins if ins else 0:.2f}")
PY
  }
  for rep in $(seq 1 $REPS); do run_one base $rep $BASE_BIN; for v in ${VARIANTS:?}; do VB=$(ls $D/exe/*_base.$v | head -1); run_one $v $rep $VB; run_one ${v}_nop $rep ${VB}_nop; done; done | tee -a $OUT/run.log
  python3 - $CSV <<'PY'
import csv,statistics as st,sys
from collections import defaultdict
g=defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    if r["status"]=="ok": g[r["variant"]].append(r)
med={v:st.median(float(r["elapsed_sec"]) for r in rs) for v,rs in g.items()}; mp={v:st.mean(float(r["l2i_mpki"]) for r in rs) for v,rs in g.items()}
print("| variant | n | median s | speedup vs base | L2I MPKI |\n|---|---:|---:|---:|---:|")
for v in sorted(g,key=lambda x:med[x]): print(f"| {v} | {len(g[v])} | {med[v]:.1f} | {med['base']/med[v]:.4f}x | {mp[v]:.2f} |")
PY
  ;;
*) echo "unknown step $STEP" >&2; exit 2 ;;
esac
