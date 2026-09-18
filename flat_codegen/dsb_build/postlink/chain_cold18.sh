#!/usr/bin/env bash
# Round 33: confirmation — best plan arm of the night (by in-round ratio vs gs) with 5 interleaved reps against gs and its twin,
# plus the wake burst on top if round 29 showed a gain.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD17_DONE logs/chain_cold17.log 2>/dev/null; do sleep 15; done
read -r BEST WAKE <<< "$(python3 - <<'PY'
import csv,statistics,collections
def med(rnd):
    d=collections.defaultdict(list)
    try:
        for r in csv.DictReader(open(f'results/{rnd}/runs.csv')): d[r['arm']].append(float(r['cycles']))
    except FileNotFoundError: return {}
    return {a:statistics.median(v) for a,v in d.items() if len(v)>=2}
cands=[]
for rnd,arms in (('round24',['cold8']),('round27',['cold10']),('round30',['cold11']),('round31',['cold12','cold13']),('round32',['cold14'])):
    m=med(rnd)
    for a in arms:
        if a in m and 'gs' in m: cands.append((m['gs']/m[a],a))
best=max(cands)[1] if cands else 'cold8'
m=med('round29'); wake='0'
for a in list(m):
    if a.endswith('w32') and a[:-3] in m and m[a[:-3]]/m[a]>1.01: wake='32'
    if a.endswith('w64') and a[:-3] in m and m[a[:-3]]/m[a]>1.01 and (wake=='0' or m[a]<m[a[:-3]+'w32']): wake='64'
print(best, wake)
PY
)"; echo "[$(date +%T)] best=$BEST wake=$WAKE"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g; WL=/dsb/postlink/warmup
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BEST=$DB/out_utl_$BEST:$L:dsb-deps-g:-:-:64:0:20000:0"
[[ -f $DB/out_utl_${BEST}nop/UserTimelineService ]] && ARMS="$ARMS ${BEST}_nop=$DB/out_utl_${BEST}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
[[ $WAKE != 0 ]] && ARMS="$ARMS ${BEST}w$WAKE=$DB/out_utl_$BEST:$L:dsb-deps-g:$WL/libwarmup.so:$WL/list_fs_top256.txt:$WAKE:0:20000:0"
echo "[$(date +%T)] round33 arms: $ARMS"; ./dsb_warm_ab2.sh results/round33 5 $ARMS > logs/round33.log 2>&1
python3 summarize_ab.py results/round33/runs.csv gs 2>/dev/null | sed -n 3,7p
echo "[$(date +%T)] CHAIN_COLD18_DONE"
