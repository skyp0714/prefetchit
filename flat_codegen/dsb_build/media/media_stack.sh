#!/usr/bin/env bash
# up [ARM] | init | down — bring the media stack up (optionally with the target service replaced by an arm's binary), load the dataset.
# ARM = a directory prefix under dsb_build: out_<OUTPFX>_<ARM> + libs_<OUTPFX>_<ARM>; empty = the stock image.
set -u; source /home/hnpark2/prefetchit/flat_codegen/dsb_build/media/media_env.sh
cmd=$1; ARM=${2:-}
OVR=$MD/compose-override-$SVC.yml
up() {
  cd $MM
  if [[ -n $ARM ]]; then
    export SVC_IMG=${SVC_IMG:-dsb-deps-jammy} SVC_BIN=$DB/out_${OUTPFX}_$ARM SVC_LIBS=$DB/libs_${OUTPFX}_$ARM
    [[ -x $SVC_BIN/$SVCBIN ]] || { echo "missing $SVC_BIN/$SVCBIN"; exit 1; }
    docker compose -f docker-compose.yml -f $OVR up -d --remove-orphans > $MD/logs/up.log 2>&1
  else
    docker compose up -d --remove-orphans > $MD/logs/up.log 2>&1
  fi
  sleep 20; pin_all
  local n=$(docker ps --format '{{.Names}}' | grep -c '^mediamicroservices'); echo "stack up: $n containers, $SVC arm='${ARM:-stock}' pid=$(svc_pid)"
}
case $cmd in
  up) up;;
  recreate)   # swap only the target service (keeps the dataset)
    cd $MM; export SVC_IMG=${SVC_IMG:-dsb-deps-jammy} SVC_BIN=$DB/out_${OUTPFX}_$ARM SVC_LIBS=$DB/libs_${OUTPFX}_$ARM
    [[ -x $SVC_BIN/$SVCBIN ]] || { echo "missing $SVC_BIN/$SVCBIN"; exit 1; }
    docker compose -f docker-compose.yml -f $OVR up -d --force-recreate --no-deps $SVC > $MD/logs/recreate_$ARM.log 2>&1
    sleep 6; pin_all; echo "$SVC -> arm $ARM (pid $(svc_pid))";;
  stock) cd $MM; docker compose up -d --force-recreate --no-deps $SVC > $MD/logs/recreate_stock.log 2>&1; sleep 6; pin_all; echo "$SVC -> stock image (pid $(svc_pid))";;
  init)
    cd $MM/scripts && timeout 900 python3 write_movie_info.py -c ../datasets/tmdb/casts.json -m ../datasets/tmdb/movies.json --server_address http://localhost:8080 > $MD/logs/init.log 2>&1
    timeout 300 bash register_users.sh >> $MD/logs/init.log 2>&1; timeout 300 bash register_movies.sh >> $MD/logs/init.log 2>&1
    echo "init done: $(grep -c . $MD/logs/init.log) log lines";;
  down) cd $MM && docker compose down --remove-orphans -v > /dev/null 2>&1; echo "stack down";;   # -v: anonymous mongo/redis volumes otherwise pile up (207 orphans = 14 GB in a day; init re-creates the dataset)
  smoke) taskset -c $CL_CORES $W -D exp -t 4 -c $CONN -d 10 -L -s $LUA $WRK_URL -R $RATE 2>&1 | grep -E "Requests/sec|Non-2xx|Socket errors" ;;
esac
