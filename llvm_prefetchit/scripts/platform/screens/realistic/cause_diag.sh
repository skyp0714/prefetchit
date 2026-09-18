#!/usr/bin/env bash
# Miss-cause diagnostic for the candidates: same pinned cores, three configs — default / deep C-states off / C-states off + one core.
# GROUP=jvm (cores 8-11, one-core 8) or GROUP=srv (MariaDB rw t=4 and Router 1k qps on 36-39, one-core 36). Output: cause_diag.csv
GROUP=$1; R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; OUT=$R/cause_diag.csv
[[ -f $OUT ]] || echo "workload,config,cores,util_pct,mpki,ipc,instr" > $OUT
cores_list() { python3 -c "import re;s='$1';print(' '.join(str(i) for a,b in re.findall(r'(\d+)-?(\d*)',s) for i in range(int(a),int(b or a)+1)))"; }
cstate() { local mode=$1 cc; for cc in $(cores_list $2); do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
EV='cpu/event=0x24,umask=0x24,name=L2I/u,instructions:u,cycles:u,task-clock'
rec() { python3 - "$1" "$2" "$3" "$4" $OUT <<'PY'
import csv,sys
w,cfg,cores,nc,out=sys.argv[1:6]; v={}
for r in csv.reader(open('/tmp/cause_perf.csv')):
    if len(r)>=3:
        try: v[r[2]]=float(r[0])
        except: pass
i=v.get('instructions:u',0); c=v.get('cycles:u',0); m=v.get('L2I',0); t=v.get('task-clock',0); util=100*t/(30000*int(nc))
open(out,'a').write(f"{w},{cfg},{cores},{util:.1f},{1000*m/i if i else 0:.2f},{i/c if c else 0:.3f},{i:.0f}\n")
print(f"{w:28s} {cfg:12s} cores={cores:6s} util={util:4.0f}% MPKI={1000*m/i if i else 0:6.2f} IPC={i/c if c else 0:.2f} instr={i/1e9:.1f}G")
PY
}
if [[ $GROUP == jvm ]]; then
  JDK=/usr/lib/jvm/java-21-openjdk-amd64; DACAPO=/home/hnpark2/prefetchit/benchmarks/tools/dacapo/dacapo-23.11-MR2-chopin.jar; REN=/home/hnpark2/prefetchit/benchmarks/tools/renaissance/renaissance-gpl.jar; SCR=/tmp/jvm_cause; mkdir -p $SCR
  runj() { local suite=$1 b=$2 cfg=$3 cores=$4 nc=$5; local fl=""; [[ $b == cassandra ]] && fl="-Djava.security.manager=allow"; mkdir -p $SCR/s_$b
    if [[ $suite == dacapo ]]; then taskset -c $cores $JDK/bin/java -Xms8g -Xmx8g -XX:ActiveProcessorCount=$nc $fl -jar $DACAPO $b -n 60 --scratch-directory $SCR/s_$b > $SCR/$b.log 2>&1 & else taskset -c $cores $JDK/bin/java -Xms8g -Xmx8g -XX:ActiveProcessorCount=$nc -jar $REN $b -r 500 --scratch-base $SCR/s_$b > $SCR/$b.log 2>&1 & fi; local jp=$!
    sleep 40; if ! kill -0 $jp 2>/dev/null; then echo "$suite/$b $cfg: ended early"; return; fi
    perf stat -x, -o /tmp/cause_perf.csv -e $EV -p $jp -- sleep 20 > /dev/null 2>&1; kill $jp 2>/dev/null; sleep 1; kill -9 $jp 2>/dev/null; wait $jp 2>/dev/null; rec "$suite/$b" $cfg $cores $nc; rm -rf $SCR/s_$b; }
  LIST="dacapo:tomcat dacapo:spring dacapo:tradesoap dacapo:avrora dacapo:kafka dacapo:jme dacapo:cassandra dacapo:tradebeans renaissance:dotty renaissance:finagle-chirper renaissance:log-regression"
  cstate 1 8-11; for sb in $LIST; do runj ${sb%%:*} ${sb#*:} noC6 8-11 4; done
  for sb in $LIST; do runj ${sb%%:*} ${sb#*:} noC6_1core 8 1; done; cstate 0 8-11
  for sb in $LIST; do runj ${sb%%:*} ${sb#*:} default_1core 8 1; done
else
  M=/home/hnpark2/prefetchit/benchmarks/mariadb; I=$M/install_base; SOCK=/tmp/mariadb_cause.sock; PORT=3403; SB="--mysql-host=localhost --mysql-socket=$SOCK --mysql-user=root --mysql-db=sbtest --tables=16 --table-size=200000"
  runm() { local cfg=$1 cores=$2 nc=$3
    taskset -c $cores $I/bin/mariadbd --no-defaults --datadir=$M/data --port=$PORT --socket=$SOCK --innodb-buffer-pool-size=4G --innodb-flush-log-at-trx-commit=1 --max-connections=512 > /tmp/mariadb_cause.log 2>&1 & local SP=$!
    for i in $(seq 1 60); do $I/bin/mariadb-admin --socket=$SOCK -u root ping > /dev/null 2>&1 && break; sleep 1; done
    taskset -c 60-67 sysbench oltp_read_write $SB --threads=4 --time=8 run > /dev/null 2>&1
    taskset -c 60-67 sysbench oltp_read_write $SB --threads=4 --time=45 --report-interval=0 run > /tmp/sb_cause.log 2>&1 & local BP=$!; sleep 6
    perf stat -x, -o /tmp/cause_perf.csv -e $EV -p $SP -- sleep 30 > /dev/null 2>&1; wait $BP; rec mariadb_oltp_read_write $cfg $cores $nc
    $I/bin/mariadb-admin --socket=$SOCK -u root shutdown > /dev/null 2>&1; sleep 2; kill $SP 2>/dev/null; sleep 1; }
  S=/home/hnpark2/prefetchit/benchmarks/MicroSuite/src; D=/home/hnpark2/prefetchit/benchmarks/MicroSuite/datasets; RR=/home/hnpark2/prefetchit/benchmarks/MicroSuite/run; V=/home/hnpark2/prefetchit/benchmarks/MicroSuite/variants/base
  runr() { local cfg=$1 cores=$2 nc=$3
    taskset -c $cores memcached -p 11311 -t 2 -m 512 -u $USER > /tmp/mc.log 2>&1 & local MC=$!; sleep 1
    (cd $S/Router/lookup_service/service && exec taskset -c $cores $V/lookup_server 127.0.0.1:50052 11311 4 0 > /tmp/leaf.log 2>&1) & local LEAF=$!; sleep 2
    (cd $S/Router/mid_tier_service/service && exec taskset -c $cores $V/mid_tier_server 1 $RR/router_leaf_ips.txt 127.0.0.1:50051 4 4 4 1 > /tmp/mid.log 2>&1) & local MID=$!; sleep 2
    (cd $S/Router/load_generator && exec taskset -c 40-42 ./load_generator_open_loop $D/Router/twitter_requests_query_set.dat /tmp/res.txt 50 1000 127.0.0.1:50051 90 10 > /tmp/lg_cause.log 2>&1) & local LP=$!; sleep 12
    perf stat -x, -o /tmp/cause_perf.csv -e $EV -p $LEAF -- sleep 30 > /dev/null 2>&1 & local P1=$!; perf stat -x, -o /tmp/cause_perf_mid.csv -e $EV -p $MID -- sleep 30 > /dev/null 2>&1 & local P2=$!; wait $P1 $P2; rec "μSuite Router leaf" $cfg $cores $nc; cp /tmp/cause_perf_mid.csv /tmp/cause_perf.csv; rec "μSuite Router midtier" $cfg $cores $nc
    wait $LP; kill $MID $LEAF $MC 2>/dev/null; sleep 2; killall -q lookup_server mid_tier_server 2>/dev/null; kill -9 $MC 2>/dev/null; sleep 1; }
  cstate 1 36-39; runm noC6 36-39 4; runr noC6 36-39 4; runm noC6_1core 36 1; runr noC6_1core 36 1; cstate 0 36-39; runm default_1core 36 1; runr default_1core 36 1
fi
echo CAUSE_${GROUP}_DONE
