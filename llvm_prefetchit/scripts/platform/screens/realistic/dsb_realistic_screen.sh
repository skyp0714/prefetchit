#!/usr/bin/env bash
# DeathStarBench socialNetwork realistic screen. Pass 1: containers share 0-35, mixed load R0 → CPU% per container → cpuset sizes
# (ceil(cpu%/70%) cores, nginx capped). Pass 2: everything pinned, mixed load sweep until errors / p99 > 200 ms / a container > 85% busy;
# at the last good step one 30 s perf run counts user-mode L2I misses, instructions, cycles per container cgroup.
# Usage: dsb_realistic_screen.sh OUT.csv [rates...]
OUT=$1; shift; RATES=${@:-4000 6000 8000 10000}; R0=${R0:-4000}
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=$SN/../wrk2/wrk; LUA=${LUA:-/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua}; PREFIX=${PREFIX:-socialnetwork}; URL=${URL:-http://localhost:8080/wrk2-api/post/compose}
D=$(dirname $OUT); mkdir -p $D/$PREFIX; [[ -f $OUT ]] || echo "stack,container,cores,ncores,rate,cpu_pct,util_pct,l2i,instr,cycles,mpki,ipc" > $OUT
CONTS=$(docker ps --format '{{.Names}}' | grep "^$PREFIX" | sort); for c in $CONTS; do docker update --cpuset-cpus 0-35 $c > /dev/null; done
echo "[$(date +%T)] pass 1: sizing at R=$R0"; taskset -c 60-67 $W -D exp -t 8 -c 128 -d 40 -L -s $LUA $URL -R $R0 > $D/$PREFIX/wrk2_size.log 2>&1 & WP=$!; sleep 20
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' > $D/$PREFIX/stats_size.txt; wait $WP
python3 - $D/$PREFIX/stats_size.txt $D/$PREFIX/cpusets.txt $PREFIX <<'PY'
import sys,math
st={l.split()[0]:float(l.split()[1].rstrip('%')) for l in open(sys.argv[1]) if l.strip()}
alloc={}; need={c:max(1,math.ceil(p/70.0)) for c,p in st.items() if c.startswith(sys.argv[3] if len(sys.argv)>3 else 'socialnetwork')}
fe=[c for c in need if 'nginx' in c or 'frontend' in c]
for c in fe: need[c]=min(need[c],16)
tot=sum(need.values()); pool=36
while tot>pool:   # shrink the biggest
    c=max(need,key=need.get); need[c]-=1; tot-=1
nxt=0
with open(sys.argv[2],'w') as f:
    for c in sorted(need,key=lambda k:-need[k]):
        n=need[c]; cs=f"{nxt}-{nxt+n-1}" if n>1 else f"{nxt}"; nxt+=n; f.write(f"{c} {cs} {n} {st[c]:.1f}\n")
print("allocated cores:",nxt,"of",pool)
PY
while read c cs n p; do docker update --cpuset-cpus $cs $c > /dev/null; done < $D/$PREFIX/cpusets.txt
sleep 3; LAST=; for R in $RATES; do
  taskset -c 60-67 $W -D exp -t 8 -c 128 -d 15 -L -s $LUA $URL -R $R > /dev/null 2>&1
  taskset -c 60-67 $W -D exp -t 8 -c 128 -d 40 -L -s $LUA $URL -R $R > $D/$PREFIX/wrk2_$R.log 2>&1 & WP=$!; sleep 15
  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' > $D/$PREFIX/stats_$R.txt; wait $WP
  python3 - $D/$PREFIX/wrk2_$R.log $D/$PREFIX/stats_$R.txt $D/$PREFIX/cpusets.txt $R <<'PY'
import sys,re
w=open(sys.argv[1]).read(); st={l.split()[0]:float(l.split()[1].rstrip('%')) for l in open(sys.argv[2]) if l.strip()}
cs={l.split()[0]:int(l.split()[2]) for l in open(sys.argv[3])}
def ms(rx):
    m=re.search(rx,w); v=float(m.group(1)) if m else 0; u=m.group(2) if m else 'ms'; return v*(1000 if u=='s' else 0.001 if u=='us' else 1)
rps=re.search(r"Requests/sec:\s+([0-9.]+)",w); rps=float(rps.group(1)) if rps else 0; bad=re.search(r"Non-2xx or 3xx responses:\s+(\d+)",w); bad=int(bad.group(1)) if bad else 0; p99=ms(r"\n\s+99.000%\s+([0-9.]+)(ms|s|us)")
busiest=max(((st.get(c,0)/(100*n),c) for c,n in cs.items()),default=(0,''))
print(f"R={sys.argv[4]}: rps={rps:.0f} non2xx={bad} p99={p99:.0f}ms busiest={busiest[1].split('-',1)[1] if '-' in busiest[1] else busiest[1]} {100*busiest[0]:.0f}%")
sys.exit(1 if (bad>0 or p99>200 or busiest[0]>0.85 or rps<0.97*float(sys.argv[4])) else 0)
PY
  if [[ $? -ne 0 ]]; then echo "limit reached at R=$R"; break; fi; LAST=$R
done
[[ -z $LAST ]] && LAST=$(echo $RATES | awk '{print $1}'); echo "[$(date +%T)] measuring at R=$LAST"
EVS=""; GS=""; for c in $CONTS; do id=$(docker inspect -f '{{.Id}}' $c); for e in 'cpu/event=0x24,umask=0x24,name=L2I/u' 'instructions:u' 'cycles:u'; do EVS="$EVS -e $e"; GS="$GS,system.slice/docker-$id.scope"; done; done; GS=${GS#,}
taskset -c 60-67 $W -D exp -t 8 -c 128 -d 60 -L -s $LUA $URL -R $LAST > $D/$PREFIX/wrk2_final.log 2>&1 & WP=$!; sleep 15
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' > $D/$PREFIX/stats_final.txt
echo ps101899 | sudo -S -p '' perf stat -x, -o $D/$PREFIX/perf_final.csv -a -C 0-35 $EVS -G $GS -- sleep 30 > /dev/null 2>&1; wait $WP
python3 - $D/$PREFIX/perf_final.csv $D/$PREFIX/stats_final.txt $D/$PREFIX/cpusets.txt $LAST $OUT <<'PY'
import csv,sys,subprocess,collections
perf,stats,cps,R,out=sys.argv[1:6]
st={l.split()[0]:float(l.split()[1].rstrip('%')) for l in open(stats) if l.strip()}
cs={l.split()[0]:(l.split()[1],int(l.split()[2])) for l in open(cps)}
ids={c:subprocess.run(['docker','inspect','-f','{{.Id}}',c],capture_output=True,text=True).stdout.strip() for c in cs}
byid={f"system.slice/docker-{i}.scope":c for c,i in ids.items()}
v=collections.defaultdict(dict)
for r in csv.reader(open(perf)):
    if len(r)>=4 and r[3] in byid or (len(r)>=4 and any(r[i] in byid for i in range(len(r)))):
        g=[x for x in r if x in byid][0]; ev=[x for x in r if x in ('L2I','instructions:u','cycles:u')]
        try: v[byid[g]][ev[0] if ev else r[2]]=float(r[0])
        except: pass
rows=[]
for c,(cores,n) in cs.items():
    d=v.get(c,{}); i=d.get('instructions:u',0); cy=d.get('cycles:u',0); m=d.get('L2I',0); cpu=st.get(c,0); util=cpu/n
    rows.append((1000*m/i if i else 0,c,cores,n,cpu,util,m,i,cy))
    open(out,'a').write(f"{c.split('-',1)[0]},{c.split('-',1)[1] if '-' in c else c},{cores},{n},{R},{cpu:.1f},{util:.1f},{m:.0f},{i:.0f},{cy:.0f},{1000*m/i if i else 0:.2f},{i/cy if cy else 0:.3f}\n")
for mp,c,cores,n,cpu,util,m,i,cy in sorted(rows,reverse=True):
    if i>1e8: print(f"  {(c.split('-',1)[1] if '-' in c else c):32s} cores={cores:6s} util={util:4.0f}% MPKI={mp:6.2f} IPC={i/cy if cy else 0:.2f} instr={i/1e9:.1f}G")
PY
echo DSB_SCREEN_DONE
