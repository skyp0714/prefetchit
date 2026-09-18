#!/usr/bin/env bash
# PostgreSQL A/B under socialNetwork noise (default scheduling, server on 0-42, clients on 40-42): arms name=binary.
# Metrics per rep: pgbench tps (50 s, 16 clients prepared), backend perf stat (instructions, cycles, L2I, context switches) over 30 s.
# Usage: pg_ab.sh OUTDIR REPS name=/path/to/postgres ...
set -u; OUT=$1; REPS=$2; shift 2; mkdir -p $OUT; OUT=$(readlink -f $OUT)
PG=/home/hnpark2/prefetchit/benchmarks/pg; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk; SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
PGB="$PG/install_base/bin/pgbench -h /tmp -p 5440 -c 16 -j 4 -M prepared bench"; CSV=$OUT/ab.csv; [[ -f $CSV ]] || echo "arm,rep,tps,instr,cycles,l2i,cs" > $CSV
$PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; sleep 2
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
for rep in $(seq 1 $REPS); do for arm in "$@"; do name=${arm%%=*}; bin=${arm#*=}
  taskset -c 0-42 $bin -D $PG/data_scale100 -p 5440 -k /tmp > $OUT/server_${name}_r$rep.log 2>&1 & PM=$!; sleep 4
  taskset -c 40-42 $PGB -T 15 > /dev/null 2>&1
  taskset -c 40-42 $PGB -T 50 > $OUT/pgb_${name}_r$rep.log 2>&1 & BP=$!; sleep 10
  PIDS=$(pgrep -P $PM | tr '\n' ',' | sed 's/,$//')
  echo ps101899 | sudo -S -p '' perf stat -x, -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I/',context-switches -p $PIDS -- sleep 30 2> $OUT/perf_${name}_r$rep.txt > /dev/null
  wait $BP; tps=$(grep -E "^tps = " $OUT/pgb_${name}_r$rep.log | tail -1 | sed -E 's/tps = ([0-9.]+).*/\1/')
  $PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; sleep 3
  python3 - $name $rep "$tps" $CSV $OUT/perf_${name}_r$rep.txt <<'PY'
import csv,sys
name,rep,tps,out,f=sys.argv[1:6]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions',0); c=v.get('cycles',0); m=v.get('L2I',0); cs=v.get('context-switches',0)
open(out,'a').write(f"{name},{rep},{tps},{i:.0f},{c:.0f},{m:.0f},{cs:.0f}\n")
t=float(tps or 0); print(f"{name} r{rep}: tps={t:.0f} MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} cycles/txn={c/(30*t)/1e3 if t else 0:.0f}k cycles={c/1e9:.1f}G")
PY
done; done
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "^$W -D exp"); do kill $p 2>/dev/null; done
echo PG_AB_DONE
