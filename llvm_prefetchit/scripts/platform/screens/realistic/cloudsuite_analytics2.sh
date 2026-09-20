#!/usr/bin/env bash
# CloudSuite 4 analytics (batch, JVM): graph-analytics (Spark GraphX, twitter graph), in-memory-analytics (Spark MLlib ALS, movielens),
# data-analytics (Hadoop/Mahout, wikimedia). Each on cores CORES (4) with deep C-states off, one 30 s user-mode window mid-run per container cgroup.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; OUT=$R/cloudsuite_4core.csv; CORES=${CORES:-4-7}; NC=4; D=$R/cloudsuite; mkdir -p $D
NET=cs_net; docker network inspect $NET > /dev/null 2>&1 || docker network create $NET > /dev/null
cst() { local mode=$1 cc; for cc in 4 5 6 7; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cst 0; docker rm -f $(docker ps -aq --filter name=cs-) > /dev/null 2>&1' EXIT; cst 1
measure() { local c=$1 tag=$2 note=$3 id; id=$(docker inspect -f '{{.Id}}' $c 2>/dev/null) || return 1
  docker stats --no-stream --format '{{.CPUPerc}}' $c > $D/an_stats_$tag.txt & local ST=$!
  echo ps101899 | sudo -S -p '' perf stat -x, -o $D/an_perf_$tag.csv -a -C $CORES -e 'cpu/event=0x24,umask=0x24,name=L2I/u' -e instructions:u -e cycles:u -G system.slice/docker-$id.scope,system.slice/docker-$id.scope,system.slice/docker-$id.scope -- sleep ${WIN:-30} > /dev/null 2>&1; wait $ST
  python3 - $tag "$note" $D $OUT $CORES $NC <<'PY'
import csv,sys
tag,note,D,out,cores,nc=sys.argv[1:7]; v={}
for r in csv.reader(open(f'{D}/an_perf_{tag}.csv')):
    for k in ('L2I','instructions:u','cycles:u'):
        if k in r:
            try: v[k]=float(r[0])
            except: pass
cpu=float(open(f'{D}/an_stats_{tag}.txt').read().strip().rstrip('%') or 0); i=v.get('instructions:u',0); cy=v.get('cycles:u',0); m=v.get('L2I',0); util=cpu/int(nc)
open(out,'a').write(f"{tag.split('-t')[0]}-noC6,{tag},{cores},batch,{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f},{note}\n")
print(f"{tag}: util={util:.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/cy if cy else 0:.3f} instr={i/1e9:.1f}G {note}")
PY
}
docker rm -f $(docker ps -aq --filter name=cs-) > /dev/null 2>&1
echo "[$(date +%T)] graph-analytics"; docker create --name cs-twitter cloudsuite/twitter-dataset-graph > /dev/null
docker run -d --name cs-graph --cpuset-cpus $CORES --volumes-from cs-twitter cloudsuite/graph-analytics --driver-memory 16g --executor-memory 16g --master 'local[4]' > /dev/null
for t in 8 20; do sleep $((t==8?8:2)); docker ps -q --filter name=cs-graph --filter status=running | grep -q . || { echo "  graph-analytics ended before ${t}s"; break; }; WIN=10 measure cs-graph graph-analytics-t$t "Spark GraphX PageRank, twitter graph, local[4]"; done
docker logs cs-graph 2>&1 | grep -iE "Executing|Time|Exception" | tail -3 | cut -c1-140; docker rm -f cs-graph cs-twitter > /dev/null 2>&1
echo "[$(date +%T)] data-analytics"; docker create --name cs-wiki cloudsuite/wikimedia-pages-dataset > /dev/null
docker run -d --net $NET --name cs-da-master --hostname data-master --cpuset-cpus $CORES --volumes-from cs-wiki cloudsuite/data-analytics --master --yarn-cores 4 --mapreduce-mem 4096 > /dev/null
docker run -d --net $NET --name cs-da-slave01 --hostname data-slave01 --cpuset-cpus $CORES cloudsuite/data-analytics --slave --master-ip data-master --yarn-cores 4 --mapreduce-mem 4096 > /dev/null; sleep 40
(docker exec cs-da-master benchmark > $D/an_data_analytics.log 2>&1 &) ; sleep 90
for t in 90 210; do [[ $t == 210 ]] && sleep 120; docker exec cs-da-master pgrep -f "mahout|MRAppMaster|YarnChild|RunJar" > /dev/null 2>&1 || { echo "  data-analytics job not running at ${t}s"; }; measure cs-da-master data-analytics-master-t$t "Hadoop/Mahout Bayes, wikimedia (master container)"; measure cs-da-slave01 data-analytics-slave-t$t "Hadoop/Mahout Bayes, wikimedia (slave container)"; done
tail -3 $D/an_data_analytics.log | cut -c1-140; docker rm -f cs-da-master cs-da-slave01 cs-wiki > /dev/null 2>&1
cst 0; echo "[$(date +%T)] CS_ANALYTICS2_DONE"
