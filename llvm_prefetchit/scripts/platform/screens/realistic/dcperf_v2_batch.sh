#!/usr/bin/env bash
# DCPerf v2 batch jobs (single process, no client): run the benchpress job under taskset on CORES with deep C-states off, and measure
# user-mode L2I MPKI / IPC system-wide on those cores (nothing else is scheduled there) in WIN-second windows at DELAY1/DELAY2.
# Usage: dcperf_v2_batch.sh JOB CORES DELAY1 DELAY2 [extra benchpress args...]      rows → dcperf_v2.csv (config=noC6, group=all)
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; V=/home/hnpark2/prefetchit/benchmarks/dcperf_v2; OUT=$R/dcperf_v2.csv
JOB=$1; CORES=$2; D1=$3; D2=$4; shift 4; EXTRA=("$@"); WIN=${WIN:-20}; CFG=(); [[ -n $JY ]] && CFG=(-b benchpress/config/$BY -j benchpress/config/$JY)
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))")
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cstate() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
[[ -f $OUT ]] || echo "job,config,group,cores,delay_s,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
trap 'cstate 0; [[ -n $JP ]] && echo ps101899 | sudo -S -p "" pkill -9 -P $JP 2>/dev/null' EXIT; cstate 1
cd $V; echo "[$(date +%T)] $JOB on $CORES (C6 off) ${EXTRA[*]}"
echo ps101899 | sudo -S -p '' env PATH=$PATH PYTHONPATH=/home/hnpark2/.local/lib/python3.12/site-packages $EXTRA_ENV taskset -c $CORES python3 ./benchpress_cli.py "${CFG[@]}" run $JOB "${EXTRA[@]}" > $R/logs/v2_batch_$JOB.log 2>&1 & JP=$!
for delay in $D1 $D2; do sleep $delay; kill -0 $JP 2>/dev/null || { echo "  $JOB ended before ${delay}s"; break; }
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/v2b_$JOB.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -- sleep $WIN > /dev/null 2>&1
  python3 - $JOB $CORES $NC $delay $WIN /tmp/v2b_$JOB.csv $OUT <<'PY'
import csv,sys
job,cores,nc,delay,win,f,out=sys.argv[1:8]; v={}
for r in csv.reader(open(f)):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0)
util=100*c/(float(win)*int(nc)*2.0e9) if c else 0   # user cycles / (cores x window) at the 2 GHz frozen clock
open(out,'a').write(f"{job},noC6,all,{cores},{delay},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f}\n")
print(f"{job} [noC6] all @{delay}s: util~{util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
done
timeout 1200 tail --pid=$JP -f /dev/null; JP=; grep -iE "result|score|time|ops|error" $R/logs/v2_batch_$JOB.log | grep -v "^\+" | tail -3 | cut -c1-160
