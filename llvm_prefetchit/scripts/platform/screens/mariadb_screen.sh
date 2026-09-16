#!/usr/bin/env bash
# MariaDB (system service) + sysbench OLTP: pin mariadbd to SERVER_CORES, sysbench on CLIENT_CORES, perf stat -a -C server cores.
set -euo pipefail
SERVER_CORES="${SERVER_CORES:-50-53}"; CLIENT_CORES="${CLIENT_CORES:-60-63}"; THREADS="${THREADS:-8}"; DUR="${DUR:-60}"; MODE="${MODE:-oltp_read_write}"
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/mariadb_${MODE}; mkdir -p $OUT
echo ps101899 | sudo -S systemctl start mariadb
PID=$(pgrep -x mariadbd | head -1); echo ps101899 | sudo -S taskset -a -cp "$SERVER_CORES" "$PID" > /dev/null
echo ps101899 | sudo -S mysql -e "CREATE DATABASE IF NOT EXISTS sbtest; CREATE USER IF NOT EXISTS 'sb'@'localhost' IDENTIFIED BY 'sb'; GRANT ALL ON sbtest.* TO 'sb'@'localhost'; FLUSH PRIVILEGES;"
C="--mysql-host=localhost --mysql-socket=/run/mysqld/mysqld.sock --mysql-user=sb --mysql-password=sb --mysql-db=sbtest --tables=16 --table-size=200000"
if ! echo ps101899 | sudo -S mysql -e "select count(*) from sbtest.sbtest16" >/dev/null 2>&1; then taskset -c $CLIENT_CORES sysbench $MODE $C prepare > $OUT/prepare.log 2>&1; fi
taskset -c $CLIENT_CORES sysbench $MODE $C --threads=$THREADS --time=15 run > $OUT/warmup.log 2>&1
perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C "$SERVER_CORES" -- \
  taskset -c $CLIENT_CORES sysbench $MODE $C --threads=$THREADS --time=$DUR run > $OUT/run.log 2>&1
python3 - $OUT/perf.csv $OUT/run.log $MODE <<'PY'
import csv,re,sys
perf,log,mode=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
ins,cyc,miss=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
tps=re.search(r"transactions:\s+\d+\s+\(([0-9.]+) per sec",open(log).read())
print(f"mariadb {mode}: tps={tps.group(1) if tps else 'n/a'} L2I MPKI={1000*miss/ins if ins else 0:.2f} IPC={ins/cyc if cyc else 0:.3f} instr={ins/1e9:.1f}G (server cores)")
PY
