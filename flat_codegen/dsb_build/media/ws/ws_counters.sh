#!/usr/bin/env bash
# Front-end decomposition of one arm under the interleaved load (60 s wrk, two 25 s perf windows):
#  C: cycles stalled on icache data/tag misses, on unknown branches (BTB miss -> BAClear), on resteers after clears; BAClears; ITLB walks
#  D: Top-Down level 1 (+fetch-latency, br-mispredict) via the container cgroup, branches and mispredicts
# Usage: ws_counters.sh ARM OUT_DIR
set -u
export SVC_CORES=${SVC_CORES:-0-7} POOL=${POOL:-0-7} CL_CORES=${CL_CORES:-32-35} RATE=${RATE:-600}
source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
ARM=$1; OUT=$2; mkdir -p $OUT; WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws
bash $WS/ws_recreate.sh $ARM - - > /dev/null; pid=$(svc_pid); cid=$(docker inspect -f '{{.Id}}' $CONT); CG=system.slice/docker-$cid.scope
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 15 -L -s $LUA $WRK_URL -R $RATE > /dev/null 2>&1
taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 70 -L -s $LUA $WRK_URL -R $RATE > $OUT/wrk_$ARM.log 2>&1 & WP=$!; sleep 8
C='cpu/event=0x80,umask=0x04,name=ICACHE_DATA_STALLS/u,cpu/event=0x83,umask=0x04,name=ICACHE_TAG_STALLS/u,cpu/event=0xad,umask=0x40,name=UNKNOWN_BRANCH_CYC/u,cpu/event=0xad,umask=0x80,name=CLEAR_RESTEER_CYC/u,cpu/event=0x60,umask=0x01,name=BACLEARS/u,cpu/event=0x11,umask=0x10,name=ITLB_WALK_ACTIVE/u,cpu/event=0x24,umask=0x24,name=L2I_MISS/u,instructions:u,cycles:u'
echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/C_$ARM.csv -e $C -p $pid -- sleep 25 > /dev/null 2>&1
D='{slots,topdown-retiring,topdown-bad-spec,topdown-fe-bound,topdown-be-bound,topdown-fetch-lat,topdown-br-mispredict}'
echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/D_$ARM.csv -e "$D" -a -C $SVC_CORES -G $CG,$CG,$CG,$CG,$CG,$CG,$CG -- sleep 25 > /dev/null 2>&1
echo ps101899 | sudo -S -p '' perf stat -x, -o $OUT/E_$ARM.csv -e 'br_inst_retired.all_branches:u,br_misp_retired.all_branches:u,instructions:u,cycles:u' -p $pid -- sleep 5 > /dev/null 2>&1
wait $WP; grep -E "Requests/sec" $OUT/wrk_$ARM.log
python3 - $ARM $OUT <<'PY'
import csv, sys
arm, out = sys.argv[1:3]
def load(p):
    v = {}
    for r in csv.reader(open(p)):
        if len(r) >= 3:
            try: v[r[2]] = float(r[0])
            except: pass
    return v
c = load(f"{out}/C_{arm}.csv"); d = load(f"{out}/D_{arm}.csv"); e = load(f"{out}/E_{arm}.csv")
ins = c.get('instructions:u', 1); cyc = c.get('cycles:u', 1)
print(f"{arm}: IPC {ins/cyc:.3f}, L2I MPKI {1000*c.get('L2I_MISS',0)/ins:.1f}; per kI: BACLEARS {1000*c.get('BACLEARS',0)/ins:.1f}, mispredicts {1000*e.get('br_misp_retired.all_branches:u',0)/e.get('instructions:u',1):.1f}, branches {1000*e.get('br_inst_retired.all_branches:u',0)/e.get('instructions:u',1):.0f}")
print(f"    stall cycles as % of cycles: icache data {100*c.get('ICACHE_DATA_STALLS',0)/cyc:.0f}%, icache tag {100*c.get('ICACHE_TAG_STALLS',0)/cyc:.0f}%, unknown-branch(BTB miss) {100*c.get('UNKNOWN_BRANCH_CYC',0)/cyc:.0f}%, clear-resteer {100*c.get('CLEAR_RESTEER_CYC',0)/cyc:.0f}%, ITLB walk {100*c.get('ITLB_WALK_ACTIVE',0)/cyc:.0f}%")
s = d.get('slots', 0)
if s: print("    topdown L1: " + ", ".join(f"{k.replace('topdown-','')} {100*d.get(k,0)/s:.0f}%" for k in ('topdown-retiring','topdown-bad-spec','topdown-fe-bound','topdown-be-bound','topdown-fetch-lat','topdown-br-mispredict')))
PY
