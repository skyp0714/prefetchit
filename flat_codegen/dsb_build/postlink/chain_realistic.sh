#!/usr/bin/env bash
# Realistic baseline: user-timeline on N dedicated cores at high utilization (operating point picked from the sweeps: largest rate with
# util >= 70%, p99 < 50 ms, no errors, shared cores < 90% busy; prefer 2 cores if it qualifies). Round 43: gs / plan v10 / twin at that
# point (3 reps). Then LBR + rate traces of gs in that regime → plan (cost-aware, pruned with the v10 profile) → cold21 (+twin) → round 44.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q SWEEP12_DONE logs/chain_sweep12.log 2>/dev/null; do sleep 15; done
read -r CORES NC RATE <<< "$(python3 - <<'PY'
import csv
best=None
for cores,nc,d in (('36-37',2,'sweep_2core'),('36',1,'sweep_1core')):
    try: rows=list(csv.DictReader(open(f'results/{d}/sweep.csv')))
    except FileNotFoundError: continue
    ok=[r for r in rows if float(r['util_pct'])>=70 and float(r['p99_ms'])<50 and int(r['non2xx'])==0 and float(r['shared_busy_pct'] or 0)<90 and float(r['rps'])>=0.97*float(r['rate'])]
    if ok and best is None: best=(cores,nc,max(int(r['rate']) for r in ok))
if best is None:
    # fall back: 1 core, highest rate with p99 < 50 ms
    rows=list(csv.DictReader(open('results/sweep_1core/sweep.csv'))); ok=[r for r in rows if float(r['p99_ms'])<50 and int(r['non2xx'])==0]
    best=('36',1,max(int(r['rate']) for r in ok) if ok else 3000)
print(*best)
PY
)"; echo "[$(date +%T)] operating point: cores=$CORES ($NC) rate=$RATE"
export LUA=$PL/utl_read.lua WRK_URL=http://localhost:8080 CONN=256 R=$RATE SHARED_CORES=$CORES
L=$DB/libs_utl_g; S=":-:-:64:0:20000:0"; G="$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g$S"; C="$DB/out_utl_cold14:$L:dsb-deps-g$S"; N="$DB/out_utl_cold14nop:$L:dsb-deps-g$S"
ARMS="gs=$G@$CORES cold14=$C@$CORES cold14_nop=$N@$CORES"
echo "[$(date +%T)] round43 arms: $ARMS"; rm -rf results/round43; ./dsb_warm_ab2.sh results/round43 3 $ARMS > logs/round43.log 2>&1
python3 summarize_ab.py results/round43/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] traces of gs in the realistic regime"; ./cold_trace_lbr.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs_real_lbr 0.9 2>&1 | tail -2 | cut -c1-200
./cold_trace_rate.sh $DB/out_utl_gs $DB/libs_utl_gs dsb-deps-g results/trace_gs_real_rate 2>&1 | tail -1 | cut -c1-200
python3 cold_plan.py results/trace_gs_real_lbr $DB/out_utl_gs/UserTimelineService $DB/plans/sysroot/libc.so.6 $DB/plans/cold_instrumentable_v3.txt $DB/plans/cold_plan_real.json --fallback --drop-own-line0 --got-only-sites $DB/plans/cold_gotonly_syms.txt --rates results/trace_gs_real_rate/rates.txt --rate-ref-hz $RATE --max-cost 20 --site-exec results/prof_cold8/site_exec.txt --max-exec-ratio 10 2>&1 | tee results/trace_gs_real_lbr/plan_stats.txt | grep -E "samples=|measured|cost" | cut -c1-220
n=cold21; env="PREFETCHIT_COLD_PLAN=/dsb/plans/cold_plan_real.json PREFETCHIT_COLD_DIRECT_IN_PIC=1"
echo "[$(date +%T)] deps image dsb-deps-planreal"; (cd $DB && EXTRA_PASS_ENV="$env" bash rebuild_deps_static.sh dsb-deps-planreal - > $PL/logs/deps_planreal.log 2>&1); grep -E "DEP_MAKE_FAILED|READY" $PL/logs/deps_planreal.log | tail -1
echo "[$(date +%T)] service $n"; (cd $DB && rm -rf out_utl_$n libs_utl_$n libs_utl_${n}nop; FATSTATIC=1 bash build_utl_variant.sh $n dsb-deps-planreal "$env" > $PL/logs/build_utl_$n.log 2>&1); docker rmi dsb-deps-planreal > /dev/null 2>&1
f=$DB/out_utl_$n/UserTimelineService; [[ -f $f.nop ]] || { echo "BUILD FAILED $n"; echo "[$(date +%T)] CHAIN_REAL_DONE"; exit 1; }
echo "$n: rip-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%rip)') r11-prefetch=$(objdump -d $f | grep -c 'prefetcht1.*(%r11)')"; mkdir -p $DB/out_utl_${n}nop; cp $f.nop $DB/out_utl_${n}nop/UserTimelineService; rm -rf $DB/libs_utl_$n $DB/libs_utl_${n}nop
ARMS="gs=$G@$CORES cold14=$C@$CORES $n=$DB/out_utl_$n:$L:dsb-deps-g$S@$CORES ${n}_nop=$DB/out_utl_${n}nop:$L:dsb-deps-g$S@$CORES"
echo "[$(date +%T)] round44 arms: $ARMS"; rm -rf results/round44; ./dsb_warm_ab2.sh results/round44 3 $ARMS > logs/round44.log 2>&1
python3 summarize_ab.py results/round44/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_REAL_DONE"
