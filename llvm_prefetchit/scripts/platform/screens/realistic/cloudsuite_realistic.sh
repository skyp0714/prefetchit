#!/usr/bin/env bash
# CloudSuite 4 realistic screens: server containers pinned to CORES (4), clients on 60-67, load raised to the server's knee;
# per benchmark: server util, user-mode L2I MPKI / IPC of the server container (cgroup), client-reported throughput.
# Usage: cloudsuite_realistic.sh OUT.csv data-caching|web-serving|media-streaming|web-search|data-serving
OUT=$1; B=$2; CORES=${CORES:-4-7}; NC=4; D=$(dirname $OUT)/cloudsuite; mkdir -p $D; [[ -f $OUT ]] || echo "bench,server,cores,load,util_pct,l2i,instr,cycles,mpki,ipc,note" > $OUT
NET=cs_net; docker network inspect $NET > /dev/null 2>&1 || docker network create $NET > /dev/null
measure() { # $1 container $2 load-label $3 note ; 30 s cgroup perf of the container on its cpuset
  local c=$1 id=$(docker inspect -f '{{.Id}}' $1); local cs=$(docker inspect -f '{{.HostConfig.CpusetCpus}}' $1)
  docker stats --no-stream --format '{{.CPUPerc}}' $c > $D/stats_$B.txt 2>/dev/null &
  echo ps101899 | sudo -S -p '' perf stat -x, -o $D/perf_${B}_$2.csv -a -C ${cs:-0-85} -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$id.scope,system.slice/docker-$id.scope,system.slice/docker-$id.scope -- sleep 30 > /dev/null 2>&1; wait
  python3 - $B $c $cs $2 "$3" $D/perf_${B}_$2.csv $D/stats_$B.txt $OUT $NC <<'PY'
import csv,sys
b,c,cs,load,note,perf,stats,out,nc=sys.argv[1:10]; v={}
for r in csv.reader(open(perf)):
    if len(r)>=3:
        for k in ('L2I','instructions:u','cycles:u'):
            if k in r:
                try: v[k]=float(r[0])
                except: pass
cpu=float(open(stats).read().strip().rstrip('%') or 0); i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); util=cpu/int(nc)
open(out,'a').write(f"{b},{c},{cs},{load},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{note}\n")
print(f"{b} [{load}]: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} instr={i/1e9:.1f}G {note}")
PY
}
cleanup() { docker rm -f $(docker ps -aq --filter name=cs-) > /dev/null 2>&1; }
case $B in
data-caching)
  cleanup; docker run -d --name cs-dc-server --net $NET --cpuset-cpus $CORES cloudsuite/data-caching:server -t $NC -m 4096 -n 550 > /dev/null; sleep 3
  docker run -d --name cs-dc-client --net $NET --cpuset-cpus 60-67 cloudsuite/data-caching:client /bin/bash -c "sleep 100000" > /dev/null; sleep 2
  docker exec cs-dc-client bash -c 'cd /usr/src/memcached/memcached_client/ && echo "cs-dc-server, 11211" > docker_servers.txt && ./loader -a ../twitter_dataset/twitter_dataset_unscaled -o ../twitter_dataset/twitter_dataset_30x -s docker_servers.txt -w 4 -S 30 -D 4096 -j -T 1' > $D/dc_warm.log 2>&1; tail -1 $D/dc_warm.log | cut -c1-120
  for rps in 100000 200000 400000 800000; do
    docker exec cs-dc-client bash -c "cd /usr/src/memcached/memcached_client/ && timeout 70 ./loader -a ../twitter_dataset/twitter_dataset_30x -s docker_servers.txt -g 0.8 -T 1 -c 200 -w 8 -e -r $rps" > $D/dc_run_$rps.log 2>&1 & LP=$!; sleep 20
    measure cs-dc-server rps$rps "$(grep -oE 'rps[ =:]+[0-9.]+' $D/dc_run_$rps.log | tail -1)"; wait $LP; grep -E "rps|latency|ms" $D/dc_run_$rps.log | tail -2 | cut -c1-140
    u=$(tail -1 $OUT | cut -d, -f5); [[ ${u%.*} -ge 85 ]] && { echo "knee at $rps"; break; }
  done; cleanup;;
