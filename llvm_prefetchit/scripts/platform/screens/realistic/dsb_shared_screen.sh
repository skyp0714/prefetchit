#!/usr/bin/env bash
# Interleaving regime for a DeathStarBench stack: every container of the stack shares one small cpuset POOL (no per-container pinning),
# mixed load sweep, per-container user-mode L2I MPKI at the highest clean rate. Usage: PREFIX= URL= LUA= POOL=0-7 dsb_shared_screen.sh OUT.csv rates...
OUT=$1; shift; RATES="$@"; POOL=${POOL:-0-7}; PREFIX=${PREFIX:-socialnetwork}; URL=${URL:-http://localhost:8080/wrk2-api/post/compose}
LUA=${LUA:-/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua}; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
D=$(dirname $OUT)/shared_$PREFIX; mkdir -p $D; [[ -f $OUT ]] || echo "stack,container,pool,rate,cpu_pct,l2i,instr,cycles,mpki,ipc" > $OUT
CONTS=$(docker ps --format '{{.Names}}' | grep "^$PREFIX" | sort); for c in $CONTS; do docker update --cpuset-cpus $POOL $c > /dev/null; done; sleep 3
LAST=; for Rt in $RATES; do
  taskset -c 60-67 $W -D exp -t 8 -c 128 -d 12 -L -s $LUA $URL -R $Rt > /dev/null 2>&1
  taskset -c 60-67 $W -D exp -t 8 -c 128 -d 30 -L -s $LUA $URL -R $Rt > $D/wrk2_${POOL}_$Rt.log 2>&1
  python3 - $D/wrk2_${POOL}_$Rt.log $Rt <<'PY'
import sys,re
w=open(sys.argv[1]).read()
def ms(rx):
    m=re.search(rx,w); v=float(m.group(1)) if m else 0; u=m.group(2) if m else 'ms'; return v*(1000 if u=='s' else 0.001 if u=='us' else 1)
rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(rps.group(1)) if rps else 0; bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w); bad=int(bad.group(1)) if bad else 0; p99=ms(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)")
print(f"R={sys.argv[2]}: rps={rps:.0f} non2xx={bad} p99={p99:.0f}ms"); sys.exit(1 if (bad>0 or p99>200 or rps<0.97*float(sys.argv[2])) else 0)
PY
  if [[ $? -ne 0 ]]; then echo "limit reached at R=$Rt"; break; fi; LAST=$Rt
done; [[ -z $LAST ]] && LAST=$(echo $RATES | awk '{print $1}'); echo "measuring at R=$LAST (pool $POOL)"
EVS=""; GS=""; for c in $CONTS; do id=$(docker inspect -f '{{.Id}}' $c); for e in 'cpu/event=0x24,umask=0x24,name=L2I/u' 'instructions:u' 'cycles:u'; do EVS="$EVS -e $e"; GS="$GS,system.slice/docker-$id.scope"; done; done; GS=${GS#,}
taskset -c 60-67 $W -D exp -t 8 -c 128 -d 55 -L -s $LUA $URL -R $LAST > $D/wrk2_${POOL}_final.log 2>&1 & WP=$!; sleep 12
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' > $D/stats_${POOL}.txt
echo ps101899 | sudo -S -p '' perf stat -x, -o $D/perf_${POOL}.csv -a -C $POOL $EVS -G $GS -- sleep 30 > /dev/null 2>&1; wait $WP
python3 - $D/perf_${POOL}.csv $D/stats_${POOL}.txt $LAST $OUT $PREFIX $POOL <<'PY'
import csv,sys,subprocess,collections
perf,stats,Rt,out,prefix,pool=sys.argv[1:7]
st={l.split()[0]:float(l.split()[1].rstrip('%')) for l in open(stats) if l.strip()}
ids={c:subprocess.run(['docker','inspect','-f','{{.Id}}',c],capture_output=True,text=True).stdout.strip() for c in st if c.startswith(prefix)}
byid={f"system.slice/docker-{i}.scope":c for c,i in ids.items()}; v=collections.defaultdict(dict)
for r in csv.reader(open(perf)):
    g=[x for x in r if x in byid]; ev=[x for x in r if x in ('L2I','instructions:u','cycles:u')]
    if g and ev:
        try: v[byid[g[0]]][ev[0]]=float(r[0])
        except: pass
rows=[]
for c,d in v.items():
    i=d.get('instructions:u',0); cy=d.get('cycles:u',0); m=d.get('L2I',0)
    open(out,'a').write(f"{prefix},{c.split('-',1)[1] if '-' in c else c},{pool},{Rt},{st.get(c,0):.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f}\n")
    if i>1e9: rows.append((1000*m/i,c,st.get(c,0),i,cy))
for mp,c,cpu,i,cy in sorted(rows,reverse=True): print(f"  {(c.split('-',1)[1] if '-' in c else c):32s} cpu={cpu:5.0f}% MPKI={mp:6.2f} IPC={i/cy:.2f} instr={i/1e9:.1f}G")
PY
echo SHARED_SCREEN_DONE
