#!/usr/bin/env bash
# DSB nginx-thrift tier: L2I-miss PEBS record by cgroup under mixed load → miss share per DSO (JIT vs AOT code)
set -u
true
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/dsb_socialnetwork/dso; mkdir -p $OUT
cd $SN; docker compose up -d > $OUT/up.log 2>&1; sleep 25
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --limit=200 > $OUT/init.log 2>&1; tail -1 $OUT/init.log
LUA=/tmp/screen_inputs/mixed-workload-nosocket.lua
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080 -R 3000 > $OUT/warmup.log 2>&1
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 70 -L -s $LUA http://localhost:8080 -R 3000 > $OUT/wrk2.log 2>&1 &
WP=$!; sleep 5
for c in $(docker compose ps --format '{{.Name}}'); do
  pid=$(docker inspect -f '{{.State.Pid}}' $c); cg=$(awk -F: 'NR==1{print $3}' /proc/$pid/cgroup); svc=${c#socialnetwork-}; svc=${svc%-1}
  echo ps101899 | sudo -S perf stat -x, -o $OUT/stat_${svc}.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -G "${cg#/}" -- sleep 30 > /dev/null 2>&1 &
done
NPID=$(docker inspect -f '{{.State.Pid}}' socialnetwork-nginx-thrift-1); NCG=$(awk -F: 'NR==1{print $3}' /proc/$NPID/cgroup)
echo ps101899 | sudo -S perf record -e 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' -c 2000 -o $OUT/nginx_thrift.data -a -G "${NCG#/}" -- sleep 30 > $OUT/record.log 2>&1
wait
grep -E "Requests/sec|Non-2xx" $OUT/wrk2.log
echo ps101899 | sudo -S chown hnpark2 $OUT/nginx_thrift.data
perf report -i $OUT/nginx_thrift.data --sort dso --stdio 2>/dev/null | grep -vE "^#|^$" | head -12
perf report -i $OUT/nginx_thrift.data --sort comm --stdio 2>/dev/null | grep -vE "^#|^$" | head -6
python3 - $OUT <<'PY'
import csv,glob,os,sys
rows=[]
for p in sorted(glob.glob(f"{sys.argv[1]}/stat_*.csv")):
    ev={}
    for row in csv.reader(open(p)):
        if len(row)>=3:
            try: ev[row[2]]=float(row[0])
            except ValueError: pass
    i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
    rows.append((i,os.path.basename(p)[5:-4],1000*m/i if i else 0,i/c if c else 0))
print("DSB per-container (30 s, mixed R=3000):")
for i,n,mp,ipc in sorted(rows,reverse=True): print(f"  {n:28s} instr={i/1e9:6.2f}G MPKI={mp:7.2f} IPC={ipc:.3f}")
PY
docker compose down > /dev/null 2>&1; echo DSBDSO_DONE
