#!/usr/bin/env bash
# Round 36: 5-rep confirmation of the night's best plan arm (in-round ratio vs gs across rounds 24/32/34/35) against gs and its twin.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q CHAIN_COLD21_DONE logs/chain_cold21.log 2>/dev/null; do sleep 15; done
BEST=$(python3 - <<'PY'
import csv,statistics,collections
def med(rnd):
    d=collections.defaultdict(list)
    try:
        for r in csv.DictReader(open(f'results/{rnd}/runs.csv')):
            if float(r['rps'])>5000 and int(r['non2xx'])==0: d[r['arm']].append(float(r['cycles']))
    except FileNotFoundError: return {}
    return {a:statistics.median(v) for a,v in d.items() if len(v)>=2}
c=[]
for rnd,arms in (('round24',['cold8']),('round32',['cold14']),('round34',['cold15','cold16']),('round35',['cold17'])):
    m=med(rnd)
    for a in arms:
        if a in m and 'gs' in m: c.append((m['gs']/m[a],a))
print(max(c)[1] if c else 'cold14')
PY
); echo "[$(date +%T)] best=$BEST"
for c in $(docker ps --format '{{.Names}}' | grep -E "^socialnetwork|^hotelreservation"); do docker update --cpuset-cpus 0-35 $c > /dev/null 2>&1; done
export SHARED_CORES=0-35; L=$DB/libs_utl_g
ARMS="gs=$DB/out_utl_gs:$DB/libs_utl_gs:dsb-deps-g:-:-:64:0:20000:0 $BEST=$DB/out_utl_$BEST:$L:dsb-deps-g:-:-:64:0:20000:0"
[[ -f $DB/out_utl_${BEST}nop/UserTimelineService ]] && ARMS="$ARMS ${BEST}_nop=$DB/out_utl_${BEST}nop:$L:dsb-deps-g:-:-:64:0:20000:0"
echo "[$(date +%T)] round36 arms: $ARMS"; rm -rf results/round36; ./dsb_warm_ab2.sh results/round36 5 $ARMS > logs/round36.log 2>&1
python3 summarize_ab.py results/round36/runs.csv gs 2>/dev/null | sed -n 3,6p
echo "[$(date +%T)] CHAIN_COLD22_DONE"
