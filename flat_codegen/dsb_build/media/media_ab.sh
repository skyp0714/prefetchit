#!/usr/bin/env bash
# Interleaved A/B of media service arms in the alone regime (target service on its own cores, C6 off there, rest of the stack in POOL).
# Per rep/arm: recreate the service container with that arm's binary, 15 s warm-up + 60 s load, perf stat the service pid for 30 s.
# Usage: media_ab.sh OUT_DIR REPS arm1 arm2 ...   (arm "stock" = the original image binary)
set -u; source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
OUT=$1; REPS=$2; shift 2; mkdir -p $OUT; OUT=$(readlink -f $OUT); CSV=$OUT/ab.csv
[[ -f $CSV ]] || echo "arm,rep,rps,p99_ms,non2xx,instr,cycles,l2i,cs,task_clock_ms" > $CSV
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,context-switches,task-clock'
for rep in $(seq 1 $REPS); do for arm in "$@"; do
  if [[ $arm == stock ]]; then bash $MD/media_stack.sh stock > /dev/null; else bash $MD/media_stack.sh recreate $arm > /dev/null; fi
  pid=$(svc_pid); [[ -z $pid || $pid == 0 ]] && { echo "$arm r$rep: container not running"; continue; }
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 15 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 60 -L -s $LUA $WRK_URL -R $RATE > $OUT/wrk_${arm}_r$rep.log 2>&1 & WP=$!; sleep 12
  echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/perf_${arm}_r$rep.csv -e $EV -p $pid -- sleep 30 > /dev/null 2>&1
  wait $WP
  python3 - $arm $rep $OUT/wrk_${arm}_r$rep.log $OUT/perf_${arm}_r$rep.csv $CSV <<'PY'
import csv,sys,re
arm,rep,wlog,pf,out=sys.argv[1:6]; w=open(wlog).read(); v={}
for r in csv.reader(open(pf)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
m=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(m.group(1)) if m else 0
m=re.search(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)",w); p99=(float(m.group(1))*(1000 if m.group(2)=='s' else 0.001 if m.group(2)=='us' else 1)) if m else 0
m=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w); bad=int(m.group(1)) if m else 0
i=v.get('instructions:u',0); c=v.get('cycles:u',0); l=v.get('L2I',0); cs=v.get('context-switches',0); t=v.get('task-clock',0)
open(out,'a').write(f"{arm},{rep},{rps:.1f},{p99:.1f},{bad},{i:.0f},{c:.0f},{l:.0f},{cs:.0f},{t:.0f}\n")
print(f"{arm} r{rep}: rps={rps:.0f} p99={p99:.0f}ms non2xx={bad} | MPKI={1000*l/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G cycles={c/1e9:.1f}G cpu={t/30000:.0f}%")
PY
done; done
python3 $MD/media_summary.py $CSV; echo "MEDIA_AB_DONE"
