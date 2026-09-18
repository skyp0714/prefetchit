#!/usr/bin/env bash
# L2I-miss samples of a (fat-static) user-timeline binary under the standard load → per-function miss shares and a cumulative-coverage
# function list (mangled names) for PREFETCHIT_SEQ_FUNCTIONS_FILE. Usage: cold_trace_funcs.sh BIN_DIR LIBS_DIR IMAGE OUT [COVERAGE=0.9]
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk
LUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
BIN=$1; LIBS=$2; IMG=$3; OUT=$4; COV=${5:-0.9}; R=${R:-6000}; mkdir -p $OUT; OUT=$(readlink -f $OUT)
export UTL_BIN=$BIN UTL_LIBS=$LIBS UTL_IMG=$IMG WARM_PRELOAD= WARM_LIST= WARM_N=0 WARM_STAGE=0 WARM_MIN=0 WARM_PACE=0
cd $SN; docker compose -f docker-compose.yml -f $PL/compose-override-utl-warm.yml up -d --force-recreate --no-deps user-timeline-service > $OUT/up.log 2>&1; sleep 6
docker update --cpuset-cpus ${SHARED_CORES:-0-35} socialnetwork-user-timeline-service-1 > /dev/null 2>&1
pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1); echo "pid=$pid"
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > /dev/null 2>&1
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 45 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2.log 2>&1 & WP=$!; sleep 10
echo ps101899 | sudo -S -p '' cat /proc/$pid/maps > $OUT/maps.txt
echo ps101899 | sudo -S -p '' perf record -e instructions:u -c 20000 -p $pid -o $OUT/l2miss.data -- sleep 20 > $OUT/perf_record.log 2>&1
wait $WP; echo ps101899 | sudo -S -p '' chmod a+r $OUT/l2miss.data
echo ps101899 | sudo -S -p '' perf script -i $OUT/l2miss.data -F ip,dso 2>/dev/null > $OUT/samples_instr.txt
python3 - $OUT $BIN/UserTimelineService <<'PY'
import sys,re,bisect,collections,subprocess
out,exe=sys.argv[1:3]
base=None
for l in open(f"{out}/maps.txt"):
    f=l.split()
    if len(f)>=6 and f[5].endswith('/custom/UserTimelineService') and f[2]=='00000000': base=int(f[0].split('-')[0],16); break
syms=[]
for l in subprocess.run(['nm','--defined-only',exe],capture_output=True,text=True).stdout.splitlines():
    f=l.split()
    if len(f)==3 and f[1] in 'TtWw': syms.append((int(f[0],16),f[2]))
syms.sort(); addrs=[a for a,_ in syms]
pf=set()
for l in subprocess.run(['objdump','-d','--no-show-raw-insn',exe],capture_output=True,text=True).stdout.splitlines():
    m=re.match(r'^\s*([0-9a-f]+):\s+prefetcht1',l)
    if m: pf.add(int(m.group(1),16))
tot=0; exe_n=0; onpf=collections.Counter(); per_fn=collections.Counter()
for l in open(f"{out}/samples_instr.txt"):
    f=l.split()
    if len(f)<2: continue
    tot+=1
    if f[1].strip('()').endswith('/custom/UserTimelineService'):
        exe_n+=1; va=int(f[0],16)-base; i=bisect.bisect_right(addrs,va)-1
        if i>=0: per_fn[syms[i][1]]+=1
        if va in pf and i>=0: onpf[syms[i][1]]+=1
with open(f"{out}/site_exec.txt","w") as f:
    f.write(f"#samples {tot} exe {exe_n} on_prefetch {sum(onpf.values())}\n")
    for n,c in onpf.most_common(): f.write(f"{c} {n}\n")
print(f"instr profile: samples={tot} exe={exe_n} on_prefetch_insns={sum(onpf.values())} ({100*sum(onpf.values())/max(1,tot):.2f}% of all instructions)")
print("top prefetch-executing sites: "+'; '.join(f"{n[:40]}={c}" for n,c in onpf.most_common(6)))
PY
