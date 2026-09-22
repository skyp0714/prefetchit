#!/usr/bin/env bash
# Stage-0 add-on for a pass-built arm: PT-trace that binary (its layout differs), rebuild the per-run-type lists + mark sites + next
# queues for it, and emit the WS_LIST file the LD_PRELOAD runtime needs. Usage: ws_stage0.sh ARM [DUR=0.1]   (stack up, arm recreated)
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
ARM=$1; DUR=${2:-0.1}; export RATE=${RATE:-600}
bash $WS/ws_recreate.sh $ARM - - > /dev/null; sleep 2
RATE=$RATE PT_MODE=cpu CORES=0-7 AUXMM=512M bash $WS/ws_pt_trace.sh $WS/pt_$ARM $ARM $DUR 2>&1 | tail -2
rm -rf $WS/symfs_$ARM/custom && mkdir -p $WS/symfs_$ARM/custom && cp $DB/out_mid_$ARM/MovieIdService $WS/symfs_$ARM/custom/MovieIdService
bash $WS/ws_marks.sh $DB/out_mid_$ARM/MovieIdService > $WS/marks_$ARM.txt; wc -l < $WS/marks_$ARM.txt
taskset -c 40-42 python3 $WS/run_paths.py $WS/pt_$ARM --symfs $WS/symfs_$ARM --marks $WS/marks_$ARM.txt 2>&1 | grep -E "^runs|^type (Upload|none__m[0-9]+):" | cut -c1-150
python3 - $WS/pt_$ARM/runs <<'PY'
import collections, sys
rows=[l.rstrip('\n').split('\t') for l in open(sys.argv[1]+'/runs.tsv')][1:]
by=collections.defaultdict(list)
for r in rows: by[r[0]].append(r)
succ=collections.defaultdict(collections.Counter)
for tid,rs in by.items():
    rs.sort(key=lambda r: float(r[1]))
    for a,b in zip(rs,rs[1:]): succ[(a[4],a[6])][(b[3],b[4],b[6])]+=1
with open(sys.argv[1]+'/next.tsv','w') as f:
    f.write("#from_method\tfrom_mark\tnext_hook\tnext_method\tnext_mark\tshare\tn\n")
    for k,c in succ.items():
        tot=sum(c.values())
        for (h,m,mk),n in c.most_common(3): f.write(f"{k[0]}\t{k[1]}\t{h}\t{m}\t{mk}\t{n/tot:.2f}\t{n}\n")
PY
python3 $WS/ws_lists.py $WS/pt_$ARM/runs $WS/plan_$ARM.list --p-min 0.5 --pair --auto-sites $WS/marks_$ARM.txt --next $WS/pt_$ARM/runs/next.tsv 2>&1 | grep -E "^site|^next" | head -20
echo "STAGE0_LIST_DONE $WS/plan_$ARM.list"
