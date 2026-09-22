#!/usr/bin/env bash
# TailBench (integrated harness, in-process client) on CORES pinned with deep C-states off: each app with 4 worker threads at two loads
# (paper QPS and QPS/4 — the operating-point rule keeps the max-MPKI side); user-mode L2I MPKI / IPC of the app process over WIN s after
# warm-up. Prebuilt binaries (2026-09-15) + compatlib shims (readline 7→8, jemalloc 1→2). Rows → tailbench.csv
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; TBH=/home/hnpark2/prefetchit/benchmarks/tailbench; TB=$TBH/tailbench; OUT=$R/tailbench.csv
CORES=${CORES:-0-3}; NC=4; WIN=${WIN:-20}; DELAY=${DELAY:-30}; export LD_LIBRARY_PATH=$TBH/compatlib:${LD_LIBRARY_PATH:-}
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cst() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
pg() { pgrep -f "$1" | grep -vw -e $$ -e $BASHPID; }
killapp() { local p; for p in $(pg "_integrated"); do kill -9 $p 2>/dev/null; done; }
trap 'cst 0; killapp' EXIT; cst 1
[[ -f $OUT ]] || echo "app,qps,cores,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
APPS="img-dnn|img-dnn|img-dnn_integrated|500|THREADS
masstree|masstree|mttest_integrated|2000|NTHREADS
moses|moses|moses_integrated|100|THREADS
shore|shore|shore_kits_integrated|10|THREADS
silo|silo|dbtest_integrated|1000|NUM_THREADS
sphinx|sphinx|decoder_integrated|1|THREADS
xapian|xapian|xapian_integrated|50|NSERVERS"
echo "$APPS" | while IFS='|' read -r app dir bin pq tvar; do [[ -n ${ONLY:-} && " $ONLY " != *" $app "* ]] && continue
  for qps in $pq $((pq/4>0?pq/4:1)); do
    warm=$((10*qps>10?10*qps:10)); maxr=$((90*qps+warm)); rv=MAXREQS; [[ $app == xapian ]] && rv=REQUESTS
    cd $TB/$dir || continue; killapp; rm -rf scratch log diskrw db-tpcc-1 2>/dev/null
    echo "[$(date +%T)] $app qps=$qps ($tvar=4, warm=$warm, max=$maxr)"
    env $tvar=4 QPS=$qps WARMUPREQS=$warm $rv=$maxr taskset -c $CORES timeout 900 bash ./run.sh > $R/logs/tb_${app}_q$qps.log 2>&1 & RP=$!
    sleep $DELAY; p=$(pg "$bin" | head -1); [[ -z $p ]] && { echo "  $app not running at ${DELAY}s"; tail -3 $R/logs/tb_${app}_q$qps.log | cut -c1-140; kill $RP 2>/dev/null; continue; }
    echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/tb_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -e task-clock -p $p -- sleep $WIN > /dev/null 2>&1
    python3 - $app $qps $CORES $NC $WIN /tmp/tb_perf.csv $OUT <<'PY'
import csv,sys
app,qps,cores,nc,win,f,out=sys.argv[1:8]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u','task-clock'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(float(win)*1000*int(nc))
open(out,'a').write(f"{app},{qps},{cores},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"  {app} qps={qps}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
    kill $RP 2>/dev/null; killapp; sleep 2
    grep -aE "latency|Throughput|error|Error" $R/logs/tb_${app}_q$qps.log | tail -1 | cut -c1-140
  done
done
cst 0; echo "[$(date +%T)] TB_SCREEN_DONE"
