#!/usr/bin/env bash
# Corrected CloudSuite web-search (wait for the Solr collection before the client) and data-serving (YCSB warm-up + target-rate sweep).
# Usage: cloudsuite_fix2.sh OUT.csv web-search|data-serving
OUT=$1; B=$2; CORES=${CORES:-4-7}; NC=4; D=$(dirname $OUT)/cloudsuite; mkdir -p $D; NET=cs_net; docker network inspect $NET > /dev/null 2>&1 || docker network create $NET > /dev/null
measure() { local c=$1 tag=$2 note=$3 id=$(docker inspect -f '{{.Id}}' $1)
  docker stats --no-stream --format '{{.CPUPerc}}' $c > $D/${B}2_stats_$tag.txt &
  echo ps101899 | sudo -S -p '' perf stat -x, -o $D/${B}2_perf_$tag.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$id.scope,system.slice/docker-$id.scope,system.slice/docker-$id.scope -- sleep 30 > /dev/null 2>&1; wait
  python3 - $B $c $CORES $tag "$note" $D $OUT $NC <<'PY'
import csv,sys
b,c,cores,tag,note,D,out,nc=sys.argv[1:9]; v={}
for r in csv.reader(open(f'{D}/{b}2_perf_{tag}.csv')):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
cpu=float(open(f'{D}/{b}2_stats_{tag}.txt').read().strip().rstrip('%') or 0); i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); util=cpu/int(nc)
open(out,'a').write(f"{b},{c},{cores},{tag},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{note.replace(',',';')}\n")
print(f"{b} [{tag}]: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} instr={i/1e9:.1f}G {note}")
sys.exit(1 if util>=85 else 0)
PY
}
case $B in
web-search)
  docker rm -f cs-wsrch-server cs-wsrch-client > /dev/null 2>&1
  docker run -d --name cs-wsrch-server --net $NET --cpuset-cpus $CORES cloudsuite/web-search:server 12g 1 > /dev/null
  for i in $(seq 1 60); do docker logs cs-wsrch-server 2>&1 | grep -qiE "Created collection|collection.*created|Web search server is running|ready" && break; sleep 5; done; docker logs cs-wsrch-server 2>&1 | tail -2 | cut -c1-140; sleep 20
  for w in 25 50 100 200 400; do
    docker run --rm --name cs-wsrch-client --net $NET --cpuset-cpus 60-67 cloudsuite/web-search:client cs-wsrch-server $w --ramp-up 30 --steady 90 --ramp-down 5 > $D/wsrch2_$w.log 2>&1 & LP=$!; sleep 60
    measure cs-wsrch-server w$w "workers=$w $(grep -c 'SEVERE' $D/wsrch2_$w.log) errors"; wait $LP 2>/dev/null; grep -iE "ops/sec|passed" $D/wsrch2_$w.log | tail -2 | cut -c1-120
    [[ $(tail -1 $OUT | cut -d, -f5 | cut -d. -f1) -ge 85 ]] && { echo "knee at $w"; break; }
  done; docker rm -f cs-wsrch-server > /dev/null 2>&1;;
data-serving)
  docker rm -f cs-ds-server cs-ds-client > /dev/null 2>&1
  docker run -d --name cs-ds-server --net $NET --cpuset-cpus $CORES cloudsuite/data-serving:server --writer-count 32 --reader-count 16 --heap-size 8 > /dev/null
  for i in $(seq 1 40); do docker logs cs-ds-server 2>&1 | grep -q "Created default superuser" && break; sleep 5; done; sleep 10
  docker run -d -it --name cs-ds-client --net $NET --cpuset-cpus 60-67 --entrypoint bash cloudsuite/data-serving:client > /dev/null; sleep 2
  echo "[$(date +%T)] warm-up (1M records)"; docker exec cs-ds-client bash -c 'cd / && ./warmup.sh cs-ds-server 1000000 16' > $D/ds2_warm.log 2>&1; tail -2 $D/ds2_warm.log | cut -c1-120
  for rate in 5000 10000 20000 40000 80000; do
    docker exec cs-ds-client bash -c "cd / && ./load.sh cs-ds-server 1000000 $rate 32 $((rate*70))" > $D/ds2_run_$rate.log 2>&1 & LP=$!; sleep 25
    measure cs-ds-server rps$rate "target=$rate/s"; wait $LP 2>/dev/null; grep -E "Throughput|99thPercentile" $D/ds2_run_$rate.log | head -3 | tr '\n' ' ' | cut -c1-160; echo
    [[ $(tail -1 $OUT | cut -d, -f5 | cut -d. -f1) -ge 85 ]] && { echo "knee at $rate"; break; }
  done; docker rm -f cs-ds-server cs-ds-client > /dev/null 2>&1;;
esac; echo CS_${B}_FIX2_DONE
