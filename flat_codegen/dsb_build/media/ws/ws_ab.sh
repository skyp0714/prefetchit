#!/usr/bin/env bash
# Interleaved A/B of wake-stream arms on movie-id in the INTERLEAVED regime (whole stack on cores 0-7, C6 off, MODE=2ghz).
# Usage: ws_ab.sh OUT_DIR REPS name=ARM[:PRELOAD:LIST:N0:QM] ...   (PRELOAD/LIST host paths or '-')
# Per rep/arm: recreate the service with that arm, 15 s warm-up + 60 s load at $RATE, perf stat the service pid for 30 s
# (L2I code-read misses, SW prefetch hit/miss at L2, instructions, cycles, context switches).
set -u
export SVC_CORES=${SVC_CORES:-0-7} POOL=${POOL:-0-7} CL_CORES=${CL_CORES:-32-35} RATE=${RATE:-600}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
OUT=$1; REPS=$2; shift 2; mkdir -p $OUT; OUT=$(readlink -f $OUT); CSV=$OUT/ab.csv
[[ -f $CSV ]] || echo "arm,rep,rps,p99_ms,non2xx,instr,cycles,l2i,swpf_miss,swpf_hit,cs,task_clock_ms" > $CSV
EV='cpu/event=0x24,umask=0x24,name=L2I/u,cpu/event=0x24,umask=0x28,name=SWPF_MISS/u,cpu/event=0x24,umask=0xc8,name=SWPF_HIT/u,instructions:u,cycles:u,context-switches,task-clock'
for rep in $(seq 1 $REPS); do for spec in "$@"; do
  name=${spec%%=*}; s=${spec#*=}; IFS=: read -r arm pre list n0 qm <<< "$s"
  bash $MD/ws/ws_recreate.sh $arm ${pre:--} ${list:--} ${n0:-32} ${qm:-32} > /dev/null
  pid=$(svc_pid); [[ -z $pid || $pid == 0 ]] && { echo "$name r$rep: container not running"; continue; }
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 15 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
  taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 60 -L -s $LUA $WRK_URL -R $RATE > $OUT/wrk_${name}_r$rep.log 2>&1 & WP=$!; sleep 12
  echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/perf_${name}_r$rep.csv -e $EV -p $pid -- sleep 30 > /dev/null 2>&1
  wait $WP
  docker logs $CONT 2>&1 | grep "^ws:" | tail -3 > $OUT/wslog_${name}_r$rep.txt
  python3 - $name $rep $OUT/wrk_${name}_r$rep.log $OUT/perf_${name}_r$rep.csv $CSV <<'PY'
import csv,sys,re
arm,rep,wlog,pf,out=sys.argv[1:6]; w=open(wlog).read(); v={}
for r in csv.reader(open(pf)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
m=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(m.group(1)) if m else 0
m=re.search(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)",w); p99=(float(m.group(1))*(1000 if m.group(2)=='s' else 0.001 if m.group(2)=='us' else 1)) if m else 0
m=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w); bad=int(m.group(1)) if m else 0
i=v.get('instructions:u',0); c=v.get('cycles:u',0); l=v.get('L2I',0); sm=v.get('SWPF_MISS',0); sh=v.get('SWPF_HIT',0); cs=v.get('context-switches',0); t=v.get('task-clock',0)
open(out,'a').write(f"{arm},{rep},{rps:.1f},{p99:.1f},{bad},{i:.0f},{c:.0f},{l:.0f},{sm:.0f},{sh:.0f},{cs:.0f},{t:.0f}\n")
print(f"{arm} r{rep}: rps={rps:.0f} p99={p99:.0f}ms non2xx={bad} | MPKI={1000*l/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.2f}G cycles={c/1e9:.2f}G swpf_miss={sm/1e6:.1f}M swpf_hit={sh/1e6:.1f}M fill%={100*sm/(sm+sh) if sm+sh else 0:.0f} cpu={t/30000:.0f}%")
PY
done; done
python3 $MD/ws/ws_summary.py $CSV; echo "WS_AB_DONE"
