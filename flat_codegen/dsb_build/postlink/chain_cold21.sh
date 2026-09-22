#!/usr/bin/env bash
# Round 35: combine what helped — measured-execution pruning (round 32) and/or the orphan burst (round 34) on top of v4; 3 reps vs gs,
# cold8 and the twin.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD20_DONE logs/chain_cold20.log 2>/dev/null; do sleep 15; done
read -r PRUNE ORPHAN <<< "$(python3 - <<'PY'
import csv,statistics,collections
def med(rnd):
    d=collections.defaultdict(list)
    try:
        for r in csv.DictReader(open(f'results/{rnd}/runs.csv')): d[r['arm']].append(float(r['cycles']))
    except FileNotFoundError: return {}
    return {a:statistics.median(v) for a,v in d.items() if len(v)>=2}
m32=med('round32'); prune='1' if ('cold14' in m32 and 'cold8' in m32 and m32['cold8']/m32['cold14']>0.995) else '0'   # keep pruning unless it is clearly slower (it halves the overhead)
m34=med('round34'); orphan='0'
for a,nn in (('cold15','64'),('cold16','128')):
    if a in m34 and 'cold8' in m34 and m34['cold8']/m34[a]>1.005 and (orphan=='0' or m34[a]<m34['cold15' if nn=='128' else 'cold16']): orphan=nn
print(prune, orphan)
PY
)"; echo "[$(date +%T)] prune=$PRUNE orphan=$ORPHAN"
[[ $PRUNE == 0 && $ORPHAN == 0 ]] && { echo "nothing to combine"; echo "[$(date +%T)] CHAIN_COLD21_DONE"; exit 0; }
[[ $PRUNE == 1 && $ORPHAN == 0 ]] && { echo "pruning alone already measured (round 32)"; echo "[$(date +%T)] CHAIN_COLD21_DONE"; exit 0; }
PSYM=_ZN6apache6thrift18TDispatchProcessor7processESt10shared_ptrINS0_8protocol9TProtocolEES5_Pv
OPTS="--fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20"
[[ $PRUNE == 1 ]] && OPTS="$OPTS --site-exec results/prof_cold8/site_exec.txt --max-exec-ratio 10"
[[ $ORPHAN != 0 ]] && OPTS="$OPTS --orphan-burst $ORPHAN --orphan-site $PSYM"
python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v13.json $OPTS 2>&1 | tee results/trace_gs_lbr/plan_stats_v13.txt | grep -E "orphan|exec filter|samples=" | cut -c1-200
n=cold17; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v13.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-plan13"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan13 - > $PL/logs/deps_plan13.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan13.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan13 "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-plan13 > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; echo "[$(date +%T)] CHAIN_COLD21_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 cold8=$DB/out_utl_cold8:$L:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round35 arms: $ARMS"; ./dsb_warm_ab2.sh results/round35 3 $ARMS > logs/round35.log 2>&1
python3 summarize_ab.py results/round35/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD21_DONE"
