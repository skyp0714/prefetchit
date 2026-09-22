#!/usr/bin/env bash
# Separate the two cold-start sources on isolated cores: deep C-states (core C6 flushes L2) vs nothing.
# For each container: isolated on ISO_CORES with C6/C6P enabled (default) and with C6/C6P disabled on those cores.
# Usage: cold_screen_cstate.sh OUTCSV "LOADCMD" containers...
set -u
OUT=$1; LOAD=$2; shift 2; CONTS=("$@"); ISO=${ISO_CORES:-36-39}; SHARED=${SHARED_CORES:-0-35}; WIN=${WIN:-30}
EV='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I/,context-switches'
[[ -f $OUT ]] || echo "container,mode,instr,cycles,l2i,cs,migr,taskclock_ms" > $OUT
cstate(){ local v=$1 cpu st; for cpu in 36 37 38 39; do for st in 3 4; do echo ps101899 | sudo -S -p '' sh -c "echo $v > /sys/devices/system/cpu/cpu$cpu/cpuidle/state$st/disable"; done; done; }
measure(){ local c=$1 mode=$2; local pid; pid=$(docker inspect -f '{{.State.Pid}}' $c); [[ -n $pid && $pid != 0 ]] || return
  echo ps101899 | sudo -S -p '' perf stat -x, -e $EV -p $pid -- sleep $WIN 2> /tmp/cs_$c.txt > /dev/null
  python3 - $c $mode $OUT /tmp/cs_$c.txt <<'PY'
import csv,sys
c,mode,out,f=sys.argv[1:5]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
open(out,'a').write(f"{c},{mode},{v.get('instructions',0):.0f},{v.get('cycles',0):.0f},{v.get('L2I',0):.0f},{v.get('context-switches',0):.0f},0,0\n")
PY
}
( while true; do bash -c "$LOAD" > /tmp/cold_load.log 2>&1; done ) & LP=$!; sleep 12
for c in "${CONTS[@]}"; do
  docker update --cpuset-cpus $ISO $c > /dev/null 2>&1; sleep 2
  cstate 0; sleep 1; measure $c iso_c6on
  cstate 1; sleep 1; measure $c iso_c6off
  cstate 0; docker update --cpuset-cpus $SHARED $c > /dev/null 2>&1
  echo "[$(date +%T)] cstate: $c done"
done
kill $LP 2>/dev/null; pkill -P $LP 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
echo CSTATE_DONE
