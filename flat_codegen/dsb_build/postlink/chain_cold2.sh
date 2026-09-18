#!/usr/bin/env bash
# After round 17: fat-static UserTimelineService (thrift/mongoc/bson/jaeger/opentracing/yaml/libstdc++ linked in) so the cold-path pass
# references callees pc-relative (PREFETCHIT_COLD_DIRECT_SYMS) instead of mov-GOT + prefetch; arms g (shared base), gs (fat-static base),
# cold2 (+twin), cold2s (libc callees skipped instead of GOT-prefetched). Round 18 under default scheduling (containers on 0-35).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD_DONE logs/chain_cold.log 2>/dev/null; do sleep 15; done
ENVS="PREFETCHIT_COLD_OWN_LINES=16 PREFETCHIT_COLD_CALLEE_LINES=1 PREFETCHIT_COLD_MAX_CALLEES=8 PREFETCHIT_COLD_MAX_EXTERNAL=8 PREFETCHIT_COLD_MIN_INSNS=24 PREFETCHIT_COLD_DIRECT_SYMS=/dsb/plans/cold_direct_syms.txt"
echo "[$(date +%T)] fat-static builds"
(cd $DB && rm -rf out_utl_gs libs_utl_gs out_utl_cold2 libs_utl_cold2 libs_utl_cold2nop out_utl_cold2s libs_utl_cold2s libs_utl_cold2snop
 FATSTATIC=1 bash build_utl_variant.sh gs dsb-deps-g "" > $PL/logs/build_utl_gs.log 2>&1
 FATSTATIC=1 bash build_utl_variant.sh cold2 dsb-deps-cold "$ENVS" > $PL/logs/build_utl_cold2.log 2>&1
 FATSTATIC=1 bash build_utl_variant.sh cold2s dsb-deps-cold "$ENVS PREFETCHIT_COLD_EXTERNAL=skip" > $PL/logs/build_utl_cold2s.log 2>&1)
for v in gs cold2 cold2s; do f=$DB/out_utl_$v/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $v"; continue; }
  echo "$v: $(file -b $f | cut -c1-40) size=$(stat -c %s $f) NEEDED=$(readelf -d $f | grep NEEDED | awk '{print $NF}' | tr -d '[]' | tr '\n' ' ')"
  echo "$v: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)')"; done
grep -h "prefetchit-cold:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | tail -1
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; B=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g; ARMS="g=$B:-:-:64:0:20000:0"
[[ -f $DB/out_utl_gs/UserTimelineService ]] && ARMS="$ARMS gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0"
if [[ -f $DB/out_utl_cold2/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_cold2nop; cp $DB/out_utl_cold2/UserTimelineService.nop $DB/out_utl_cold2nop/UserTimelineService
  ARMS="$ARMS cold2=$DB/out_utl_cold2:$DB/libs_utl_cold2:dsb-deps-cold:-:-:64:0:20000:0 cold2_nop=$DB/out_utl_cold2nop:$DB/libs_utl_cold2nop:dsb-deps-cold:-:-:64:0:20000:0"; fi
[[ -f $DB/out_utl_cold2s/UserTimelineService ]] && ARMS="$ARMS cold2s=$DB/out_utl_cold2s:$DB/libs_utl_cold2s:dsb-deps-cold:-:-:64:0:20000:0"
echo "[$(date +%T)] round18 arms: $ARMS"; ./dsb_warm_ab2.sh results/round18 3 $ARMS > logs/round18.log 2>&1
echo "[$(date +%T)] CHAIN_COLD2_DONE"
