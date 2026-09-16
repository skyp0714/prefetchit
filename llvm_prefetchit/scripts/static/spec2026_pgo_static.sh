#!/usr/bin/env bash
# SPEC2026 benchmark: traces → PGO plan → static plan (ret,cond) → pass builds (runcpu, label per variant) → twins → interleaved A/B
set -u
BENCH="${1:?bench}"; ROOT=/home/hnpark2/prefetchit; SPEC=$ROOT/benchmarks/spec2026; LLVM=$ROOT/llvm_prefetchit
OUT=$LLVM/results/pgo_static_20260916/$BENCH; mkdir -p $OUT/plans $OUT/measure; CORE="${CORE:-40}"; REPS=3
log(){ echo "[$(date '+%T')] [$BENCH] $*" | tee -a $OUT/run.log; }
wait_quiet(){ while pgrep -x clang++-19 >/dev/null || pgrep -x clang-19 >/dev/null || pgrep -f "runcpu.*action=build" >/dev/null; do sleep 30; done; }
cd $SPEC; source shrc
D=$SPEC/benchspec/CPU/$BENCH
runcpu --config=prefetchit-clang-2026 --size=ref --action=setup --noreportable $BENCH > $OUT/setup.log 2>&1
RD=$(ls -d $D/run/run_base_ref*_clangbase.0000 | head -1); CMD=$(cd $RD && specinvoke -n | grep -v '^#' | grep -v '^$' | head -1); BASE=$(ls $D/exe/*_base.clangbase | head -1)
log "cmd: ${CMD:0:120}"
# traces (3 x 60 s)
for i in 1 2 3; do TD=$OUT/traces/trace0$i/l2_miss; mkdir -p $TD; [[ -s $TD/lbr_symbolic_dump.txt ]] && continue
  (cd $RD && perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 5000 -o $TD/l2miss_profile.data -C $CORE -- timeout -k 5s 60s taskset -c $CORE bash -c "$CMD" > $TD/record.log 2>&1 || true)
  bash $ROOT/profiling/analyze_pebs_trace.sh --data $TD/l2miss_profile.data --out-dir $TD --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary $BASE > $TD/analyze.log 2>&1
  log "trace $i samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' $TD/trace_summary.md)"
done
python3 $ROOT/static_prefetch/tools/ret/miss_stream_characterization.py --binary $BASE --trace-dir $OUT/traces/trace01/l2_miss --out-dir $OUT/diag 2>&1 | grep -E "^\{'type'" | cut -c1-150 | tee -a $OUT/run.log
TA=(); for i in 1 2 3; do TA+=(--trace-dir $OUT/traces/trace0$i/l2_miss); done
python3 $LLVM/tools/prefetchit_trace_to_plan.py "${TA[@]}" --binary $BASE --top-k 999999 --target-coverage-pct 90 --depth 24 --depth-min 4 --site-budget-per-target 8 --candidate-pool 0 --selection-mode top-sites --sites-per-depth 1 --allow-unresolved-targets --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0,64 --target-ip-source sample-ip --summary-dir $OUT/plans/pgo_cov90 --output $OUT/plans/pgo_cov90.plan.json > $OUT/plans/pgo_cov90.log 2>&1
log "PGO plan: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']))" $OUT/plans/pgo_cov90.plan.json) injections"
python3 $ROOT/static_prefetch/tools/static_plan.py --binary $BASE --kinds ret,cond --out-dir $OUT/plans/static_work --output $OUT/plans/static_retcond.plan.json --label static_retcond > $OUT/plans/static.log 2>&1 || tail -2 $OUT/plans/static.log
log "static plan: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']))" $OUT/plans/static_retcond.plan.json 2>/dev/null) injections"
build(){ local V=$1 PLAN=$2
  PREFETCHIT_PLAN=$PLAN runcpu --config=prefetchit-clang-2026 --action=build --tune=base --rebuild --define label=$V --define build_ncpus=24 --define extra_optimize="-fpass-plugin=$LLVM/build/PrefetchITPass.so" $BENCH > $OUT/build_$V.log 2>&1
  local VB=$(ls $D/exe/*_base.$V 2>/dev/null | head -1); [[ -x "$VB" ]] || { log "BUILD FAILED $V"; return 1; }
  cp -f $VB $OUT/${V}.unanchored; python3 $LLVM/tools/resolve_plan_layout_shift.py --plan $PLAN --shifts $PLAN.shifts.json --output ${PLAN%.json}.resolved.json > /dev/null 2>&1 || true
  python3 $LLVM/tools/reanchor_prefetch_targets.py --baseline $BASE --binary $OUT/${V}.unanchored --plan ${PLAN%.json}.resolved.json --output $VB 2>&1 | tail -1 | tee -a $OUT/run.log
  log "$V: $(llvm-objdump-19 -d $VB | grep -cE 'prefetcht[012]') prefetches in $(basename $VB)"; python3 $LLVM/tools/make_nop_control_binary.py --input $VB --output ${VB}_nop > /dev/null 2>&1; }
build pgo_cov90 $OUT/plans/pgo_cov90.plan.json
build static_retcond $OUT/plans/static_retcond.plan.json
wait_quiet; exec 9>/tmp/measure.lock; flock 9
CSV=$OUT/measure/runs.csv; echo "variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc,rc" > $CSV
run1(){ local v=$1 rep=$2 bin=$3; local c; c=$(echo "$CMD" | sed -E "s#\.\./run_base_ref[a-z]+_clangbase\.0000/[^ ]+#$bin#"); local s e rc
  s=$(date +%s.%N); (cd $RD && taskset -c $CORE perf stat -x, -o $OUT/measure/${v}_r$rep.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -- bash -c "$c" > $OUT/measure/${v}_r$rep.log 2>&1); rc=$?; e=$(date +%s.%N)
  python3 - $CSV $v $rep $s $e $OUT/measure/${v}_r$rep.csv $rc <<'PY'
import csv,sys
out,v,rep,s,e,p,rc=sys.argv[1:]; ev={}
for row in csv.reader(open(p)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0); el=float(e)-float(s)
csv.writer(open(out,"a",newline="")).writerow([v,rep,f"{el:.3f}",int(i),int(c),int(m),f"{1000*m/i if i else 0:.3f}",f"{i/c if c else 0:.3f}",rc])
print(f"{v} rep{rep}: {el:.1f}s MPKI={1000*m/i if i else 0:.2f} rc={rc}")
PY
}
for rep in $(seq 1 $REPS); do run1 base $rep $BASE | tee -a $OUT/run.log; for V in pgo_cov90 static_retcond; do VB=$(ls $D/exe/*_base.$V 2>/dev/null | head -1); [[ -x "$VB" ]] || continue; run1 $V $rep $VB | tee -a $OUT/run.log; run1 ${V}_nop $rep ${VB}_nop | tee -a $OUT/run.log; done; done
python3 - $CSV <<'PY'
import csv,statistics as st,sys
from collections import defaultdict
g=defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    if r["rc"]=="0": g[r["variant"]].append(r)
med={v:st.median(float(r["elapsed_sec"]) for r in rs) for v,rs in g.items()}; mp={v:st.mean(float(r["l2i_mpki"]) for r in rs) for v,rs in g.items()}
print("| variant | n | median s | speedup vs base | L2I MPKI |\n|---|---:|---:|---:|---:|")
for v in sorted(g,key=lambda x:med[x]): print(f"| {v} | {len(g[v])} | {med[v]:.1f} | {med['base']/med[v]:.4f}x | {mp[v]:.2f} |")
PY
echo "SPEC_PGO_STATIC_DONE $BENCH"
