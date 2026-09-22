#!/usr/bin/env bash
# ScyllaDB (C++/Seastar) single node pinned to cores 50-53; cassandra-stress from a second container on 60-63; perf stat -a -C 50-53
set -u
true
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/scylla; mkdir -p $OUT
docker rm -f scylla scylla-stress > /dev/null 2>&1
docker run -d --name scylla --cpuset-cpus 50-53 --memory 16g scylladb/scylla:6.2 --smp 4 --memory 6G --overprovisioned 1 --developer-mode 1 --reactor-backend epoll > $OUT/run.log 2>&1
for i in $(seq 1 60); do docker exec scylla nodetool status 2>/dev/null | grep -q "^UN" && break; sleep 5; done
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' scylla); echo "scylla up at $IP"
docker run --rm --cpuset-cpus 60-63 scylladb/scylla:6.2 cassandra-stress write n=1500000 -rate threads=32 -node $IP > $OUT/stress_write.log 2>&1
docker run --rm --cpuset-cpus 60-63 scylladb/scylla:6.2 cassandra-stress mixed duration=15s -rate threads=32 -node $IP > $OUT/stress_warm.log 2>&1
perf stat -x, -o $OUT/perf.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C 50-53 -- \
  docker run --rm --cpuset-cpus 60-63 scylladb/scylla:6.2 cassandra-stress mixed duration=60s -rate threads=32 -node $IP > $OUT/stress_mixed.log 2>&1
python3 - $OUT/perf.csv $OUT/stress_mixed.log <<'PY'
import csv,re,sys
perf,log=sys.argv[1:]; ev={}
for row in csv.reader(open(perf)):
    if len(row)>=3:
        try: ev[row[2]]=float(row[0])
        except ValueError: pass
i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
ops=re.search(r"Op rate\s*:\s*([0-9,]+)",open(log).read())
print(f"scylla mixed: ops/s={ops.group(1) if ops else 'n/a'} L2I MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G (cores 50-53)")
PY
docker rm -f scylla > /dev/null 2>&1; echo SCYLLA_DONE
