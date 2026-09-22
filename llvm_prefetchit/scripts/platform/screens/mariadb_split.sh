#!/usr/bin/env bash
# user vs kernel L2I misses of the self-built MariaDB under two configs (durable = package-like; fast = our pipeline config)
set -u
M=/home/hnpark2/prefetchit/benchmarks/mariadb; I=$M/install_base; DATA=$M/data; SOCK=/tmp/mariadb_pipe.sock; PORT=3400
SERVER_CORES=64-67; CLIENT_CORES=68-71
SB="--mysql-host=localhost --mysql-socket=$SOCK --mysql-user=root --mysql-db=sbtest --tables=16 --table-size=200000"
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/mariadb_20260916/split; mkdir -p $OUT
run(){ local label=$1; shift
  taskset -c $SERVER_CORES $I/bin/mariadbd --no-defaults --datadir=$DATA --port=$PORT --socket=$SOCK --innodb-buffer-pool-size=4G --max-connections=64 --skip-name-resolve "$@" > $OUT/server_$label.log 2>&1 &
  for i in $(seq 1 60); do $I/bin/mariadb-admin --socket=$SOCK -u root ping >/dev/null 2>&1 && break; sleep 1; done
  taskset -c $CLIENT_CORES sysbench oltp_read_write $SB --threads=8 --time=10 run > /dev/null 2>&1
  perf stat -x, -o $OUT/$label.csv -e instructions:u,instructions:k,'cpu/event=0x24,umask=0x24,name=L2I_MISS_U/u','cpu/event=0x24,umask=0x24,name=L2I_MISS_K/k' -a -C $SERVER_CORES -- \
    taskset -c $CLIENT_CORES sysbench oltp_read_write $SB --threads=8 --time=40 run > $OUT/$label.sysbench.log 2>&1
  $I/bin/mariadb-admin --socket=$SOCK -u root shutdown >/dev/null 2>&1; sleep 2
  python3 - $OUT/$label.csv $OUT/$label.sysbench.log $label <<'PY'
import csv,re,sys
perf,log,label=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
iu,ik,mu,mk=ev.get("instructions:u",0),ev.get("instructions:k",0),ev.get("L2I_MISS_U",0),ev.get("L2I_MISS_K",0)
tps=re.search(r"transactions:\s+\d+\s+\(([0-9.]+) per sec",open(log).read())
print(f"{label}: tps={tps.group(1) if tps else 'n/a'} user MPKI={1000*mu/iu if iu else 0:.2f} kernel MPKI(per kernel instr)={1000*mk/ik if ik else 0:.2f} total MPKI={1000*(mu+mk)/(iu+ik) if iu+ik else 0:.2f} kernel instr share={ik/(iu+ik) if iu+ik else 0:.1%}")
PY
}
run fast --innodb-flush-log-at-trx-commit=0 --skip-log-bin --innodb-flush-method=O_DIRECT
run durable --innodb-flush-log-at-trx-commit=1 --log-bin=mariadb-bin --sync-binlog=1 --innodb-flush-method=fsync
echo SPLIT_DONE
