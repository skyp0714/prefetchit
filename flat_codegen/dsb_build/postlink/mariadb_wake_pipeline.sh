#!/usr/bin/env bash
# MariaDB durable (fsync+binlog) under socialNetwork co-tenant noise, default scheduling (server floats on 0-42):
#   STEP=trace : start server + sysbench, record L2I misses + sched_switch + sys_exit 30 s, build the wake list (warmup/list_mariadb.txt)
#   STEP=ab    : interleaved base / warm64 / warm64_nop (REPS) — metric: sysbench tps and server perf (instr, cycles, L2I)
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; M=/home/hnpark2/prefetchit/benchmarks/mariadb; SOCK=/tmp/mariadb_cold.sock
W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk; SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
SB="oltp_read_write --mysql-socket=$SOCK --mysql-user=root --tables=16 --table-size=200000 --threads=8"
STEP=${STEP:-trace}; REPS=${REPS:-3}; OUT=$PL/results/mariadb_wake; mkdir -p $OUT
start_server(){ local pre=$1; $M/install_base/bin/mariadb-admin --socket=$SOCK -u root shutdown > /dev/null 2>&1; sleep 2
  env ${pre:+LD_PRELOAD=$pre WARMUP_LIST=$PL/warmup/list_mariadb.txt WARMUP_N=${WARM_N:-64} WARMUP_MIN_CYCLES=20000} taskset -c 0-42 $M/install_base/bin/mariadbd --no-defaults --datadir=$M/data --port=3310 --socket=$SOCK --innodb-buffer-pool-size=4G --innodb-flush-log-at-trx-commit=1 --sync-binlog=1 --log-bin=$M/binlog_cold/binlog > $OUT/server.log 2>&1 &
  sleep 6; pgrep -f "[m]ariadbd --no-defaults --datadir=$M/data" | head -1; }
noise_on(){ ( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!; }
noise_off(){ kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done; }
if [[ $STEP == trace ]]; then
  noise_on; pid=$(start_server ""); echo "server pid $pid"
  taskset -c 40-42 sysbench $SB --time=15 run > /dev/null 2>&1
  taskset -c 40-42 sysbench $SB --time=60 run > $OUT/sysbench_trace.log 2>&1 & SP=$!; sleep 10
  echo ps101899 | sudo -S -p '' perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -c 2003 -e sched:sched_switch -e raw_syscalls:sys_exit -p $pid -o $OUT/wake.data -- sleep 30 > $OUT/record.log 2>&1
  echo ps101899 | sudo -S -p '' chmod a+r $OUT/wake.data; echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
  wait $SP; echo ps101899 | sudo -S -p '' perf script -i $OUT/wake.data -F comm,tid,time,event,ip,sym,dso,trace > $OUT/events.txt 2> $OUT/script.err
  MAIN_NAME=mariadbd python3 $PL/wake_lines.py $OUT/events.txt $OUT/maps.txt $PL/warmup/list_mariadb.txt --top 256 | tail -6
  $M/install_base/bin/mariadb-admin --socket=$SOCK -u root shutdown > /dev/null 2>&1; noise_off; echo TRACE_DONE
else
  CSV=$OUT/ab.csv; [[ -f $CSV ]] || echo "arm,rep,tps,instr,cycles,l2i,cs" > $CSV
  noise_on
  for rep in $(seq 1 $REPS); do for arm in base warm64 warm64_nop; do
    pre=; [[ $arm == warm64 ]] && pre=$PL/warmup/libwarmup_host.so; [[ $arm == warm64_nop ]] && pre=$PL/warmup/libwarmup_host_nop.so
    pid=$(start_server "$pre")
    taskset -c 40-42 sysbench $SB --time=15 run > /dev/null 2>&1
    taskset -c 40-42 sysbench $SB --time=50 run > $OUT/sb_${arm}_r${rep}.log 2>&1 & SP=$!; sleep 10
    echo ps101899 | sudo -S -p '' perf stat -x, -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I/',context-switches -p $pid -- sleep 30 2> $OUT/perf_${arm}_r${rep}.txt > /dev/null
    wait $SP; tps=$(grep -E "transactions:" $OUT/sb_${arm}_r${rep}.log | sed -E 's/.*\(([0-9.]+) per sec.*/\1/')
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
    $M/install_base/bin/mariadb-admin --socket=$SOCK -u root shutdown > /dev/null 2>&1; sleep 2
  done; done
  noise_off; echo AB_DONE
fi
