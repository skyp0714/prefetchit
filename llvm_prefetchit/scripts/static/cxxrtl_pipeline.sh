#!/usr/bin/env bash
# CXXRTL (yosys) simulator: base traces → PGO plan; seq + PGO variants through the pass; NOP twins; interleaved A/B (3 reps).
set -u
ROOT=/home/hnpark2/prefetchit; LLVM=$ROOT/llvm_prefetchit; SRC=/tmp/screen_inputs/cxxrtl; OUT=$LLVM/results/pgo_static_20260916/cxxrtl; mkdir -p $OUT/bin $OUT/traces $OUT/plans $OUT/measure
CORE=44; CYC=300000; PLUGIN=$LLVM/build/PrefetchITPass.so; YINC=/usr/share/yosys/include
log(){ echo "[$(date '+%T')] [cxxrtl] $*" | tee -a $OUT/run.log; }
wait_quiet(){ while pgrep -x clang++-19 >/dev/null || pgrep -x clang-19 >/dev/null || pgrep -f "runcpu.*action=build" >/dev/null; do sleep 30; done; }
cp -f $SRC/sim_cxxrtl $OUT/bin/base
# 1. traces of the base (3 x ~50 s)
for i in 1 2 3; do TD=$OUT/traces/trace0$i/l2_miss; mkdir -p $TD; [[ -s $TD/lbr_symbolic_dump.txt ]] && continue
  (cd $SRC && perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 5000 -o $TD/l2miss_profile.data -C $CORE -- taskset -c $CORE ./sim_cxxrtl 600000 > $TD/record.log 2>&1)
  bash $ROOT/profiling/analyze_pebs_trace.sh --data $TD/l2miss_profile.data --out-dir $TD --event-label 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' --binary $OUT/bin/base > $TD/analyze.log 2>&1
  log "trace $i samples: $(awk -F: '/LBR samples parsed/ {gsub(/ /, "", $2); print $2; exit}' $TD/trace_summary.md)"
done
python3 $ROOT/static_prefetch/tools/ret/miss_stream_characterization.py --binary $OUT/bin/base --trace-dir $OUT/traces/trace01/l2_miss --out-dir $OUT/diag 2>&1 | grep -E "^\{'type'|cumulative" | cut -c1-160 | tee -a $OUT/run.log
# 2. PGO plan (all sample types, sample-IP targets)
TA=(); for i in 1 2 3; do TA+=(--trace-dir $OUT/traces/trace0$i/l2_miss); done
python3 $LLVM/tools/prefetchit_trace_to_plan.py "${TA[@]}" --binary $OUT/bin/base --top-k 999999 --target-coverage-pct 90 --depth 24 --depth-min 4 --site-budget-per-target 8 --candidate-pool 0 --selection-mode top-sites --sites-per-depth 1 --allow-unresolved-targets --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0,64 --target-ip-source sample-ip --summary-dir $OUT/plans/pgo_cov90 --output $OUT/plans/pgo_cov90.plan.json > $OUT/plans/pgo_cov90.log 2>&1
log "PGO plan: $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['injections']))" $OUT/plans/pgo_cov90.plan.json) injections"
# 3. builds (parallel): seq (plan-free) and PGO (plan)
build(){ local name=$1; shift; ( cd $SRC && env "$@" clang++-19 -O2 -g -std=c++17 -I$YINC -I$YINC/backends/cxxrtl/runtime -fpass-plugin=$PLUGIN main.cc -o $OUT/bin/$name 2> $OUT/build_$name.err; grep -h "prefetchit-seq:\|prefetchit-inject: injected=" $OUT/build_$name.err | tail -2 | cut -c1-200 ) ; }
build seq_d4096_k20 PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=20 PREFETCHIT_SEQ_FUNCTIONS='.*' &
build pgo_cov90 PREFETCHIT_PLAN=$OUT/plans/pgo_cov90.plan.json &
wait; log "builds done"
python3 $LLVM/tools/resolve_plan_layout_shift.py --plan $OUT/plans/pgo_cov90.plan.json --shifts $OUT/plans/pgo_cov90.plan.json.shifts.json --output $OUT/plans/pgo_cov90.resolved.json > /dev/null 2>&1 || true
python3 $LLVM/tools/reanchor_prefetch_targets.py --baseline $OUT/bin/base --binary $OUT/bin/pgo_cov90 --plan $OUT/plans/pgo_cov90.resolved.json --output $OUT/bin/pgo_cov90.anch 2>&1 | tail -1 | tee -a $OUT/run.log && mv -f $OUT/bin/pgo_cov90.anch $OUT/bin/pgo_cov90
for v in seq_d4096_k20 pgo_cov90; do log "$v: $(llvm-objdump-19 -d $OUT/bin/$v | grep -cE 'prefetcht[012]') prefetches"; python3 $LLVM/tools/make_nop_control_binary.py --input $OUT/bin/$v --output $OUT/bin/${v}_nop > /dev/null 2>&1; done
# 4. measure (quiet machine, lock)
wait_quiet; exec 9>/tmp/measure.lock; flock 9
CSV=$OUT/measure/runs.csv; echo "variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc" > $CSV
run1(){ local v=$1 rep=$2 b=$OUT/bin/$1; local s e; s=$(date +%s.%N); (cd $SRC && taskset -c $CORE perf stat -x, -o $OUT/measure/${v}_r$rep.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -- $b $CYC > $OUT/measure/${v}_r$rep.log 2>&1); e=$(date +%s.%N)
  python3 - $CSV $v $rep $s $e $OUT/measure/${v}_r$rep.csv <<'PY'
import csv,sys
out,v,rep,s,e,p=sys.argv[1:]; ev={}
for row in csv.reader(open(p)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0); el=float(e)-float(s)
csv.writer(open(out,"a",newline="")).writerow([v,rep,f"{el:.3f}",int(i),int(c),int(m),f"{1000*m/i if i else 0:.3f}",f"{i/c if c else 0:.3f}"])
print(f"{v} rep{rep}: {el:.2f}s MPKI={1000*m/i if i else 0:.2f}")
PY
}
for rep in 1 2 3; do for v in base seq_d4096_k20 seq_d4096_k20_nop pgo_cov90 pgo_cov90_nop; do run1 $v $rep | tee -a $OUT/run.log; done; done
python3 - $CSV <<'PY'
import csv,statistics as st,sys
from collections import defaultdict
g=defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])): g[r["variant"]].append(r)
med={v:st.median(float(r["elapsed_sec"]) for r in rs) for v,rs in g.items()}; mp={v:st.mean(float(r["l2i_mpki"]) for r in rs) for v,rs in g.items()}
print("| variant | n | median s | speedup vs base | L2I MPKI |\n|---|---:|---:|---:|---:|")
for v in sorted(g,key=lambda x:med[x]): print(f"| {v} | {len(g[v])} | {med[v]:.2f} | {med['base']/med[v]:.4f}x | {mp[v]:.2f} |")
PY
echo CXXRTL_PIPE_DONE
