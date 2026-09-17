#!/usr/bin/env bash
# After the cold-start screens: build the timeline-prefetch arm for user-timeline (inline via IR pass) and measure under default
# scheduling with the DSB stacks as co-tenants (all containers confined to 0-35): g / tl / tl_nop / tl+w64 wake burst.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; LL=/home/hnpark2/prefetchit/llvm_prefetchit; PI=$PL/plans/timeline
cd $PL; until grep -q NATIVE_DONE coldscreen/chain_cold_native.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] timeline build start"
python3 $LL/tools/inline_fix_operands.py --main $PI/MAIN.raw.plan.json --exe $DB/out_utl_g/UserTimelineService --dynsyms $PL/plans/inline2/dynsyms.txt --libs $PI/libjaegertracing.so.0.4.2.raw.plan.json $PI/libmongoc-1.0.so.0.0.0.raw.plan.json $PI/libbson-1.0.so.0.0.0.raw.plan.json $PI/libthrift.so.0.12.0.raw.plan.json $(ls $PI/libredis++*.raw.plan.json 2>/dev/null) --static-prefixes /opt/src/hiredis,/opt/src/redis-plus-plus --out-main $PI/main.plan.json --out-libs $PI/libs.plan.json | tee $PL/logs/timeline_fix.log
cd $DB; bash rebuild_deps_env.sh dsb-deps-tl $PI/libs.plan.json > $PL/logs/deps_tl.log 2>&1; rm -rf out_utl_tl libs_utl_tl libs_utl_tlnop; bash build_utl_variant.sh tl dsb-deps-tl "PREFETCHIT_PLAN=/dsb/postlink/plans/timeline/main.plan.json" > $PL/logs/build_utl_tl.log 2>&1; grep -E "prefetcht1|BUILD_UTL|lib.*: [1-9]" $PL/logs/build_utl_tl.log | head -12
cd $PL; B=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g; T=$DB/out_utl_tl:$DB/libs_utl_tl:dsb-deps-tl; TN=$DB/out_utl_tlnop:$DB/libs_utl_tlnop:dsb-deps-tl; L=/dsb/postlink/warmup
if [[ -f $DB/out_utl_tl/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_tlnop; cp $DB/out_utl_tl/UserTimelineService.nop $DB/out_utl_tlnop/UserTimelineService
  for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
  export SHARED_CORES=0-35
  echo "[$(date +%T)] round14 start"
  ./dsb_warm_ab2.sh results/round14 3 g=$B:-:-:64:0:20000:0 tl=$T:-:-:64:0:20000:0 tl_nop=$TN:-:-:64:0:20000:0 tlw64=$T:$L/libwarmup.so:$L/list_top256.txt:64:0:20000:0 tlw64_nop=$TN:$L/libwarmup_nop.so:$L/list_top256.txt:64:0:20000:0 > logs/round14.log 2>&1
fi
echo "[$(date +%T)] CHAIN_TIMELINE_DONE"
