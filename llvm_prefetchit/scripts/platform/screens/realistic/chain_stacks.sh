#!/usr/bin/env bash
# After the socialNetwork screen: hotelReservation (Go) and mediaMicroservices (C++) stacks, same per-service pinned screen.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; DSB=/home/hnpark2/prefetchit/benchmarks/DeathStarBench; W=$DSB/wrk2/wrk
until grep -q DSB_CHAIN_DONE $R/logs/chain_dsb.log 2>/dev/null; do sleep 20; done
for c in $(docker ps --format '{{.Names}}' | grep "^socialnetwork"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
echo "[$(date +%T)] hotelReservation up"; (cd $DSB/hotelReservation && docker compose up -d > $R/logs/hotel_up.log 2>&1); sleep 25
docker ps --format '{{.Names}}' | grep -c "^hotelreservation"; curl -s "http://localhost:5000/hotels?inDate=2015-04-09&outDate=2015-04-10&lat=38.0235&lon=-122.095" | head -c 120; echo
taskset -c 60-67 $W -D exp -t 4 -c 32 -d 5 -L -s $R/hotel_mixed.lua http://localhost:5000 -R 500 2>&1 | grep -E "Requests/sec|Non-2xx|Socket" | head -3
PREFIX=hotelreservation URL=http://localhost:5000 LUA=$R/hotel_mixed.lua R0=3000 $R/dsb_realistic_screen.sh $R/dsb_hotel.csv 3000 5000 8000 12000 16000 2>&1 | grep -vE "^\s*$"
(cd $DSB/hotelReservation && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] socialNetwork down (port 8080 needed by media)"; (cd /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] mediaMicroservices up"; (cd $DSB/mediaMicroservices && docker compose up -d > $R/logs/media_up.log 2>&1); sleep 30
(cd $DSB/mediaMicroservices/scripts && python3 write_movie_info.py -c ../datasets/tmdb/casts.json -m ../datasets/tmdb/movies.json --server_address http://localhost:8080 > $R/logs/media_init.log 2>&1; bash register_users.sh >> $R/logs/media_init.log 2>&1; bash register_movies.sh >> $R/logs/media_init.log 2>&1); tail -2 $R/logs/media_init.log | cut -c1-120
sed 's/require("socket")/nil/; s/socket.gettime()\*1000/os.time()*1000/' $DSB/mediaMicroservices/wrk2/scripts/media-microservices/compose-review.lua > $R/media_compose_review.lua
taskset -c 60-67 $W -D exp -t 4 -c 32 -d 5 -L -s $R/media_compose_review.lua http://localhost:8080/wrk2-api/review/compose -R 200 2>&1 | grep -E "Requests/sec|Non-2xx|Socket" | head -3
PREFIX=mediamicroservices URL=http://localhost:8080/wrk2-api/review/compose LUA=$R/media_compose_review.lua R0=1000 $R/dsb_realistic_screen.sh $R/dsb_media.csv 1000 2000 3000 4000 6000 2>&1 | grep -vE "^\s*$"
(cd $DSB/mediaMicroservices && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] STACKS_CHAIN_DONE"
