#!/usr/bin/env bash
# Miss-cause diagnostic for the microservice stacks: repeat each per-container screen with deep C-states disabled on the pool cores
# (same rates as the default pass). socialNetwork is up after chain_sn2; hotel and media are brought up/down here.
R=/home/hnpark2/prefetchit/llvm_prefetchit/results/realistic_screen_20260918; DSB=/home/hnpark2/prefetchit/benchmarks/DeathStarBench; PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink
until grep -q CS5_CHAIN_DONE $R/logs/chain_cs5.log 2>/dev/null; do sleep 60; done
cstate() { local mode=$1 cc; for cc in $(seq 0 42); do for st in /sys/devices/system/cpu/cpu$cc/cpuidle/state*; do n=$(cat $st/name); [[ $n == C6* ]] && echo ps101899 | sudo -S -p '' sh -c "echo $mode > $st/disable"; done; done; }
trap 'cstate 0' EXIT
RATE=$(awk -F, 'NR>1{print $5}' $R/dsb_social_pool43.csv 2>/dev/null | sort -n | tail -1); [[ -z $RATE ]] && RATE=4000
echo "[$(date +%T)] socialNetwork, C6 off, pool 0-42, rate $RATE"; docker ps --format '{{.Names}}' | grep -q "^socialnetwork" || $PL/reset_sn_stack.sh > $R/logs/stackdiag_reset.log 2>&1
cstate 1; POOL=0-42 FECAP=20 R0=$RATE $R/dsb_realistic_screen_v2.sh $R/dsb_social_noC6.csv $RATE 2>&1 | grep -vE "^\s*$" | cut -c1-200; cstate 0
(cd $DSB/socialNetwork && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] hotelReservation, C6 off, rate 3000"; (cd $DSB/hotelReservation && docker compose up -d > /dev/null 2>&1); sleep 25
cstate 1; PREFIX=hotelreservation URL=http://localhost:5000 LUA=$R/hotel_mixed.lua R0=3000 POOL=0-35 $R/dsb_realistic_screen_v2.sh $R/dsb_hotel_noC6.csv 3000 2>&1 | grep -vE "^\s*$" | cut -c1-200; cstate 0
(cd $DSB/hotelReservation && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] mediaMicroservices, C6 off, rate 2000"; (cd $DSB/mediaMicroservices && docker compose up -d > /dev/null 2>&1); sleep 30
(cd $DSB/mediaMicroservices/scripts && python3 write_movie_info.py -c ../datasets/tmdb/casts.json -m ../datasets/tmdb/movies.json --server_address http://localhost:8080 > $R/logs/stackdiag_media_init.log 2>&1; bash register_users.sh >> $R/logs/stackdiag_media_init.log 2>&1; bash register_movies.sh >> $R/logs/stackdiag_media_init.log 2>&1)
cstate 1; PREFIX=mediamicroservices URL=http://localhost:8080/wrk2-api/review/compose LUA=$R/media_compose_review.lua R0=2000 POOL=0-35 $R/dsb_realistic_screen_v2.sh $R/dsb_media_noC6.csv 2000 2>&1 | grep -vE "^\s*$" | cut -c1-200; cstate 0
(cd $DSB/mediaMicroservices && docker compose down > /dev/null 2>&1)
echo "[$(date +%T)] STACKDIAG_DONE"
