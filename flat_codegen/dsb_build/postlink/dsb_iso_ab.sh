#!/usr/bin/env bash
# Isolation baseline: move every other socialnetwork container off cores 40-44, run dsb_warm_ab2.sh arms (use @40:41-44), then reset.
# Usage: dsb_iso_ab.sh OUTDIR REPS arm-specs...
for c in $(docker ps --format '{{.Names}}' | grep socialnetwork | grep -v "user-timeline-service"); do docker update --cpuset-cpus 0-39,45-85 $c > /dev/null 2>&1; done
echo "[$(date +%T)] isolated cores 40-44"
"$(dirname "$0")/dsb_warm_ab2.sh" "$@"
for c in $(docker ps --format '{{.Names}}' | grep socialnetwork | grep -v "user-timeline-service"); do docker update --cpuset-cpus 0-85 $c > /dev/null 2>&1; done
echo "[$(date +%T)] cpusets reset; ISO_DONE"
