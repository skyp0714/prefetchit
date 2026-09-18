#!/usr/bin/env bash
# End of the 2026-09-18 night campaign: restore the CPU/uncore frequency defaults, stop the disk cleaner, un-confine the containers
# (back to all cores), keep the stacks up. Run after the last measurement (CHAIN_COLD25_DONE).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; cd $PL
until grep -q CHAIN_COLD25_DONE logs/chain_cold25.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] restoring platform"; echo ps101899 | sudo -S -p '' env MODE=restore bash /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh 2>&1 | tail -3
echo ps101899 | sudo -S -p '' env MODE=show bash /home/hnpark2/prefetchit/llvm_prefetchit/scripts/platform/freeze_platform.sh 2>&1 | tail -2
[[ -f logs/janitor.pid ]] && kill $(cat logs/janitor.pid) 2>/dev/null && echo "cleaner stopped"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-85 $c > /dev/null 2>&1; done; echo "containers un-confined (0-85)"
docker images --format '{{.Repository}}' | grep -E "^dsb-deps-(plan|cold1|seq)" | xargs -r docker rmi > /dev/null 2>&1; df -h / | tail -1 | awk '{print "root free:", $4}'
echo "[$(date +%T)] WRAPUP_DONE"
