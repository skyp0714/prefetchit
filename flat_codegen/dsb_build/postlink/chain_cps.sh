#!/usr/bin/env bash
# Test 2a — generalization to compose-post (the most cold-start-dominant socialNetwork service: 22.9 → 4.4 MPKI shared → isolated).
# Same pipeline: fat-static base (gs) → LBR + rate traces → plan v4 (cost-aware) → build → instruction profile → prune (v10) → build → A/B.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; cd $PL
until grep -q CHAIN_PIN_DONE logs/chain_pin.log 2>/dev/null; do sleep 15; done
export SVC=compose-post-service SVCBIN=ComposePostService RATE_REF=_ZN14social_network18ComposePostHandler11ComposePost SHARED_CORES=0-35 EXE_SUFFIX=/custom/ComposePostService
B() { local n=$1 img=$2 env=$3; (cd $DB && rm -rf out_cps_$n libs_cps_$n libs_cps_${n}nop; SVCBIN=$SVCBIN OUTPFX=cps FATSTATIC=${FS:-1} bash build_utl_variant.sh $n $img "$env" > $PL/logs/build_cps_$n.log 2>&1); local f=$DB/out_cps_$n/$SVCBIN; [[ -f $f ]] && echo "$n: rip=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)" || { echo "BUILD FAILED $n"; grep -m3 -E "undefined|error:" $SN/build/make.log | cut -c1-200; }; }
echo "[$(date +%T)] compose-post builds g (shared) and gs (fat-static)"; FS=0 B g dsb-deps-g ""; B gs dsb-deps-g ""
find $SN/build/src/$SVCBIN -name "*.o" | xargs nm --defined-only 2>/dev/null | awk '$2 ~ /^[TtWw]$/ {print $3}' | sort -u > $DB/plans/cps_svc_syms.txt; cat $DB/plans/cold_instrumentable_v3.txt $DB/plans/cps_svc_syms.txt | sort -u > $DB/plans/cps_instrumentable.txt; echo "instrumentable: $(wc -l < $DB/plans/cps_instrumentable.txt) (service $(wc -l < $DB/plans/cps_svc_syms.txt))"
G="$DB/out_cps_g:$DB/libs_cps_g:dsb-deps-g:-:-:64:0:20000:0"; GS="$DB/out_cps_gs:$DB/libs_cps_gs:dsb-deps-g:-:-:64:0:20000:0"; L=$DB/libs_cps_g
echo "[$(date +%T)] traces of gs"; ./cold_trace_lbr.sh $DB/out_cps_gs $DB/libs_cps_gs dsb-deps-g results/trace_cps_gs_lbr 0.9 2>&1 | tail -2 | cut -c1-200; ./cold_trace_rate.sh $DB/out_cps_gs $DB/libs_cps_gs dsb-deps-g results/trace_cps_gs_rate 2>&1 | tail -1 | cut -c1-200
COMMON="results/trace_cps_gs_lbr $DB/out_cps_gs/$SVCBIN $DB/plans/sysroot/libc.so.6 $DB/plans/cps_instrumentable.txt"; OPTS="--fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_cps_gs_rate/rates.txt --rate-ref-pattern ComposePostHandler11ComposePost --rate-ref-hz 600 --max-cost 20 --exe-suffix $EXE_SUFFIX --local-aliases"
python3 cold_plan.py $COMMON $DB/plans/cps_plan_v4.json $OPTS 2>&1 | tee results/trace_cps_gs_lbr/plan_stats_v4.txt | grep -E "samples=|local|cost" | cut -c1-220
P() { local n=$1 plan=$2; local env="PREFETCHIT_COLD_PLAN=/dsb/plans/$plan PREFETCHIT_COLD_DIRECT_IN_PIC=1"; echo "[$(date +%T)] deps image dsb-deps-$n"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-$n - > $PL/logs/deps_$n.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_$n.log | tail -1; B $n dsb-deps-$n "$env"; docker rmi dsb-deps-$n > /dev/null 2>&1; rm -rf $DB/libs_cps_$n $DB/libs_cps_${n}nop; }
P c4 cps_plan_v4.json
echo "[$(date +%T)] instruction profile of c4"; ./cold_site_profile.sh $DB/out_cps_c4 $L dsb-deps-g results/prof_cps_c4 2>&1 | tail -2 | cut -c1-200
python3 cold_plan.py $COMMON $DB/plans/cps_plan_v10.json $OPTS --site-exec results/prof_cps_c4/site_exec.txt --max-exec-ratio 10 2>&1 | tee results/trace_cps_gs_lbr/plan_stats_v10.txt | grep -E "samples=|measured" | cut -c1-220
P c10 cps_plan_v10.json
ARMS="g=$G gs=$GS"; for n in c4 c10; do f=$DB/out_cps_$n/$SVCBIN; [[ -f $f ]] && ARMS="$ARMS $n=$DB/out_cps_$n:$L:dsb-deps-g:-:-:64:0:20000:0"; done
f=$DB/out_cps_c10/$SVCBIN; if [[ -f $f.nop ]]; then mkdir -p $DB/out_cps_c10nop; cp $f.nop $DB/out_cps_c10nop/$SVCBIN; ARMS="$ARMS c10_nop=$DB/out_cps_c10nop:$L:dsb-deps-g:-:-:64:0:20000:0"; fi
echo "[$(date +%T)] round42 (compose-post) arms: $ARMS"; rm -rf results/round42; ./dsb_warm_ab2.sh results/round42 3 $ARMS > logs/round42.log 2>&1
python3 summarize_ab.py results/round42/runs.csv gs 2>/dev/null | sed -n 3,8p
echo "[$(date +%T)] target analysis of c10"; ./cold_trace_funcs.sh $DB/out_cps_c10nop $L dsb-deps-g results/trace_cps_c10nop 0.9 2>&1 | tail -1; ./cold_trace_funcs.sh $DB/out_cps_c10 $L dsb-deps-g results/trace_cps_c10 0.9 2>&1 | tail -1
python3 cold_target_analysis.py $f results/trace_cps_c10nop results/trace_cps_c10 > results/target_analysis_cps_c10.txt 2>&1; sed -n 1,4p results/target_analysis_cps_c10.txt | cut -c1-200; grep -E "residual|waste" results/target_analysis_cps_c10.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_CPS_DONE"
