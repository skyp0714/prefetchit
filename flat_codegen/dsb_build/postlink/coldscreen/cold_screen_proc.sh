#!/usr/bin/env bash
# Post-wake cold-start screen for a native process (not a container). The DSB stacks (confined to 0-35) + their load act as co-tenant noise.
#   shared  : process on 0-42 (floats among the noisy cores)     isolated: process on 36-39 (nobody else there)
# Usage: cold_screen_proc.sh NAME OUTCSV "CMD" [PGREP_PATTERN] ["LOADCMD"]  (CMD = server/app; LOADCMD runs on client cores 40-42 after 8 s; perf stat -p on the newest process matching PGREP_PATTERN)
set -u
NAME=$1; OUT=$2; CMD=$3; PAT=${4:-}; LOADCMD=${5:-}; WIN=${WIN:-30}; EV='instructions,cycles,cpu/event=0x24,umask=0x24,name=L2I/,context-switches,cpu-migrations,task-clock'
[[ -f $OUT ]] || echo "container,mode,instr,cycles,l2i,cs,migr,taskclock_ms" > $OUT
for mode in shared isolated; do
  cores=0-42; [[ $mode == isolated ]] && cores=36-39
  bash -c "exec taskset -c $cores $CMD" > /tmp/proc_$NAME.log 2>&1 & P=$!; sleep 8
  LP=; if [[ -n $LOADCMD ]]; then bash -c "taskset -c 40-42 $LOADCMD" > /tmp/load_$NAME.log 2>&1 & LP=$!; fi; sleep 12
  if [[ -n $PAT ]]; then pid=$(pgrep -n -f "$PAT"); else pid=$(pgrep -P $P | head -1); fi; [[ -n $pid ]] || pid=$P
  echo ps101899 | sudo -S -p '' perf stat -x, -e $EV -p $pid -- sleep $WIN 2> /tmp/cs_$NAME.txt > /dev/null
  python3 - $NAME $mode $OUT /tmp/cs_$NAME.txt <<'PY'
import csv,sys
c,mode,out,f=sys.argv[1:5]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
open(out,'a').write(f"{c},{mode},{v.get('instructions',0):.0f},{v.get('cycles',0):.0f},{v.get('L2I',0):.0f},{v.get('context-switches',0):.0f},{v.get('cpu-migrations',0):.0f},{v.get('task-clock',0):.1f}\n")
PY
  [[ -n $LP ]] && { kill $LP 2>/dev/null; pkill -P $LP 2>/dev/null; }
  if [[ -n $PAT ]]; then for q in $(pgrep -f "$PAT"); do kill $q 2>/dev/null; done; fi; kill $P 2>/dev/null; pkill -P $P 2>/dev/null; wait $P 2>/dev/null; sleep 4
  echo "[$(date +%T)] $NAME $mode done"
done
