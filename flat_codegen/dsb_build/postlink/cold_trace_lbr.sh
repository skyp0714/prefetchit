#!/usr/bin/env bash
# L2I-miss samples of a (fat-static) user-timeline binary under the standard load → per-function miss shares and a cumulative-coverage
# function list (mangled names) for PREFETCHIT_SEQ_FUNCTIONS_FILE. Usage: cold_trace_funcs.sh BIN_DIR LIBS_DIR IMAGE OUT [COVERAGE=0.9]
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
SVC=${SVC:-user-timeline-service}; SVCBIN=${SVCBIN:-UserTimelineService}; CONT=socialnetwork-$SVC-1; OVR=$PL/compose-override-${SVC}-warm.yml
export SVC SVCBIN RATE_REF
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
BIN=$1; LIBS=$2; IMG=$3; OUT=$4; COV=${5:-0.9}; R=${R:-6000}; mkdir -p $OUT; OUT=$(readlink -f $OUT)
export UTL_BIN=$BIN UTL_LIBS=$LIBS UTL_IMG=$IMG WARM_PRELOAD= WARM_LIST= WARM_N=0 WARM_STAGE=0 WARM_MIN=0 WARM_PACE=0
cd $SN; docker compose -f docker-compose.yml -f $OVR up -d --force-recreate --no-deps $SVC > $OUT/up.log 2>&1; sleep 6
docker update --cpuset-cpus ${SHARED_CORES:-0-35} $CONT > /dev/null 2>&1
pid=$(docker inspect -f '{{.State.Pid}}' $CONT); echo "pid=$pid"
PINPID=; if [[ -n "${PIN:-}" ]]; then echo ps101899 | sudo -S -p '' nohup $PL/pin_threads.sh $CONT ${PIN%%:*} ${PIN#*:} > /dev/null 2>&1 & PINPID=$!; sleep 1; fi
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > /dev/null 2>&1
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 45 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2.log 2>&1 & WP=$!; sleep 10
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
echo ps101899 | sudo -S -p '' perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -b -c 1000 -p $pid -o $OUT/l2miss.data -- sleep 25 > $OUT/perf_record.log 2>&1
wait $WP; echo ps101899 | sudo -S -p '' chmod a+r $OUT/l2miss.data
echo ps101899 | sudo -S -p '' perf script -i $OUT/l2miss.data -F ip,dso,brstack 2>/dev/null > $OUT/samples_lbr.txt; awk '{print $1, $2}' $OUT/samples_lbr.txt > $OUT/samples.txt
if [[ -n $PINPID ]]; then echo ps101899 | sudo -S -p '' pkill -P $PINPID > /dev/null 2>&1; echo ps101899 | sudo -S -p '' kill $PINPID > /dev/null 2>&1; fi
python3 - $OUT $BIN/$SVCBIN $COV <<'PY'
import sys,subprocess,bisect,collections
out,exe,cov=sys.argv[1],sys.argv[2],float(sys.argv[3])
base=None
for l in open(f"{out}/maps.txt"):
    f=l.split()
    if len(f)>=6 and f[5].endswith('/custom/'+__import__('os').environ.get('SVCBIN','UserTimelineService')) and f[2]=='00000000': base=int(f[0].split('-')[0],16); break
syms=[]
for l in subprocess.run(['nm','--defined-only',exe],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)==3 and f[1] in 'TtWw': syms.append((int(f[0],16),f[2]))
syms.sort(); addrs=[a for a,_ in syms]
tot=0; exe_n=0; per=collections.Counter(); dso=collections.Counter()
for l in open(f"{out}/samples.txt"):
    f=l.split()
    if len(f)<2: continue
    tot+=1; d=f[1].strip('()'); dso[d.rsplit('/',1)[-1]]+=1
    if d.endswith('/custom/'+__import__('os').environ.get('SVCBIN','UserTimelineService')) and base is not None:
        exe_n+=1; v=int(f[0],16)-base; i=bisect.bisect_right(addrs,v)-1
        if i>=0: per[syms[i][1]]+=1
print(f"samples={tot} exe={exe_n} ({100*exe_n/max(1,tot):.1f}%) distinct_funcs={len(per)}")
print("dso shares:", ', '.join(f"{k} {100*v/tot:.1f}%" for k,v in dso.most_common(6)))
acc=0; sel=[]
for name,n in per.most_common():
    sel.append(name); acc+=n
    if acc>=cov*exe_n: break
open(f"{out}/funcs.txt","w").write('\n'.join(sel)+'\n')
open(f"{out}/func_shares.txt","w").write('\n'.join(f"{n} {100*n/max(1,exe_n):.2f}% {name}" for name,n in per.most_common(300))+'\n')
print(f"functions covering {int(cov*100)}% of exe misses: {len(sel)} (top: {', '.join(s[:40] for s in sel[:5])})")
PY
