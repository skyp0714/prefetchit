#!/usr/bin/env bash
# Round 27: self-hosted refinement. Base = better of plan v4 (cold8, round 24) and epoch-gated v5 (cold9, round 26) by cycles-vs-gs;
# LBR-trace the base's twin (bursts already in the layout), regenerate the plan with frozen burst sizes and unshifted offsets (v6),
# libc/GOT targets dropped if round 25 showed the tail-latency problem disappears without them. Arms gs / base / cold10 / cold10_nop.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD11_DONE logs/chain_cold11.log 2>/dev/null; do sleep 15; done
EPFN=_ZN14social_network19UserTimelineHandler16ReadUserTimelineERSt6vectorINS_4PostESaIS2_EElliiRKSt3mapINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESC_St4lessISC_ESaISt4pairIKSC_SC_EEE
read -r BASE BASEPLAN EPOCH NOGOT <<< "$(python3 - <<'PY'
import csv,statistics,collections,os
def ratio(rnd,arm):
    d=collections.defaultdict(list)
    try:
        for r in csv.DictReader(open(f'results/{rnd}/runs.csv')): d[r['arm']].append((float(r['cycles']),float(r['p99_ms'])))
    except FileNotFoundError: return None,None
    if arm not in d or 'gs' not in d: return None,None
    return statistics.median(c for c,p in d['gs'])/statistics.median(c for c,p in d[arm]), statistics.median(p for c,p in d[arm])
r8,p8=ratio('round24','cold8'); r9,p9=ratio('round26','cold9'); r8n,p8n=ratio('round25','cold8n')
nogot='--no-got' if (p8n is not None and p8 is not None and p8n<40 and p8>60) else '-'
if r9 is not None and r8 is not None and r9>r8: print('cold9 cold_plan_v5.json 1', nogot)
else: print('cold8 cold_plan_v4.json 0', nogot)
PY
)"
echo "[$(date +%T)] base=$BASE plan=$BASEPLAN epoch=$EPOCH nogot=$NOGOT"
echo "[$(date +%T)] LBR trace of ${BASE}_nop"; SHARED_CORES=0-35 ./cold_trace_lbr.sh $DB/out_utl_${BASE}nop $DB/libs_utl_g dsb-deps-g results/trace_${BASE}nop_lbr 0.9 2>&1 | tail -2 | cut -c1-200
EXTRA=""; [[ $EPOCH == 1 ]] && EXTRA="--epoch-gate --epoch-fn $EPFN"; [[ $NOGOT == --no-got ]] && EXTRA="$EXTRA --no-got"
python3 cold_plan.py results/trace_${BASE}nop_lbr $DB/out_utl_${BASE}nop/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v6.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --rate-cap 6000 --max-cost 20 --base-plan $DB/plans/$BASEPLAN $EXTRA 2>&1 | tee results/trace_${BASE}nop_lbr/plan_stats_v6.txt | head -4 | cut -c1-250
n=cold10; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v6.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"; [[ $EPOCH == 1 ]] && env="$env PREFETCHIT_COLD_EPOCH=1 PREFETCHIT_COLD_EPOCH_FN=$EPFN"
echo "[$(date +%T)] deps image dsb-deps-plan6"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan6 - > $PL/logs/deps_plan6.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan6.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan6 "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-plan6 > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD12_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BASE=$DB/out_utl_$BASE:$L:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round27 arms: $ARMS"; ./dsb_warm_ab2.sh results/round27 3 $ARMS > logs/round27.log 2>&1
python3 summarize_ab.py results/round27/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] traces"; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_${n}nop $L dsb-deps-g results/trace_${n}nop 0.9 2>&1 | tail -1; SHARED_CORES=0-35 ./cold_trace_funcs.sh $DB/out_utl_$n $L dsb-deps-g results/trace_$n 0.9 2>&1 | tail -1
python3 cold_target_analysis.py $f results/trace_${n}nop results/trace_$n > results/target_analysis_$n.txt 2>&1; sed -n 1,4p results/target_analysis_$n.txt | cut -c1-200; grep -E "residual|waste" results/target_analysis_$n.txt | cut -c1-200
echo "[$(date +%T)] CHAIN_COLD12_DONE"
