#!/usr/bin/env bash
# Disk janitor for the overnight chains: drop per-arm deps images once the arm's service (and twin) is built; drop perf.data > 50 MB older
# than 10 min (the analyses read them within a minute of the trace). Runs until killed.
DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; PL=$DB/postlink
while true; do
  find $PL/results -name "*.data" -size +50M -mmin +10 -delete 2>/dev/null   # unlinking is cheap: always
  if ps -eo args | grep -q "[d]sb_warm_ab2.sh"; then sleep 120; continue; fi   # no image removals during a measurement
  for img in $(docker images --format '{{.Repository}}' | grep -E "^dsb-deps-(plan[0-9]*|cold[0-9]+n?|seq[A-Z])$"); do
    arm=${img#dsb-deps-}; case $arm in plan4) arm=cold8;; plan3) arm=cold7;; plan2) arm=cold6;; esac
    if [[ -f $DB/out_utl_$arm/UserTimelineService.nop || -f $DB/out_utl_$arm/UserTimelineService ]] && ! pgrep -f "build_utl_variant.sh $arm " > /dev/null 2>&1; then
      if ! ps -eo args | grep -q "[r]ebuild_deps_static.sh $img"; then docker rmi $img > /dev/null 2>&1 && echo "[$(date +%T)] removed image $img"; fi
    fi
  done
  find $PL/results -name "*.data" -size +50M -mmin +10 -delete 2>/dev/null
  free=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [[ $free -lt 6 ]] && echo "[$(date +%T)] WARNING root free ${free}G"
  sleep 120
done
