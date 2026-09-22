#!/usr/bin/env bash
# DSB socialNetwork: bring up, init graph, verify one compose-post request, then measure with per-container cgroup perf
set -u
until grep -q WP2_DONE /tmp/wp_chain.log; do sleep 15; done
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/dsb_socialnetwork; mkdir -p $OUT/cg
echo ps101899 | sudo -S rm -f /etc/nginx/sites-enabled/wordpress; echo ps101899 | sudo -S nginx -s reload 2>/dev/null
cd $SN; docker compose up -d > $OUT/up2.log 2>&1; sleep 25
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --limit=200 > $OUT/init2.log 2>&1; tail -1 $OUT/init2.log
# one compose-post via the lua script's exact request shape
curl -s -o $OUT/compose_one.txt -w "compose-post status %{http_code}\n" -X POST "http://localhost:8080/wrk2-api/post/compose" --data-urlencode "username=username_1" --data-urlencode "user_id=1" --data-urlencode "text=hello world http://example.com @username_2" --data-urlencode "media_ids=[]" --data-urlencode "media_types=[]" --data-urlencode "post_type=0"; head -c 300 $OUT/compose_one.txt; echo
curl -s -o /dev/null -w "home-timeline status %{http_code}\n" "http://localhost:8080/wrk2-api/home-timeline/read?user_id=1&start=0&stop=10"
docker logs socialnetwork-compose-post-service-1 2>&1 | tail -3 | cut -c1-200
docker logs socialnetwork-nginx-thrift-1 2>&1 | tail -2 | cut -c1-200
# measurement: mixed workload (60% home, 30% user timeline, 10% compose), R=3000
LUA=$SN/wrk2/scripts/social-network/mixed-workload.lua
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 15 -L -s $LUA http://localhost:8080 -R 3000 > $OUT/warmup2.log 2>&1
taskset -c 60-67 $W -D exp -t 8 -c 64 -d 65 -L -s $LUA http://localhost:8080 -R 3000 > $OUT/wrk2_mixed.log 2>&1 &
WP=$!; sleep 5
for c in $(docker compose ps --format '{{.Name}}'); do
  pid=$(docker inspect -f '{{.State.Pid}}' $c); cg=$(awk -F: 'NR==1{print $3}' /proc/$pid/cgroup); [[ -n "$cg" ]] || continue
  echo ps101899 | sudo -S perf stat -x, -o $OUT/cg/${c#socialnetwork-}.csv -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -a -G "${cg#/}" -- sleep 30 > /dev/null 2>&1 &
done; wait $WP; wait
grep -E "Requests/sec|Non-2xx" $OUT/wrk2_mixed.log
python3 - $OUT/cg <<'PY'
import csv,glob,os,sys
rows=[]
for p in sorted(glob.glob(f"{sys.argv[1]}/*.csv")):
    ev={}
    for row in csv.reader(open(p)):
        if len(row)>=3:
            try: ev[row[2]]=float(row[0])
            except ValueError: pass
    i,c,m=ev.get("instructions",0),ev.get("cycles",0),ev.get("L2I_CODE_RD_MISS",0)
    if i>5e8: rows.append((i,os.path.basename(p)[:-4],1000*m/i,i/c if c else 0))
tot_i=sum(r[0] for r in rows); tot_m=sum(r[0]*r[2]/1000 for r in rows)
print(f"DSB per-container (30 s window): total instr={tot_i/1e9:.1f}G aggregate MPKI={1000*tot_m/tot_i if tot_i else 0:.2f}")
for i,n,mp,ipc in sorted(rows,reverse=True): print(f"  {n:28s} instr={i/1e9:6.2f}G MPKI={mp:7.2f} IPC={ipc:.3f}")
PY
docker compose down > /dev/null 2>&1; echo DSB4_DONE
