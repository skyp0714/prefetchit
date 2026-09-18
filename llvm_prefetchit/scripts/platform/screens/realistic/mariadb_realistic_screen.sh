#!/usr/bin/env bash
# MariaDB 10.11 realistic screen: server pinned to CORES (4), sysbench on 60-67, thread sweep; configs: durable (defaults,
# innodb_flush_log_at_trx_commit=1) and fast (=0); workloads oltp_read_write and oltp_read_only. Per step: tps, user-mode L2I MPKI/IPC, util.
CORES=${CORES:-4-7}; NC=4; OUT=$1; M=/home/hnpark2/prefetchit/benchmarks/mariadb; I=$M/install_base; DATA=$M/data; SOCK=/tmp/mariadb_real.sock; PORT=3401
SB="--mysql-host=localhost --mysql-socket=$SOCK --mysql-user=root --mysql-db=sbtest --tables=16 --table-size=200000"
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'; [[ -f $OUT ]] || echo "workload,config,cores,clients,tps,util_pct,l2i,instr,cycles,mpki,ipc,lat_ms" > $OUT
stop(){ $I/bin/mariadb-admin --socket=$SOCK -u root shutdown > /dev/null 2>&1; sleep 2; for p in $(pgrep -f "^$I/bin/mariadbd .*--port=$PORT"); do kill $p; done; sleep 1; }
for cfg in durable fast; do
  stop; flush=1; [[ $cfg == fast ]] && flush=0
  taskset -c $CORES $I/bin/mariadbd --no-defaults --datadir=$DATA --port=$PORT --socket=$SOCK --innodb-buffer-pool-size=4G --innodb-flush-log-at-trx-commit=$flush --max-connections=512 > /tmp/mariadb_real_$cfg.log 2>&1 & SP=$!
  for i in $(seq 1 60); do $I/bin/mariadb-admin --socket=$SOCK -u root ping > /dev/null 2>&1 && break; sleep 1; done
  for wl in oltp_read_write oltp_read_only; do for t in 4 8 16 32 64; do
    taskset -c 60-67 sysbench $wl $SB --threads=$t --time=10 run > /dev/null 2>&1
    taskset -c 60-67 sysbench $wl $SB --threads=$t --time=45 --report-interval=0 run > /tmp/sb_${cfg}_${wl}_$t.log 2>&1 & BP=$!; sleep 8
    perf stat -x, -o /tmp/mdb_perf.csv -e $EV -p $SP -- sleep 30 > /dev/null 2>&1; wait $BP
    python3 - $wl $cfg $CORES $NC $t $OUT <<'PY'
import csv,re,sys
wl,cfg,cores,nc,t,out=sys.argv[1:7]; v={}
for r in csv.reader(open('/tmp/mdb_perf.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
w=open(f'/tmp/sb_{cfg}_{wl}_{t}.log').read(); tps=re.search(r'transactions:\s+\d+\s+\(([0-9.]+) per sec',w); tps=float(tps.group(1)) if tps else 0; lat=re.search(r'avg:\s+([0-9.]+)',w); lat=float(lat.group(1)) if lat else 0
i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); tc=v.get('task-clock',0); util=100*tc/(30000*int(nc))
open(out,'a').write(f"mariadb_{wl},{cfg},{cores},{t},{tps:.0f},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{lat:.2f}\n")
print(f"mariadb {wl} {cfg} t={t}: tps={tps:.0f} util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} lat={lat:.2f}ms")
PY
  done; done
done; stop; echo MARIADB_SCREEN_DONE
