#!/usr/bin/env bash
# PostgreSQL under socialNetwork co-tenant noise, default scheduling: STEP=trace (wake list) | STEP=ab (base / warm64 / twin; pgbench tps + server counters)
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; PG=/home/hnpark2/prefetchit/benchmarks/pg; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua; STEP=${STEP:-trace}; REPS=${REPS:-3}; OUT=$PL/results/pg_wake; mkdir -p $OUT
PGB="$PG/install_base/bin/pgbench -h /tmp -p 5440 -c 16 -j 4 -M prepared bench"
start_server(){ local pre=$1; env ${pre:+LD_PRELOAD=$pre WARMUP_LIST=$PL/warmup/list_pg.txt WARMUP_N=${WARM_N:-64} WARMUP_MIN_CYCLES=20000} taskset -c 0-42 $PG/install_base/bin/postgres -D $PG/data_scale100 -p 5440 -k /tmp > $OUT/server.log 2>&1 & PM=$!; sleep 5; echo $PM; }
stop_server(){ $PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; sleep 3; }
pids(){ local q=$1; echo $q; for k in $(pgrep -P $q); do pids $k; done; }
noise_on(){ ( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!; }
noise_off(){ kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done; }
stop_server
if [[ $STEP == trace ]]; then
  noise_on; PM=$(start_server ""); taskset -c 40-42 $PGB -T 15 > /dev/null 2>&1
  taskset -c 40-42 $PGB -T 60 > $OUT/pgbench_trace.log 2>&1 & BP=$!; sleep 10; PL_PIDS=$(pids $PM | tr ' ' ',')
  echo ps101899 | sudo -S -p '' perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -c 2003 -e sched:sched_switch -e raw_syscalls:sys_exit -p $PL_PIDS -o $OUT/wake.data -- sleep 30 > $OUT/record.log 2>&1
  echo ps101899 | sudo -S -p '' chmod a+r $OUT/wake.data; b=$(pgrep -P $PM | head -1); echo ps101899 | sudo -S -p '' cat /proc/$b/maps > $OUT/maps.txt
  wait $BP; echo ps101899 | sudo -S -p '' perf script -i $OUT/wake.data -F comm,tid,time,event,ip,sym,dso,trace > $OUT/events.txt 2> $OUT/script.err
  MAIN_NAME=postgres python3 $PL/wake_lines.py $OUT/events.txt $OUT/maps.txt $PL/warmup/list_pg.txt --top 256 | tail -6
  stop_server; noise_off; echo TRACE_DONE
else
  CSV=$OUT/ab.csv; [[ -f $CSV ]] || echo "arm,rep,tps,instr,cycles,l2i,cs" > $CSV; noise_on
  for rep in $(seq 1 $REPS); do for arm in base warm64 warm64_nop; do
    pre=; [[ $arm == warm64 ]] && pre=$PL/warmup/libwarmup_host.so; [[ $arm == warm64_nop ]] && pre=$PL/warmup/libwarmup_host_nop.so
    PM=$(start_server "$pre"); taskset -c 40-42 $PGB -T 15 > /dev/null 2>&1
    taskset -c 40-42 $PGB -T 50 > $OUT/pgb_${arm}_r${rep}.log 2>&1 & BP=$!; sleep 10; PL_PIDS=$(pids $PM | tr ' ' ',')
    echo ps101899 | sudo -S -p '' perf stat -x, -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I/',context-switches -p $PL_PIDS -- sleep 30 2> $OUT/perf_${arm}_r${rep}.txt > /dev/null
    wait $BP; tps=$(grep -E "^tps = " $OUT/pgb_${arm}_r${rep}.log | tail -1 | sed -E 's/tps = ([0-9.]+).*/\1/')
    python3 - $arm $rep "$tps" $CSV $OUT/perf_${arm}_r${rep}.txt <<'PY'
import csv,sys
arm,rep,tps,out,f=sys.argv[1:6]; v={}
for r in csv.reader(open(f)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
open(out,'a').write(f"{arm},{rep},{tps},{v.get('instructions',0):.0f},{v.get('cycles',0):.0f},{v.get('L2I',0):.0f},{v.get('context-switches',0):.0f}\n")
print(f"{arm} r{rep}: tps={tps} MPKI={1000*v.get('L2I',0)/max(1,v.get('instructions',1)):.2f} IPC={v.get('instructions',0)/max(1,v.get('cycles',1)):.3f} cycles={v.get('cycles',0)/1e9:.1f}G")
PY
    stop_server
  done; done
  noise_off; echo AB_DONE
fi
