#!/usr/bin/env bash
# Capacity/interleaving-only regime for the databases: server on CORES with deep C-states disabled, client sweep (PG c=4/8/16; MariaDB
# durable rw t=4/8/16), user-mode L2I MPKI / IPC / util per step → c6off_sweep.csv
CORES=${CORES:-4-7}; NC=4; OUT=$1; PG=/home/hnpark2/prefetchit/benchmarks/pg; M=/home/hnpark2/prefetchit/benchmarks/mariadb
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'; [[ -f $OUT ]] || echo "workload,config,cores,clients,tps,util_pct,l2i,instr,cycles,mpki,ipc,lat_ms" > $OUT
rec() { python3 - "$1" "$2" $CORES $NC $3 "$4" $OUT "$5" <<'PY'
import csv,re,sys
wl,cfg,cores,nc,c,tps_lat,out,pf=sys.argv[1:9]; v={}
for r in csv.reader(open(pf)):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
tps,lat=tps_lat.split('/'); i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(30000*int(nc))
open(out,'a').write(f"{wl},{cfg},{cores},{c},{tps},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{lat}\n")
print(f"{wl:26s} {cfg:12s} c={c:>2}: tps={tps} util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} lat={lat}ms")
PY
}
$PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; sleep 2
taskset -c $CORES $PG/install_base/bin/postgres -D $PG/data_scale100 -p 5442 -k /tmp > /tmp/pg_c6off.log 2>&1 & PM=$!; sleep 4
for c in 4 8 16; do PGB="$PG/install_base/bin/pgbench -h /tmp -p 5442 -c $c -j 8 -M prepared bench"; taskset -c 60-67 $PGB -T 8 > /dev/null 2>&1
  taskset -c 60-67 $PGB -T 45 > /tmp/pgb_c6off_$c.log 2>&1 & BP=$!; sleep 6; PIDS=$(pgrep -P $PM | tr '\n' ',' | sed 's/,$//')
  perf stat -x, -o /tmp/c6off_perf.csv -e $EV -p $PIDS -- sleep 30 > /dev/null 2>&1; wait $BP
  tps=$(grep -E "^tps = " /tmp/pgb_c6off_$c.log | tail -1 | sed -E 's/tps = ([0-9.]+).*/\1/' | cut -d. -f1); lat=$(grep -oE "latency average = [0-9.]+" /tmp/pgb_c6off_$c.log | grep -oE "[0-9.]+$"); rec postgresql_tpcb noC6 $c "$tps/$lat" /tmp/c6off_perf.csv; done
$PG/install_base/bin/pg_ctl -D $PG/data_scale100 -m fast stop > /dev/null 2>&1; sleep 2
I=$M/install_base; SOCK=/tmp/mariadb_c6off.sock; SB="--mysql-host=localhost --mysql-socket=$SOCK --mysql-user=root --mysql-db=sbtest --tables=16 --table-size=200000"
taskset -c $CORES $I/bin/mariadbd --no-defaults --datadir=$M/data --port=3404 --socket=$SOCK --innodb-buffer-pool-size=4G --innodb-flush-log-at-trx-commit=1 --max-connections=512 > /tmp/mariadb_c6off.log 2>&1 & SP=$!
for i in $(seq 1 60); do $I/bin/mariadb-admin --socket=$SOCK -u root ping > /dev/null 2>&1 && break; sleep 1; done
for t in 4 8 16; do taskset -c 60-67 sysbench oltp_read_write $SB --threads=$t --time=8 run > /dev/null 2>&1
  taskset -c 60-67 sysbench oltp_read_write $SB --threads=$t --time=45 --report-interval=0 run > /tmp/sb_c6off_$t.log 2>&1 & BP=$!; sleep 6
  perf stat -x, -o /tmp/c6off_perf.csv -e $EV -p $SP -- sleep 30 > /dev/null 2>&1; wait $BP
  tps=$(grep -oE "transactions:\s+[0-9]+\s+\([0-9.]+" /tmp/sb_c6off_$t.log | grep -oE "[0-9.]+$" | cut -d. -f1); lat=$(grep -oE "avg:\s+[0-9.]+" /tmp/sb_c6off_$t.log | grep -oE "[0-9.]+$"); rec mariadb_oltp_rw_durable noC6 $t "$tps/$lat" /tmp/c6off_perf.csv; done
$I/bin/mariadb-admin --socket=$SOCK -u root shutdown > /dev/null 2>&1; sleep 2; kill $SP 2>/dev/null; echo DB_C6OFF_DONE
