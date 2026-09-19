#!/usr/bin/env bash
# CloudSuite data-caching, corrected client usage (entrypoint modes): server memcached on CORES (4 threads), client in bash mode,
# scale+warm-up, then RPS sweep; per step: server util, user-mode L2I MPKI / IPC (cgroup), client-reported rps / latency.
OUT=$1; CORES=${CORES:-4-7}; NC=4; D=$(dirname $OUT)/cloudsuite; mkdir -p $D; NET=cs_net; docker network inspect $NET > /dev/null 2>&1 || docker network create $NET > /dev/null
docker rm -f cs-dc-server cs-dc-client > /dev/null 2>&1
docker run -d --name cs-dc-server --net $NET --cpuset-cpus $CORES cloudsuite/data-caching:server -t $NC -m 4096 -n 550 > /dev/null; sleep 3
docker run -d -it --name cs-dc-client --net $NET --cpuset-cpus 60-67 cloudsuite/data-caching:client --m=bash > /dev/null; sleep 2
docker exec cs-dc-client bash -c 'mkdir -p /usr/src/memcached/memcached_client/docker_servers && echo "cs-dc-server, 11211" > /usr/src/memcached/memcached_client/docker_servers/docker_servers.txt'
echo "[$(date +%T)] scale + warm-up"; docker exec cs-dc-client /entrypoint.sh '--m=S&W' --S=30 --w=4 --D=4096 --T=1 > $D/dc2_warm.log 2>&1; tail -1 $D/dc2_warm.log | cut -c1-140
id=$(docker inspect -f '{{.Id}}' cs-dc-server)
for rps in 100000 200000 400000 700000 1000000; do
  docker exec cs-dc-client /entrypoint.sh --m=RPS --S=30 --w=8 --c=200 --g=0.8 --T=1 --r=$rps > $D/dc2_run_$rps.log 2>&1 & LP=$!; sleep 20   # loader has no duration: killed after the measurement
  docker stats --no-stream --format '{{.CPUPerc}}' cs-dc-server > $D/dc2_stats_$rps.txt & ST=$!
  echo ps101899 | sudo -S -p '' perf stat -x, -o $D/dc2_perf_$rps.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$id.scope,system.slice/docker-$id.scope,system.slice/docker-$id.scope -- sleep 30 > /dev/null 2>&1; wait $ST   # NOT a bare wait: the loader never exits
  docker exec cs-dc-client bash -c 'kill -9 $(pidof loader) 2>/dev/null; true' > /dev/null 2>&1; sleep 2   # the client image has no pkill; loader runs until killed
  python3 - $rps $D $OUT $CORES $NC <<'PY'
import csv,sys,re
rps,D,out,cores,nc=sys.argv[1:6]; v={}
for r in csv.reader(open(f'{D}/dc2_perf_{rps}.csv')):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
cpu=float(open(f'{D}/dc2_stats_{rps}.txt').read().strip().rstrip('%') or 0); i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); util=cpu/int(nc)
log=open(f'{D}/dc2_run_{rps}.log').read(); last=[l for l in log.splitlines() if re.search(r'\d',l)][-3:]
open(out,'a').write(f"data-caching,cs-dc-server,{cores},rps{rps},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{' | '.join(x.strip()[:60] for x in last).replace(',',';')}\n")
print(f"data-caching rps={rps}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} instr={i/1e9:.1f}G | "+' | '.join(x.strip()[:70] for x in last))
sys.exit(1 if util>=85 else 0)
PY
  [[ $? -ne 0 ]] && { echo "knee at $rps"; break; }
done; docker rm -f cs-dc-server cs-dc-client > /dev/null 2>&1; echo CS_DC2_DONE
