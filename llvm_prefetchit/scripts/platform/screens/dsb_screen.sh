#!/usr/bin/env bash
# DeathStarBench socialNetwork L2I-MPKI screen (stock images): compose up, init graph, wrk2 mixed load on CLIENT_CORES,
# perf stat -a on all other cores (services are unpinned docker processes) + per-service perf stat -p for the top services.
set -u
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/dsb_socialnetwork; mkdir -p $OUT
CLIENT_CORES="${CLIENT_CORES:-60-67}"; SERVER_CORES="${SERVER_CORES:-0-59}"; DUR="${DUR:-60}"; R="${R:-6000}"
cd $SN; docker compose up -d > $OUT/up.log 2>&1; sleep 20
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --limit=200 > $OUT/init.log 2>&1 || python3 scripts/init_social_graph.py --graph socfb-Reed98 >> $OUT/init.log 2>&1; tail -1 $OUT/init.log
sleep 2
LUA=$SN/wrk2/scripts/social-network/mixed-workload.lua; [[ -f $LUA ]] || LUA=$SN/wrk2/scripts/social-network/compose-post.lua
taskset -c $CLIENT_CORES $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/warmup.log 2>&1
taskset -c $CLIENT_CORES $W -D exp -t 8 -c 64 -d $((DUR+5)) -L -s $LUA http://localhost:8080/wrk2-api/post/compose -R $R > $OUT/wrk2.log 2>&1 &
WP=$!; sleep 3
perf stat -x, -o $OUT/perf_all.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -C $SERVER_CORES -- sleep $((DUR-10)) &
PP=$!
# per-service (top CPU) breakdown
sleep 2; for c in $(docker compose ps --format '{{.Name}}'); do
  pid=$(docker inspect -f '{{.State.Pid}}' $c 2>/dev/null); [[ -n "$pid" && "$pid" != 0 ]] || continue
  svc=${c#socialnetwork-}; svc=${svc%-1}
  echo ps101899 | sudo -S perf stat -x, -o $OUT/perf_${svc}.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -p $pid -- sleep 25 > /dev/null 2>&1 &
done; wait $PP; wait
python3 - $OUT <<'PY'
import csv,glob,os,re,sys
out=sys.argv[1]
def rd(p):
    ev={}
    for row in csv.reader(open(p)):
        if len(row)>=3:
            try: ev[row[2]]=float(row[0])
            except ValueError: pass
    return ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
i,c,m=rd(f"{out}/perf_all.csv"); w=open(f"{out}/wrk2.log").read(); rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w)
print(f"DSB socialNetwork all server cores: rps={rps.group(1) if rps else 'n/a'} non2xx={bad.group(1) if bad else 0} L2I MPKI={1000*m/i if i else 0:.2f} IPC={i/c if c else 0:.3f} instr={i/1e9:.1f}G")
for p in sorted(glob.glob(f"{out}/perf_*.csv")):
    if p.endswith("perf_all.csv"): continue
    i,c,m=rd(p); 
    if i>1e8: print(f"  {os.path.basename(p)[5:-4]:28s} instr={i/1e9:6.2f}G MPKI={1000*m/i:7.2f} IPC={i/c if c else 0:.3f}")
PY
docker compose down > /dev/null 2>&1
echo DSB_SCREEN_DONE
