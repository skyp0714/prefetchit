#!/usr/bin/env bash
# Single-process batch screen: run CMD pinned to CORES with deep C-states off, measure the process's user-mode L2I MPKI / IPC over a
# WIN-second window starting DELAY seconds in. Usage: NAME=<row> CORES=36 [DELAY=] [WIN=] batch_screen.sh "<command>" [note]
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/newcands_20260921; OUT=$R/batch.csv
NAME=${NAME:?}; CORES=${CORES:-36}; WIN=${WIN:-20}; DELAY=${DELAY:-10}; CMD=$1; NOTE=${2:-}
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))")
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cst() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cst 0; [[ -n $BP ]] && kill -9 $BP 2>/dev/null' EXIT; cst 1
[[ -f $OUT ]] || echo "workload,cores,util_pct,l2i,instr,cycles,mpki,ipc,note" > $OUT
echo "[$(date +%T)] $NAME on $CORES (C6 off)"
( eval "exec taskset -c $CORES $CMD" ) > $R/logs/batch_$NAME.log 2>&1 & BP=$!   # exec: $BP must be the benchmark itself, not a wrapper shell
sleep $DELAY; [[ -d /proc/$BP ]] || { echo "  ended before ${DELAY}s"; tail -3 $R/logs/batch_$NAME.log | cut -c1-140; exit 1; }
echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/batch_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -e task-clock -p $BP -- sleep $WIN > /dev/null 2>&1
python3 - "$NAME" $CORES $NC $WIN /tmp/batch_perf.csv $OUT "$NOTE" <<'PY'
import csv,sys
name,cores,nc,win,f,out,note=sys.argv[1:8]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u','task-clock'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(float(win)*1000*int(nc))
open(out,'a').write(f"{name},{cores},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{note}\n")
print(f"  {name}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
kill $BP 2>/dev/null; BP=; cst 0; echo "[$(date +%T)] ${NAME}_BATCH_DONE"
