#!/usr/bin/env bash
# After the Router A/B: DSB user-timeline with the cold-path static mode (function-entry bursts: own lines <=16, direct callees, external callees via GOT),
# with and without a small wake burst (32 lines); NOP twins; round 17 under default scheduling (containers on 0-35).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q ROUTER_AB_CHAIN_DONE /home/hnpark2/prefetchit/benchmarks/MicroSuite/run/chain_router_ab.log 2>/dev/null; do sleep 15; done
ENVS="PREFETCHIT_COLD_OWN_LINES=16 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24"
echo "[$(date +%T)] cold builds"; (cd $DB && EXTRA_PASS_ENV="$ENVS" bash rebuild_deps_env.sh dsb-deps-cold - > $PL/logs/deps_cold.log 2>&1; rm -rf out_utl_cold libs_utl_cold libs_utl_coldnop; bash build_utl_variant.sh cold dsb-deps-cold "$ENVS" > $PL/logs/build_utl_cold.log 2>&1)
grep -E "prefetcht1|BUILD_UTL|lib.*: [1-9]" $PL/logs/build_utl_cold.log | head -10; grep -h "prefetchit-cold:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | tail -2 | cut -c1-160
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; B=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g; L=/dsb/postlink/warmup; ARMS="g=$B:-:-:64:0:20000:0"
if [[ -f $DB/out_utl_cold/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_coldnop; cp $DB/out_utl_cold/UserTimelineService.nop $DB/out_utl_coldnop/UserTimelineService
  C=$DB/out_utl_cold:$DB/libs_utl_cold:dsb-deps-cold; CN=$DB/out_utl_coldnop:$DB/libs_utl_coldnop:dsb-deps-cold
  ARMS="$ARMS cold=$C:-:-:64:0:20000:0 cold_nop=$CN:-:-:64:0:20000:0 coldw32=$C:$L/libwarmup.so:$L/list_top256.txt:32:0:20000:0 coldw32_nop=$CN:$L/libwarmup_nop.so:$L/list_top256.txt:32:0:20000:0 w32=$B:$L/libwarmup.so:$L/list_top256.txt:32:0:20000:0"
fi
echo "[$(date +%T)] round17 arms: $ARMS"; ./dsb_warm_ab2.sh results/round17 3 $ARMS > logs/round17.log 2>&1
echo "[$(date +%T)] CHAIN_COLD_DONE"
