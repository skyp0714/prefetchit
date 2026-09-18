#!/usr/bin/env bash
# After the decomposition: DSB user-timeline static modes (seq D4K K40 + callee burst 3) built with prefetchit1 / prefetchit0,
# NOP twins, round 16 under default scheduling (all containers on 0-35, co-tenant load).
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q DECOMP_DONE coldscreen/decomp_chain.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] prefetchit builds"
for M in prefetchit1 prefetchit0; do V=seq${M#prefetch}; ENVS="PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_CALLEE_BURST_LINES=3 PREFETCHIT_SEQ_MNEMONIC=$M"
  (cd $DB && EXTRA_PASS_ENV="$ENVS" bash rebuild_deps_env.sh dsb-deps-$V - > $PL/logs/deps_$V.log 2>&1; rm -rf out_utl_$V libs_utl_$V libs_utl_${V}nop; bash build_utl_variant.sh $V dsb-deps-$V "$ENVS" > $PL/logs/build_utl_$V.log 2>&1)
  grep -E "prefetcht1|BUILD_UTL|lib.*: [1-9]" $PL/logs/build_utl_$V.log | head -6; objdump -d $DB/out_utl_$V/UserTimelineService 2>/dev/null | grep -c "$M"
done
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; B=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g; ARMS="g=$B:-:-:64:0:20000:0"
for V in seqit1 seqit0; do if [[ -f $DB/out_utl_$V/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_${V}nop; cp $DB/out_utl_$V/UserTimelineService.nop $DB/out_utl_${V}nop/UserTimelineService; ARMS="$ARMS $V=$DB/out_utl_$V:$DB/libs_utl_$V:dsb-deps-$V:-:-:64:0:20000:0 ${V}_nop=$DB/out_utl_${V}nop:$DB/libs_utl_${V}nop:dsb-deps-$V:-:-:64:0:20000:0"; fi; done
echo "[$(date +%T)] round16 arms: $ARMS"; ./dsb_warm_ab2.sh results/round16 3 $ARMS > logs/round16.log 2>&1
echo "[$(date +%T)] CHAIN_PREFETCHIT_DONE"
