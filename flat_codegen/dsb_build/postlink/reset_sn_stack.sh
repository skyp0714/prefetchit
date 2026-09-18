#!/usr/bin/env bash
# Fresh socialNetwork stack: drop volumes (mongo data grows ~1 GB/h under the write load and slows the base), bring it up with the redis
# no-snapshot override, load the socfb-Reed98 graph, confine every container to cores 0-35. Writes results/STACK_READY when done.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; cd $SN
rm -f $PL/results/STACK_READY
docker compose down -v > $PL/logs/reset_down.log 2>&1; docker volume prune -f > /dev/null 2>&1
docker compose -f docker-compose.yml -f $PL/compose-override-redis.yml up -d > $PL/logs/reset_up.log 2>&1; sleep 25
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --limit=200 > $PL/logs/reset_init.log 2>&1 || python3 scripts/init_social_graph.py --graph socfb-Reed98 >> $PL/logs/reset_init.log 2>&1; tail -1 $PL/logs/reset_init.log
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork-.*redis"); do docker exec $c redis-cli CONFIG GET save | tail -1 | tr '\n' ' '; done; echo "(redis save settings)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
echo "containers: $(docker ps --format '{{.Names}}' | grep -c '^socialnetwork') free: $(df --output=avail -BG / | tail -1)"; date +%T > $PL/results/STACK_READY; echo STACK_READY
