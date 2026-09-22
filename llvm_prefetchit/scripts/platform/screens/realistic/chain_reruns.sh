#!/usr/bin/env bash
# Reruns: DaCapo fop (-n 500), kafka (-n 500, C6 off) and h2o (JDK 17) on cores 8-11, C6 off; then mediaMicroservices in the 16-core
# interleaving pool at 2000/3000 req/s with a 0.1% error tolerance (C6 off on 0-15).
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; DSB=/home/hnpark2/prefetchit/benchmarks/DeathStarBench
cst() { local mode=$1 cc; shift; for cc in "$@"; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cst 0 $(seq 0 15)' EXIT; cst 1 8 9 10 11
DACAPO=/home/hnpark2/prefetchit/benchmarks/tools/dacapo/dacapo-23.11-MR2-chopin.jar; SCR=/tmp/jvm_rerun; mkdir -p $SCR
runj() { local b=$1 jdk=$2 n=$3 fl=$4; mkdir -p $SCR/s_$b
  taskset -c 8-11 $jdk/bin/java -Xms8g -Xmx8g -XX:ActiveProcessorCount=4 $fl -jar $DACAPO $b -n $n --scratch-directory $SCR/s_$b > $SCR/$b.log 2>&1 & local jp=$!; sleep 40
  if ! kill -0 $jp 2>/dev/null; then echo "dacapo/$b ($(basename $jdk)): ended before 40 s"; tail -2 $SCR/$b.log | cut -c1-140; return; fi
  perf stat -x, -o /tmp/rerun_perf.csv -e 'cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock' -p $jp -- sleep 20 > /dev/null 2>&1; kill $jp 2>/dev/null; sleep 1; kill -9 $jp 2>/dev/null
  python3 - $b $(basename $jdk) <<'PY'
import csv,sys; v={}
for r in csv.reader(open('/tmp/rerun_perf.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0)
open('/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918/cause_diag.csv','a').write(f"dacapo/{sys.argv[1]},noC6_{sys.argv[2]},8-11,{100*t/(20000*4):.1f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{i:.0f}\n")
print(f"dacapo/{sys.argv[1]} ({sys.argv[2]}, C6 off, 4 cores): util={100*t/(20000*4):.0f}% MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
PY
  rm -rf $SCR/s_$b; }
runj fop /usr/lib/jvm/java-21-openjdk-amd64 500 ""
runj kafka /usr/lib/jvm/java-21-openjdk-amd64 500 ""
runj h2o /home/hnpark2/prefetchit/benchmarks/tools/jdk17 30 ""
runj cassandra /home/hnpark2/prefetchit/benchmarks/tools/jdk17 30 "-Djava.security.manager=allow"
cst 0 8 9 10 11
echo "[$(date +%T)] media pool 0-15, C6 off, 2000/3000"; cst 1 $(seq 0 15); (cd $DSB/mediaMicroservices && docker compose up -d > /dev/null 2>&1); sleep 30
(cd $DSB/mediaMicroservices/scripts && timeout 600 python3 write_movie_info.py -c ../datasets/tmdb/casts.json -m ../datasets/tmdb/movies.json --server_address http://localhost:8080 > /dev/null 2>&1; timeout 300 bash register_users.sh > /dev/null 2>&1; timeout 300 bash register_movies.sh > /dev/null 2>&1)
sed 's/sys.exit(1 if (bad>0 or p99>200/sys.exit(1 if (bad>0.001*rps*30 or p99>200/' $R/dsb_shared_screen.sh > /tmp/dsb_shared_tol.sh
PREFIX=mediamicroservices URL=http://localhost:8080/wrk2-api/review/compose LUA=$R/media_compose_review.lua POOL=0-15 timeout 900 bash /tmp/dsb_shared_tol.sh $R/c6off_shared.csv 2000 3000 2>&1 | grep -vE "^\s*$" | cut -c1-160
(cd $DSB/mediaMicroservices && docker compose down > /dev/null 2>&1); cst 0 $(seq 0 15); echo "[$(date +%T)] RERUNS_DONE"
