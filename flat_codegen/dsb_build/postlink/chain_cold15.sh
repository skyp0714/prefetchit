#!/usr/bin/env bash
# Round 30: wider plan (v7) — more lines per site (64), lower weight floor (2), up to 3 sites per line, lead window to 20k cycles;
# epoch-gated if round 26 beat round 24, otherwise the plain cost-aware form. Arms gs / best / cold11 / cold11_nop.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD14_DONE logs/chain_cold14.log 2>/dev/null; do sleep 15; done
EPFN=_ZN14social_network19UserTimelineHandler16ReadUserTimelineERSt6vectorINS_4PostESaIS2_EElliiRKSt3mapINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESC_St4lessISC_ESaISt4pairIKSC_SC_EEE
read -r BEST EPOCH <<< "$(python3 - <<'PY'
import csv,statistics,collections
def ratio(rnd,arm):
    d=collections.defaultdict(list)
    try:
        for r in csv.DictReader(open(f'results/{rnd}/runs.csv')): d[r['arm']].append(float(r['cycles']))
    except FileNotFoundError: return None
    return statistics.median(d['gs'])/statistics.median(d[arm]) if arm in d and 'gs' in d else None
c=[(ratio('round24','cold8') or 0,'cold8',0),(ratio('round26','cold9') or 0,'cold9',1),(ratio('round27','cold10') or 0,'cold10',None)]
best=max(c); ep=best[2] if best[2] is not None else (1 if (ratio('round26','cold9') or 0)>(ratio('round24','cold8') or 0) else 0)
print(best[1], ep)
PY
)"; echo "[$(date +%T)] best=$BEST epoch=$EPOCH"
EXTRA=""; [[ $EPOCH == 1 ]] && EXTRA="--epoch-gate --epoch-fn $EPFN --rate-cap 6000"
python3 cold_plan.py results/trace_gs_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_v7.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_rate/rates.txt --max-cost 20 --max-per-site 64 --min-w 2 --max-sites-per-line 3 --max-lead 20000 $EXTRA 2>&1 | tee results/trace_gs_lbr/plan_stats_v7.txt | head -3 | cut -c1-250
n=cold11; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_v7.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"; [[ $EPOCH == 1 ]] && env="$env PREFETCHIT_COLD_EPOCH=1 PREFETCHIT_COLD_EPOCH_FN=$EPFN"
echo "[$(date +%T)] deps image dsb-deps-plan7"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-plan7 - > $PL/logs/deps_plan7.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_plan7.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-plan7 "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-plan7 > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f ]] || { echo "BUILD FAILED $n"; grep -m4 -E "undefined|error:" /home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork/build/make.log | cut -c1-200; echo "[$(date +%T)] CHAIN_COLD15_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)') twin=$([[ -f $f.nop ]] && echo yes || echo no)"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BEST=$DB/out_utl_$BEST:$L:dsb-deps-g:-:-:64:0:20000:0 $n=$DB/out_utl_$n:$L:dsb-deps-g:-:-:64:0:20000:0 ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round30 arms: $ARMS"; ./dsb_warm_ab2.sh results/round30 3 $ARMS > logs/round30.log 2>&1
python3 summarize_ab.py results/round30/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD15_DONE"
