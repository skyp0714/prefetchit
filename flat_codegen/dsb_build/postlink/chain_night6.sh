#!/usr/bin/env bash
# Chain v6: wait for the Verilator post-link measurement -> round6 (pinned-core controls + read-path hot-set burst)
#   -> clang-19 userland rebuilds (base / callee-burst / seq) -> round4 (rebuilt arms)
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
while pgrep -f "measure_verilator_variant[s]" > /dev/null; do sleep 15; done
echo "[$(date +%T)] verilator done; round6 start"
./dsb_postlink_ab3.sh results/round6 3 base=arms/base pin4=arms/base@40-43 pin8=arms/base@40-47 hotG550=arms/hotG550 hotG550_nop=arms/hotG550_nop > logs/round6.log 2>&1
echo "[$(date +%T)] round6 done"
if [[ -d arms/pgo75 ]]; then
  echo "[$(date +%T)] round7 start (trace-guided post-link plan arms)"
  ./dsb_postlink_ab4.sh results/round7 3 base=arms/base pgo75=arms/pgo75 pgo75_nop=arms/pgo75_nop pgo50=arms/pgo50 pgo50_nop=arms/pgo50_nop > logs/round7.log 2>&1
  echo "[$(date +%T)] round7 done"
fi
echo "[$(date +%T)] deps rebuilds start"
cd $DB
bash rebuild_deps_env.sh dsb-deps-g - > $PL/logs/deps_g.log 2>&1; bash build_utl_variant.sh g dsb-deps-g "" > $PL/logs/build_utl_g.log 2>&1
echo "[$(date +%T)] g done"
EXTRA_PASS_ENV="PREFETCHIT_CALLEE_BURST_LINES=3" bash rebuild_deps_env.sh dsb-deps-b3 - > $PL/logs/deps_b3.log 2>&1; bash build_utl_variant.sh b3 dsb-deps-b3 "PREFETCHIT_CALLEE_BURST_LINES=3" > $PL/logs/build_utl_b3.log 2>&1
echo "[$(date +%T)] b3 done"
EXTRA_PASS_ENV="PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_CALLEE_BURST_LINES=3" bash rebuild_deps_env.sh dsb-deps-seq - > $PL/logs/deps_seq.log 2>&1; bash build_utl_variant.sh seq dsb-deps-seq "PREFETCHIT_SEQ_DISTANCE=4096 PREFETCHIT_SEQ_STRIDE_INSNS=40 PREFETCHIT_SEQ_LINES=1 PREFETCHIT_CALLEE_BURST_LINES=3" > $PL/logs/build_utl_seq.log 2>&1
echo "[$(date +%T)] seq done; round4"
cd $PL; ARMS="g=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g"
for v in b3 seq; do if [[ -f $DB/out_utl_$v/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_${v}nop; cp $DB/out_utl_$v/UserTimelineService.nop $DB/out_utl_${v}nop/UserTimelineService; ARMS="$ARMS $v=$DB/out_utl_$v:$DB/libs_utl_$v:dsb-deps-$v ${v}_nop=$DB/out_utl_${v}nop:$DB/libs_utl_${v}nop:dsb-deps-$v"; fi; done
echo "round4 arms: $ARMS"
./dsb_g_ab.sh results/round4 3 $ARMS > logs/round4.log 2>&1
echo "[$(date +%T)] CHAIN6_DONE"
