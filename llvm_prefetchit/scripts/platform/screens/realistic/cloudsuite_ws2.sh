#!/usr/bin/env bash
# CloudSuite web-serving, corrected: server containers started with -it (their entrypoints end in an interactive shell), web server on
# CORES with 8 php-fpm children / 4 nginx workers, faban client scale sweep; per step: web-server util, user-mode L2I MPKI / IPC, faban ops/s.
OUT=$1; CORES=${CORES:-4-7}; NC=4; D=$(dirname $OUT)/cloudsuite; mkdir -p $D; NET=cs_net; docker network inspect $NET > /dev/null 2>&1 || docker network create $NET > /dev/null
docker rm -f cs-ws-faban cs-ws-web cs-ws-db cs-ws-mc > /dev/null 2>&1
docker run -d -it --name cs-ws-db --net $NET --cpuset-cpus 12-15 cloudsuite/web-serving:db_server > /dev/null
docker run -d --name cs-ws-mc --net $NET --cpuset-cpus 16-17 cloudsuite/web-serving:memcached_server -m 4096 -t 2 > /dev/null; sleep 8
docker run -d -it --name cs-ws-web --net $NET --cpuset-cpus $CORES cloudsuite/web-serving:web_server /etc/bootstrap.sh http cs-ws-web cs-ws-db cs-ws-mc 8 4 > /dev/null; sleep 45
docker exec cs-ws-web sh -c 'curl -sI http://localhost:8080 | head -1'; id=$(docker inspect -f '{{.Id}}' cs-ws-web)
for scale in 25 50 100 200 400; do
  docker run --rm --name cs-ws-faban --net $NET --cpuset-cpus 60-67 cloudsuite/web-serving:faban_client cs-ws-web $scale --oper=run --ramp-up=30 --steady=60 --ramp-down=10 > $D/ws2_$scale.log 2>&1 & LP=$!; sleep 60
  docker stats --no-stream --format '{{.CPUPerc}}' cs-ws-web > $D/ws2_stats_$scale.txt &
  echo ps101899 | sudo -S -p '' perf stat -x, -o $D/ws2_perf_$scale.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$id.scope,system.slice/docker-$id.scope,system.slice/docker-$id.scope -- sleep 30 > /dev/null 2>&1; wait $LP 2>/dev/null
  python3 - $scale $D $OUT $CORES $NC <<'PY'
import csv,sys,re
sc,D,out,cores,nc=sys.argv[1:6]; v={}
for r in csv.reader(open(f'{D}/ws2_perf_{sc}.csv')):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
cpu=float(open(f'{D}/ws2_stats_{sc}.txt').read().strip().rstrip('%') or 0); i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); util=cpu/int(nc)
log=open(f'{D}/ws2_{sc}.log').read(); ops=re.findall(r'ops/sec[^\n]*',log); note=(ops[-1][:60] if ops else 'no ops/sec line').replace(',',';')
open(out,'a').write(f"web-serving,cs-ws-web,{cores},scale{sc},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{note}\n")
print(f"web-serving scale={sc}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} instr={i/1e9:.1f}G {note}")
sys.exit(1 if util>=85 else 0)
PY
  [[ $? -ne 0 ]] && { echo "knee at $scale"; break; }
done; docker rm -f cs-ws-faban cs-ws-web cs-ws-db cs-ws-mc > /dev/null 2>&1; echo CS_WS2_DONE
