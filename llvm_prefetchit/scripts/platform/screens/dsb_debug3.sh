#!/usr/bin/env bash
set -u
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
OUT=/home/hnpark2/prefetchit/llvm_prefetchit/results/broad_screen_20260916/dsb_socialnetwork/debug3; mkdir -p $OUT
cd $SN; docker compose up -d > $OUT/up.log 2>&1; sleep 25
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --limit=200 > $OUT/init.log 2>&1; tail -1 $OUT/init.log
# make some posts so timelines are non-empty
for i in $(seq 1 30); do curl -s -o /dev/null -X POST "http://localhost:8080/wrk2-api/post/compose" --data-urlencode "username=username_$i" --data-urlencode "user_id=$i" --data-urlencode "text=post number $i from user $i @username_$((i+1)) http://x.io/$i" --data-urlencode "media_ids=[]" --data-urlencode "media_types=[]" --data-urlencode "post_type=0"; done
echo "== user-timeline of user 3:"; curl -s "http://localhost:8080/wrk2-api/user-timeline/read?user_id=3&start=0&stop=10" | head -c 200; echo
LUA=$SN/wrk2/scripts/social-network/mixed-workload.lua
HP=$(docker inspect -f '{{.State.Pid}}' socialnetwork-home-timeline-service-1); UP=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1); CP=$(docker inspect -f '{{.State.Pid}}' socialnetwork-compose-post-service-1)
ps -o pid,comm,nlwp -p $HP,$UP,$CP
echo ps101899 | sudo -S perf stat -x, -o $OUT/p_home.csv -e instructions,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -p $HP -- sleep 12 > /dev/null 2>&1 &
echo ps101899 | sudo -S perf stat -x, -o $OUT/p_user.csv -e instructions,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -p $UP -- sleep 12 > /dev/null 2>&1 &
echo ps101899 | sudo -S perf stat -x, -o $OUT/p_compose.csv -e instructions,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/' -p $CP -- sleep 12 > /dev/null 2>&1 &
sleep 1; taskset -c 60-67 $W -D exp -t 8 -c 64 -d 10 -L -s $LUA http://localhost:8080 -R 2000 > $OUT/wrk2.log 2>&1; wait
grep -E "Requests/sec|Non-2xx" $OUT/wrk2.log
for f in home user compose; do printf "%-8s instr=%s miss=%s\n" $f "$(awk -F, '$3=="instructions"{print $1}' $OUT/p_$f.csv)" "$(awk -F, '$3=="L2I_CODE_RD_MISS"{print $1}' $OUT/p_$f.csv)"; done
echo "== nginx-thrift error.log tail:"; docker exec socialnetwork-nginx-thrift-1 tail -5 /usr/local/openresty/nginx/logs/error.log 2>/dev/null | cut -c1-240
docker compose down > /dev/null 2>&1; echo DSBDBG3_DONE
