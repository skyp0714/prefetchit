#!/usr/bin/env bash
# B-class (interleaving) check for the two new server candidates: ScyllaDB and MySQL 8 share one 4-core cpuset (C6 off) and are driven
# at the same time at rates that, alone, leave each well below saturation. Per-container user-mode L2I MPKI is compared with the alone
# values from services.csv. This is the datacenter colocation regime, not an artificial single-thread pile-up.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/newcands_20260921; OUT=$R/services.csv; POOL=${POOL:-8-11}; WIN=${WIN:-20}
SIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cs-scylla); MIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cs-mysql)
CL=$(python3 -c "import re;s='$POOL';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))")
NC=$(echo $CL | wc -w)
cst() { local mode=$1 cc; for cc in $CL; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cst 0; docker update --cpuset-cpus 4-7 cs-mysql > /dev/null 2>&1' EXIT; cst 1
echo "[$(date +%T)] both services onto $POOL"; docker update --cpuset-cpus $POOL cs-mysql > /dev/null; docker update --cpuset-cpus $POOL cs-scylla > /dev/null; sleep 10
timeout 220 docker run --rm --net cs_net --cpuset-cpus 60-63 --entrypoint /ycsb/bin/ycsb.sh cloudsuite/data-serving:client run cassandra-cql -p hosts=$SIP -P /ycsb/workloads/workloada -p recordcount=1000000 -p operationcount=100000000 -p maxexecutiontime=150 -s -threads 8 -target 20000 > $R/logs/coloc_ycsb.log 2>&1 & YP=$!
timeout 220 taskset -c 64-67 sysbench oltp_read_write --mysql-host=$MIP --mysql-user=root --mysql-password=root --mysql-db=sbtest --tables=16 --table-size=200000 --threads=8 --time=150 --rate=400 run > $R/logs/coloc_sysbench.log 2>&1 & SP=$!
sleep 40
for c in cs-scylla cs-mysql; do ID=$(docker inspect -f '{{.Id}}' $c)
  docker stats --no-stream --format '{{.CPUPerc}}' $c > /tmp/coloc_cpu.txt 2>/dev/null & DS=$!
  echo ps101899 | sudo -S -p '' perf stat -x, -o /tmp/coloc_perf.csv -a -C $POOL -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$ID.scope,system.slice/docker-$ID.scope,system.slice/docker-$ID.scope -- sleep $WIN > /dev/null 2>&1; wait $DS
  python3 - "$c" $POOL $NC $WIN /tmp/coloc_perf.csv /tmp/coloc_cpu.txt $OUT <<'PY'
import csv,sys
cont,pool,nc,win,pf,cf,out=sys.argv[1:8]; v={}
for r in csv.reader(open(pf)):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
try: cpu=float(open(cf).read().strip().rstrip('%'))
except: cpu=0.0
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); name={'cs-scylla':'scylla','cs-mysql':'mysql8'}[cont]
open(out,'a').write(f"{name},interleaved_noC6,{pool},coloc,{cpu/int(nc):.1f},{m:.0f},{i:.0f},{c:.0f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},scylla YCSB 20k + mysql sysbench 400/s on the same {nc} cores\n")
print(f"  {name} [interleaved]: util={cpu/int(nc):.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
done
timeout 260 tail --pid=$YP -f /dev/null; timeout 60 tail --pid=$SP -f /dev/null
grep -aE "^\[OVERALL\], Throughput" $R/logs/coloc_ycsb.log | tail -1 | cut -c1-70; grep -aE "transactions:|queries:" $R/logs/coloc_sysbench.log | head -2 | cut -c1-70
docker update --cpuset-cpus 4-7 cs-mysql > /dev/null; cst 0; echo "[$(date +%T)] COLOC_DONE"
