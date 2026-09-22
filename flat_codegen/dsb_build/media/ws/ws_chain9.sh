#!/usr/bin/env bash
# Round 9 build: p6c plan with PIC-aware burst sizes (archive sites emit GOT-form prefetches, so their k was too small and the offsets
# of lines after those sites drifted). Build only; round 8 (stage 0) then uses it as BEST and compares against p6c in-round.
set -u
WS=/home/hnpark2/prefetchit/flat_codegen/dsb_build/media/ws; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
until grep -q "WS_CHAIN7B_DONE" $WS/logs/chain7b.log 2>/dev/null; do sleep 15; done
echo "[$(date +%T)] deps+service build p9"
cd $DB && EXTRA_PASS_ENV="PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_p9.json" timeout 3600 bash $DB/rebuild_deps_static.sh dsb-deps-tmp - > $WS/logs/deps_p9.log 2>&1; echo "drift warnings in archives: $(grep -c 'offsets drift' $WS/logs/deps_p9.log)"
STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh p9 dsb-deps-tmp "PREFETCHIT_COLD_PLAN=/dsb/media/ws/plan_p9.json" 2>&1 | tail -1
echo "p9 prefetcht1 in exe: $(objdump -d $DB/out_mid_p9/MovieIdService 2>/dev/null | grep -c prefetcht1); drift warnings in exe build: $(grep -c 'offsets drift' $DB/out_mid_p9/build.log)"
docker rmi dsb-deps-tmp > /dev/null 2>&1; docker image prune -f > /dev/null 2>&1
echo "[$(date +%T)] WS_CHAIN9_DONE"
