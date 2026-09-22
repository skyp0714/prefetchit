#!/usr/bin/env bash
# L2I-miss samples of a (fat-static) user-timeline binary under the standard load → per-function miss shares and a cumulative-coverage
# function list (mangled names) for PREFETCHIT_SEQ_FUNCTIONS_FILE. Usage: cold_trace_funcs.sh BIN_DIR LIBS_DIR IMAGE OUT [COVERAGE=0.9]
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
SVC=${SVC:-user-timeline-service}; SVCBIN=${SVCBIN:-UserTimelineService}; CONT=socialnetwork-$SVC-1; OVR=$PL/compose-override-${SVC}-warm.yml
export SVC SVCBIN RATE_REF
LUA=${LUA:-/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua}; WRK_URL=${WRK_URL:-http://localhost:8080/wrk2-api/post/compose}; CONN=${CONN:-64}
BIN=$1; LIBS=$2; IMG=$3; OUT=$4; COV=${5:-0.9}; R=${R:-6000}; mkdir -p $OUT; OUT=$(readlink -f $OUT)
export UTL_BIN=$BIN UTL_LIBS=$LIBS UTL_IMG=$IMG WARM_PRELOAD= WARM_LIST= WARM_N=0 WARM_STAGE=0 WARM_MIN=0 WARM_PACE=0
cd $SN; docker compose -f docker-compose.yml -f $OVR up -d --force-recreate --no-deps $SVC > $OUT/up.log 2>&1; sleep 6
docker update --cpuset-cpus ${SHARED_CORES:-0-35} $CONT > /dev/null 2>&1
pid=$(docker inspect -f '{{.State.Pid}}' $CONT); echo "pid=$pid"
PINPID=; if [[ -n "${PIN:-}" ]]; then echo ps101899 | sudo -S -p '' nohup $PL/pin_threads.sh $CONT ${PIN%%:*} ${PIN#*:} > /dev/null 2>&1 & PINPID=$!; sleep 1; fi
taskset -c 60-67 $W -D exp -t 8 -c $CONN -d 15 -L -s $LUA $WRK_URL -R $R > /dev/null 2>&1
taskset -c 60-67 $W -D exp -t 8 -c $CONN -d 45 -L -s $LUA $WRK_URL -R $R > $OUT/wrk2.log 2>&1 & WP=$!; sleep 10
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
echo ps101899 | sudo -S -p '' perf record -e cycles:u -b -c 400000 -p $pid -o $OUT/l2miss.data -- sleep 20 > $OUT/perf_record.log 2>&1
wait $WP; echo ps101899 | sudo -S -p '' chmod a+r $OUT/l2miss.data
echo ps101899 | sudo -S -p '' perf script -i $OUT/l2miss.data -F ip,dso,brstack 2>/dev/null > $OUT/samples_rate.txt
if [[ -n $PINPID ]]; then echo ps101899 | sudo -S -p '' pkill -P $PINPID > /dev/null 2>&1; echo ps101899 | sudo -S -p '' kill $PINPID > /dev/null 2>&1; fi
python3 - $OUT $BIN/$SVCBIN <<'PY'
import sys,re,bisect,collections,subprocess
out,exe=sys.argv[1:3]
segs=[]
for l in open(f"{out}/maps.txt"):
    p=l.split(None,5)
    if len(p)>=6 and 'x' in p[1] and p[5].strip().endswith('/custom/'+__import__('os').environ.get('SVCBIN','UserTimelineService')):
        lo,hi=(int(x,16) for x in p[0].split('-')); segs.append((lo,hi,int(p[2],16)))
base=min(lo-off for lo,hi,off in segs)
syms=[]
for l in subprocess.run(['nm','--defined-only',exe],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)==3 and f[1] in 'TtWw': syms.append((int(f[0],16),f[2]))
syms.sort(); starts={a:n for a,n in syms}
DSO=r'\((?:[^()]|\([^()]*\))*\)'
ENT=re.compile(r'0x([0-9a-f]+) '+DSO+r'/0x([0-9a-f]+) '+DSO+r'/[MPX-]/[^/]*/[^/]*/([0-9-]+)/(\w+)/')
N=0; cnt=collections.Counter()
for ln in open(f"{out}/samples_rate.txt"):
    if not re.match(r'\s*[0-9a-f]+\s+\(',ln): continue
    N+=1
    for fr,to,cyc,ty in ENT.findall(ln):
        n=starts.get(int(to,16)-base)
        if n: cnt[n]+=1
with open(f"{out}/rates.txt","w") as f:
    f.write(f"#windows {N}\n")
    for n,c in cnt.most_common(): f.write(f"{c} {n}\n")
ref=[(c,n) for n,c in cnt.items() if __import__('os').environ.get('RATE_REF','UserTimelineHandler16ReadUserTimeline') in n]
print(f"rate trace: windows={N} functions_with_entries={len(cnt)} ref={ref[:1]}")
print("top entry counts: "+', '.join(f"{n[:45]}={c}" for n,c in cnt.most_common(6)))
PY
