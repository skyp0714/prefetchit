#!/usr/bin/env bash
# DCPerf v2 realistic screen (draft until the installed process names are verified): the benchpress job runs under taskset on the
# server cores; helper processes are re-pinned by pattern (clients → 60-67, DB/JVM → DBCORES); user-mode L2I MPKI / IPC per pattern group
# at DELAY1/DELAY2 seconds; then the same with deep C-states disabled on the server cores (cause diagnostic).
# Usage: dcperf_v2_screen.sh JOB CORES "server_pattern" "client_pattern" "db_pattern" DELAY1 DELAY2 [extra benchpress args...]
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; OUT=$R/dcperf_v2.csv
JOB=$1; CORES=$2; SPAT=$3; CPAT=$4; DPAT=$5; D1=$6; D2=$7; shift 7; EXTRA=("$@"); DBCORES=${DBCORES:-12-15}; CLCORES=${CLCORES:-60-67}
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))")
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'; [[ -f $OUT ]] || echo "job,config,group,cores,delay_s,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cstate() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
repin() { local pat=$1 cores=$2 p; for p in $(pgrep -f "$pat"); do taskset -apc $cores $p > /dev/null 2>&1; done; }
rec() { local cfg=$1 grp=$2 delay=$3 f=$4; python3 - $JOB "$cfg" "$grp" $CORES $NC $delay $f $OUT <<'PY'
import csv,sys
job,cfg,grp,cores,nc,delay,f,out=sys.argv[1:9]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(30000*int(nc))
open(out,'a').write(f"{job},{cfg},{grp},{cores},{delay},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"{job} [{cfg}] {grp:8s} @{delay}s: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
}
run_once() { local cfg=$1; cd $V
  (echo ps101899 | sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages JAVA_HOME=${JAVA_HOME:-/usr/lib/jvm/java-11-openjdk-amd64} taskset -c $CORES python3 ./benchpress_cli.py run $JOB "${EXTRA[@]}" > $R/logs/v2_run_${JOB}_$cfg.log 2>&1; echo "JOB_EXIT $?" >> $R/logs/v2_run_${JOB}_$cfg.log) & local JP=$!
  for delay in $D1 $D2; do sleep $delay; kill -0 $JP 2>/dev/null || { echo "  $JOB ended before ${delay}s"; break; }
    [[ -n $CPAT ]] && repin "$CPAT" $CLCORES; [[ -n $DPAT ]] && repin "$DPAT" $DBCORES; sleep 5
    local sp=$(pgrep -f "$SPAT" | tr '\n' ',' | sed 's/,$//'); [[ -z $sp ]] && { echo "  no server processes match $SPAT"; ps -eo pid,args | grep -vE "grep|benchpress" | tail -8 | cut -c1-120; continue; }
    echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/v2_srv.csv -e $EV -p $sp -- sleep 30 > /dev/null 2>&1; rec $cfg server $delay /tmp/v2_srv.csv
  done; wait $JP; grep -E "JOB_EXIT|score|Score|QPS|qps|RPS|rps|Throughput|final" $R/logs/v2_run_${JOB}_$cfg.log | tail -4 | cut -c1-160; }
run_once default; cstate 1; run_once noC6; cstate 0; echo "V2_SCREEN_${JOB}_DONE"
