#!/usr/bin/env bash
# Pin a container's main thread to MAIN_CORE and every other thread to POOL_CORES; keeps re-pinning
# new threads (they inherit the creator's mask) every 200 ms until killed.
# Usage: pin_threads.sh CONTAINER MAIN_CORE POOL_CORES   (e.g. socialnetwork-user-timeline-service-1 40 41-44)
C=$1; MAIN=$2; POOL=$3
pid=$(docker inspect -f '{{.State.Pid}}' $C); [[ -n "$pid" && "$pid" != 0 ]] || { echo "no pid"; exit 1; }
docker update --cpuset-cpus "$MAIN,$POOL" $C > /dev/null 2>&1
declare -A done
while [[ -d /proc/$pid ]]; do
  for t in /proc/$pid/task/*; do
    tid=${t##*/}
    [[ -n "${done[$tid]:-}" ]] && continue
    if [[ $tid == $pid ]]; then taskset -pc $MAIN $tid > /dev/null 2>&1; else taskset -pc $POOL $tid > /dev/null 2>&1; fi
    done[$tid]=1
  done
  sleep 0.2
done
