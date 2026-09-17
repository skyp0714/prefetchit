#!/usr/bin/env bash
# after the socialNetwork screen: screen hotelReservation containers with socialNetwork load running as co-tenant noise
CS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink/coldscreen; W=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/wrk2/wrk
SNLUA=/home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/screens/mixed-workload-nosocket.lua
HLUA=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/hotelReservation/wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua
cd $CS; until grep -q COLD_SCREEN_DONE sn.log 2>/dev/null; do sleep 10; done
echo "[$(date +%T)] hotel screen start (socialNetwork noise loop on)"
( while true; do taskset -c 40-42 $W -D exp -t 3 -c 48 -d 60 -L -s $SNLUA http://localhost:8080/wrk2-api/post/compose -R 6000 > /dev/null 2>&1; done ) & NOISE=$!
./cold_screen.sh hotel.csv hotelreservation "cd /home/hnpark2/prefetchit/benchmarks/DeathStarBench/hotelReservation && taskset -c 40-42 $W -D exp -t 3 -c 48 -d 70 -L -s $HLUA http://localhost:5000 -R 3000" > hotel.log 2>&1
kill $NOISE 2>/dev/null; pkill -P $NOISE 2>/dev/null; for p in $(pgrep -f "[w]rk2/wrk -D exp"); do kill $p 2>/dev/null; done
echo "[$(date +%T)] HOTEL_DONE"
