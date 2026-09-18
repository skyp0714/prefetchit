#!/usr/bin/env bash
# Round 29: wake burst (LD_PRELOAD, list regenerated for the fat-static layout from the best arm's twin) on top of the best plan arm.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD13_DONE logs/chain_cold13.log 2>/dev/null; do sleep 15; done
BEST=$(python3 - <<'PY'
import csv,statistics,collections
best=None
for rnd,arm in (('round24','cold8'),('round26','cold9'),('round27','cold10')):
    d=collections.defaultdict(list)
    try:
        for r in csv.DictReader(open(f'results/{rnd}/runs.csv')): d[r['arm']].append(float(r['cycles']))
    except FileNotFoundError: continue
    if arm in d and 'gs' in d and len(d[arm])>=2:
        ratio=statistics.median(d['gs'])/statistics.median(d[arm])
        if best is None or ratio>best[0]: best=(ratio,arm)
print(best[1] if best else 'cold8')
PY
); echo "[$(date +%T)] best plan arm: $BEST"
L=$DB/libs_utl_g; echo "[$(date +%T)] wake list from ${BEST}_nop"; SHARED_CORES=0-35 ./utl_wake_pipeline.sh $DB/out_utl_${BEST}nop $L dsb-deps-g results/wake_${BEST} warmup/list_fs_top256.txt 256 2>&1 | tail -4 | cut -c1-200
[[ -s warmup/list_fs_top256.txt ]] || { echo "WAKE LIST FAILED"; echo "[$(date +%T)] CHAIN_COLD14_DONE"; exit 1; }
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; WL=/dsb/postlink/warmup
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BEST=$DB/out_utl_$BEST:$L:dsb-deps-g:-:-:64:0:20000:0 ${BEST}w32=$DB/out_utl_$BEST:$L:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:32:0:20000:0 ${BEST}w64=$DB/out_utl_$BEST:$L:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:64:0:20000:0 gsw32=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:32:0:20000:0"
echo "[$(date +%T)] round29 arms: $ARMS"; ./dsb_warm_ab2.sh results/round29 3 $ARMS > logs/round29.log 2>&1
python3 summarize_ab.py results/round29/runs.csv gs 2>/dev/null | sed -n 3,8p
echo "[$(date +%T)] CHAIN_COLD14_DONE"
