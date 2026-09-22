#!/usr/bin/env bash
# Build the movie-id fat-static binary WITH the wake-stream marks (source patched by ws_patch_src.sh apply) as arm 'wsm'.
# Waits until no PT record is in flight (the build would disturb the capture), then builds like gs (-O3, FATSTATIC, no pass).
set -u
DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build
while pgrep -f "^bash ws_pt_trace.sh" > /dev/null && ! [ -s $DB/media/ws/pt5/perf_record.log ]; do sleep 3; done; sleep 5
echo "[$(date +%T)] build wsm"
cd $DB && STACK=mediaMicroservices SVCBIN=MovieIdService OUTPFX=mid OPTLEVEL=-O3 FATSTATIC=1 timeout 2400 bash $DB/build_utl_variant.sh wsm dsb-deps-jammy "" 2>&1 | tail -3
nm -C $DB/out_mid_wsm/MovieIdService | grep -c " w ws_mark" ; objdump -d $DB/out_mid_wsm/MovieIdService | grep -c "ws_mark"
echo "[$(date +%T)] WSM_BUILD_DONE"
