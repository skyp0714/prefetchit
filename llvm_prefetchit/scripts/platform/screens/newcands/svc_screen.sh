#!/usr/bin/env bash
# Pinned service screen for the 2026-09-21 candidates: the server container runs on CORES with deep C-states off; a load generator on
# CLCORES drives it at several rates; per-rate user-mode L2I MPKI / IPC of the server's cgroup over a WIN-second window.
# Usage: NAME=<row name> CONT=<container> CORES=8-11 CLCORES=60-67 svc_screen.sh "<client cmd with @RATE@>" rate1 rate2 ...
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/newcands_20260921; OUT=$R/services.csv
NAME=${NAME:?}; CONT=${CONT:?}; CORES=${CORES:-8-11}; CLCORES=${CLCORES:-60-67}; WIN=${WIN:-20}; DELAY=${DELAY:-25}
CMD=$1; shift; RATES="$@"
NC=$(python3 -c "import re;s='$CORES';print(sum(int(b)-int(a)+1 if b else 1 for a,b in re.findall(r'(\d+)-?(\d*)',s)))")
CL=$(python3 -c "import re;s='$CORES';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
cst() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cst 0' EXIT; cst 1
[[ -f $OUT ]] || echo "workload,config,cores,rate,util_pct,l2i,instr,cycles,mpki,ipc,note" > $OUT
ID=$(docker inspect -f '{{.Id}}' $CONT) || exit 1
for rate in $RATES; do
  c=${CMD//@RATE@/$rate}; echo "[$(date +%T)] $NAME rate=$rate"
  eval "timeout 300 $c" > $R/logs/${NAME}_$rate.log 2>&1 & CP=$!
  sleep $DELAY; kill -0 $CP 2>/dev/null || { echo "  client ended early"; tail -3 $R/logs/${NAME}_$rate.log | cut -c1-140; continue; }
  docker stats --no-stream --format '{{.CPUPerc}}' $CONT > /tmp/svc_cpu.txt 2>/dev/null &  SP=$!
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/svc_perf.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$ID.scope,system.slice/docker-$ID.scope,system.slice/docker-$ID.scope -- sleep $WIN > /dev/null 2>&1; wait $SP
  python3 - "$NAME" "${CONFIG:-noC6}" $CORES $NC $rate $WIN /tmp/svc_perf.csv /tmp/svc_cpu.txt $OUT "${NOTE:-}" <<'PY'
import csv,sys
name,cfg,cores,nc,rate,win,pf,cf,out,note=sys.argv[1:11]; v={}
for r in csv.reader(open(pf)):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
try: cpu=float(open(cf).read().strip().rstrip('%'))
except: cpu=0.0
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); util=cpu/int(nc)
open(out,'a').write(f"{name},{cfg},{cores},{rate},{util:.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{note}\n")
print(f"  {name} [{cfg}] rate={rate}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
  timeout 320 tail --pid=$CP -f /dev/null; grep -aE "^\[OVERALL\], Throughput|Throughput\(ops/sec\)|queries:|transactions:" $R/logs/${NAME}_$rate.log | tail -2 | cut -c1-110
done
cst 0; echo "[$(date +%T)] ${NAME}_SCREEN_DONE"