web-serving)
  cleanup; docker run -d --name cs-ws-db --net $NET --cpuset-cpus 12-15 cloudsuite/web-serving:db_server > /dev/null
  docker run -d --name cs-ws-mc --net $NET --cpuset-cpus 16-17 cloudsuite/web-serving:memcached_server -m 4096 -t 2 > /dev/null; sleep 5
  docker run -d --name cs-ws-web --net $NET --cpuset-cpus $CORES cloudsuite/web-serving:web_server /etc/bootstrap.sh http cs-ws-web cs-ws-db cs-ws-mc 8 4 > /dev/null; sleep 60
  docker logs cs-ws-web 2>&1 | tail -2 | cut -c1-120
  for scale in 50 100 200 400; do
    docker run --rm --name cs-ws-faban --net $NET --cpuset-cpus 60-67 cloudsuite/web-serving:faban_client cs-ws-web $scale --oper=run --ramp-up=30 --steady=60 --ramp-down=10 > $D/ws_$scale.log 2>&1 & LP=$!; sleep 60
    measure cs-ws-web scale$scale "$(grep -oE 'ops/sec[^,]*' $D/ws_$scale.log | tail -1)"; wait $LP; grep -iE "ops/sec|passed|failed" $D/ws_$scale.log | tail -3 | cut -c1-140
    u=$(tail -1 $OUT | cut -d, -f5); [[ ${u%.*} -ge 85 ]] && { echo "knee at $scale"; break; }
  done; cleanup;;
media-streaming)
  cleanup; docker create --name cs-ms-dataset cloudsuite/media-streaming:dataset > /dev/null
  docker run -d --name cs-ms-server --net $NET --cpuset-cpus $CORES --volumes-from cs-ms-dataset cloudsuite/media-streaming:server 4000 > /dev/null; sleep 8
  for sess in 100 400 1000 2500; do
    docker run --rm --name cs-ms-client --net $NET --cpuset-cpus 60-67 --volumes-from cs-ms-dataset -v $D/ms_out_$sess:/output cloudsuite/media-streaming:client cs-ms-server 4 $sess 10 PT > $D/ms_$sess.log 2>&1 & LP=$!; sleep 40
    measure cs-ms-server sess$sess "sessions=$sess"; wait $LP; tail -2 $D/ms_$sess.log | cut -c1-140
    u=$(tail -1 $OUT | cut -d, -f5); [[ ${u%.*} -ge 85 ]] && { echo "knee at $sess"; break; }
  done; cleanup;;
web-search)
  cleanup; docker run -d --name cs-wsrch-server --net $NET --cpuset-cpus $CORES cloudsuite/web-search:server 12g 1 > /dev/null; sleep 90; docker logs cs-wsrch-server 2>&1 | tail -2 | cut -c1-120
  for w in 25 50 100 200; do
    docker run --rm --name cs-wsrch-client --net $NET --cpuset-cpus 60-67 cloudsuite/web-search:client cs-wsrch-server $w --ramp-up 20 --steady 60 --ramp-down 5 > $D/wsrch_$w.log 2>&1 & LP=$!; sleep 45
    measure cs-wsrch-server w$w "workers=$w"; wait $LP; grep -iE "ops/sec|throughput|p99|passed" $D/wsrch_$w.log | tail -3 | cut -c1-140
    u=$(tail -1 $OUT | cut -d, -f5); [[ ${u%.*} -ge 85 ]] && { echo "knee at $w"; break; }
  done; cleanup;;
data-serving)
  cleanup; docker run -d --name cs-ds-server --net $NET --cpuset-cpus $CORES cloudsuite/data-serving:server --writer-count 32 --reader-count 16 --heap-size 8 > /dev/null; sleep 60
  docker run -d --name cs-ds-client --net $NET --cpuset-cpus 60-67 cloudsuite/data-serving:client bash -c "sleep 100000" > /dev/null; sleep 2
  docker exec cs-ds-client bash -c 'ls /; cat /load.sh 2>/dev/null | head -20; ls /run 2>/dev/null' > $D/ds_client_inspect.txt 2>&1
  docker exec cs-ds-client bash -c 'cd / && ./load.sh cs-ds-server' > $D/ds_load.log 2>&1; tail -2 $D/ds_load.log | cut -c1-120
  for th in 8 16 32 64; do
    docker exec cs-ds-client bash -c "cd / && timeout 120 ./run.sh cs-ds-server $th 2>&1 || timeout 120 ./run.sh cs-ds-server" > $D/ds_run_$th.log 2>&1 & LP=$!; sleep 40
    measure cs-ds-server th$th "threads=$th"; wait $LP; grep -iE "Throughput|99thPercentile" $D/ds_run_$th.log | head -3 | cut -c1-140
    u=$(tail -1 $OUT | cut -d, -f5); [[ ${u%.*} -ge 85 ]] && { echo "knee at $th"; break; }
  done; cleanup;;
esac; echo CLOUDSUITE_${B}_DONE
