#!/usr/bin/env bash
# Post-wake cold-start screen for a running docker stack.
#   shared mode  : every container confined to SHARED_CORES (default 0-35), floating inside → what default scheduling on a busy node gives
#   isolated mode: one container at a time moved to ISO_CORES (36-39) which nobody else uses
# For each container: perf stat -p (instructions, cycles, L2I code misses, context switches) over WIN s under LOADCMD (runs in background).
# Usage: cold_screen.sh OUTCSV PREFIX "LOADCMD" [containers...]   (containers default: all "$PREFIX*" running)
set -u
OUT=$1; PREFIX=$2; LOAD=$3; shift 3; CONTS=("$@")
SHARED=${SHARED_CORES:-0-35}; ISO=${ISO_CORES:-36-39}; WIN=${WIN:-30}; LOADDUR=${LOADDUR:-$((WIN+40))}
[[ ${#CONTS[@]} -gt 0 ]] || mapfile -t CONTS < <(docker ps --format '{{.Names}}' | grep "^$PREFIX")
EV='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I/,context-switches,cpu-migrations,task-clock'
[[ -f $OUT ]] || echo "container,mode,instr,cycles,l2i,cs,migr,taskclock_ms" > $OUT
measure(){ local c=$1 mode=$2; local pid; pid=$(docker inspect -f '{{.State.Pid}}' $c); [[ -n $pid && $pid != 0 ]] || return
  echo ps101899 | sudo -S perf stat -x, -e $EV -p $pid -- sleep $WIN 2> /tmp/cs_$c.txt > /dev/null
  python3 - $c $mode $OUT /tmp/cs_$c.txt <<'PY'
import csv,sys
c,mode,out,f=sys.argv[1:5]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
open(out,'a').write(f"{c},{mode},{v.get('instructions',0):.0f},{v.get('cycles',0):.0f},{v.get('L2I',0):.0f},{v.get('context-switches',0):.0f},{v.get('cpu-migrations',0):.0f},{v.get('task-clock',0):.1f}\n")
PY
}
for c in $(docker ps --format '{{.Names}}' | grep "^$PREFIX"); do docker update --cpuset-cpus $SHARED $c > /dev/null 2>&1; done
echo "[$(date +%T)] shared mode: all on $SHARED"
bash -c "$LOAD" > /tmp/cold_load.log 2>&1 & LP=$!; sleep 12
for c in "${CONTS[@]}"; do measure $c shared & done; wait $(jobs -p | grep -v $LP) 2>/dev/null; wait $LP
for c in "${CONTS[@]}"; do
  docker update --cpuset-cpus $ISO $c > /dev/null 2>&1; sleep 2
  bash -c "$LOAD" > /tmp/cold_load.log 2>&1 & LP=$!; sleep 12; measure $c isolated; wait $LP
  docker update --cpuset-cpus $SHARED $c > /dev/null 2>&1
  echo "[$(date +%T)] isolated: $c done"
done
echo COLD_SCREEN_DONE
