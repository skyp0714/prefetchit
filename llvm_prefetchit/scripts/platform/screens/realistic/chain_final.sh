#!/usr/bin/env bash
# Fresh relaunch of the remaining screen steps (every step under a timeout): hotel + media C6-off passes, CloudSuite C6-off points,
# data-serving rerun (warm-up fixed), data-caching rerun (bare wait fixed). Markers: FINAL_STACKS_DONE (0-42 free again), FINAL_DONE.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; DSB=/home/hnpark2/prefetchit/benchmarks/DeathStarBench
cstate() { local mode=$1 cc; for cc in $(seq 0 42); do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cstate 0' EXIT
echo "[$(date +%T)] hotelReservation, C6 off, rate 3000"; (cd $DSB/hotelReservation && docker compose up -d > /dev/null 2>&1); sleep 25
cstate 1; PREFIX=hotelreservation URL=http://localhost:5000 LUA=$R/hotel_mixed.lua R0=3000 POOL=0-35 timeout 900 $R/dsb_realistic_screen_v2.sh $R/dsb_hotel_noC6.csv 3000 2>&1 | grep -vE "^\s*$" | cut -c1-200; cstate 0
(cd $DSB/hotelReservation && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] mediaMicroservices, C6 off, rate 2000"; (cd $DSB/mediaMicroservices && docker compose up -d > /dev/null 2>&1); sleep 30
(cd $DSB/mediaMicroservices/scripts && timeout 600 python3 write_movie_info.py -c ../datasets/tmdb/casts.json -m ../datasets/tmdb/movies.json --server_address http://localhost:8080 > $R/logs/final_media_init.log 2>&1; timeout 300 bash register_users.sh >> $R/logs/final_media_init.log 2>&1; timeout 300 bash register_movies.sh >> $R/logs/final_media_init.log 2>&1)
cstate 1; PREFIX=mediamicroservices URL=http://localhost:8080/wrk2-api/review/compose LUA=$R/media_compose_review.lua R0=2000 POOL=0-35 timeout 900 $R/dsb_realistic_screen_v2.sh $R/dsb_media_noC6.csv 2000 2>&1 | grep -vE "^\s*$" | cut -c1-200; cstate 0
(cd $DSB/mediaMicroservices && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] FINAL_STACKS_DONE"
echo "[$(date +%T)] CloudSuite C6-off points (cores 4-7)"; cs47() { local mode=$1 cc; for cc in 4 5 6 7; do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
cs47 1
sed 's/for scale in 25 50 100 200 400; do/for scale in 50; do/; s/web-serving,cs-ws-web/web-serving-noC6,cs-ws-web/' $R/cloudsuite_ws2.sh > /tmp/ws2_noc6.sh; CORES=4-7 timeout 900 bash /tmp/ws2_noc6.sh $R/cloudsuite_4core.csv 2>&1 | grep -E "^web-serving" | cut -c1-200
sed 's/for w in 25 50 100 200 400; do/for w in 50; do/; s/open(out,.a.).write(f"{b},/open(out,"a").write(f"{b}-noC6,/' $R/cloudsuite_fix2.sh > /tmp/wsrch_noc6.sh; CORES=4-7 timeout 900 bash /tmp/wsrch_noc6.sh $R/cloudsuite_4core.csv web-search 2>&1 | grep -E "^web-search" | cut -c1-200
sed 's/for rps in 100000 200000 400000 700000 1000000; do/for rps in 200000; do/; s/data-caching,cs-dc-server/data-caching-noC6,cs-dc-server/' $R/cloudsuite_dc2.sh > /tmp/dc2_noc6.sh; CORES=4-7 timeout 900 bash /tmp/dc2_noc6.sh $R/cloudsuite_4core.csv 2>&1 | grep -E "^data-caching" | cut -c1-200
cs47 0
echo "[$(date +%T)] data-serving (warm-up fixed)"; grep -v "^data-serving," $R/cloudsuite_4core.csv > $R/cloudsuite_4core.tmp && mv $R/cloudsuite_4core.tmp $R/cloudsuite_4core.csv; CORES=4-7 timeout 2400 $R/cloudsuite_fix2.sh $R/cloudsuite_4core.csv data-serving 2>&1 | grep -vE "^\s*$" | cut -c1-200
echo "[$(date +%T)] data-caching (bare wait fixed)"; sed -i 's/for rps in 100000 200000 400000 700000 1000000; do/for rps in 200000 400000 700000; do/' $R/cloudsuite_dc2.sh; CORES=4-7 timeout 1500 $R/cloudsuite_dc2.sh $R/cloudsuite_4core.csv 2>&1 | grep -vE "^\s*$" | cut -c1-200
docker rm -f $(docker ps -aq --filter name=cs-) > /dev/null 2>&1; echo "[$(date +%T)] FINAL_DONE"
