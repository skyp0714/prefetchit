#!/usr/bin/env bash
# Inline-plan pipeline: g rebuild (with -g, pass-built hiredis/redis++) -> pinned trace -> per-binary plans -> operand fix
#  -> pgo deps image + service -> round10 (g / pgo / twins, unpinned and main@40:pool@41-44)
set -u
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; LL=/home/hnpark2/prefetchit/llvm_prefetchit
SN=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/socialNetwork; PI=$PL/plans/inline2; mkdir -p $PI; cd $DB
echo "[$(date +%T)] g rebuild"; bash rebuild_deps_env.sh dsb-deps-g - > $PL/logs/deps_g2.log 2>&1; rm -rf out_utl_g libs_utl_g; bash build_utl_variant.sh g dsb-deps-g "" > $PL/logs/build_utl_g2.log 2>&1; tail -1 $PL/logs/build_utl_g2.log
export PL UTL_BIN=$DB/out_utl_g UTL_LIBS=$DB/libs_utl_g UTL_IMG=dsb-deps-g
(cd $SN && docker compose -f docker-compose.yml -f $PL/compose-override-utl-g.yml up -d --force-recreate --no-deps user-timeline-service > $PL/logs/up_g2.log 2>&1); sleep 6
echo ps101899 | sudo -S nohup $PL/pin_threads.sh socialnetwork-user-timeline-service-1 40 41-44 > /dev/null 2>&1 & PINPID=$!; sleep 2
echo "[$(date +%T)] trace"; cd $PL; ./dsb_utl_trace.sh results/trace_g2_pin 40 2003 > logs/trace_g2_pin.log 2>&1
pid=$(docker inspect -f '{{.State.Pid}}' socialnetwork-user-timeline-service-1); echo ps101899 | sudo -S cat /proc/$pid/maps > results/trace_g2_pin/maps.txt 2>/dev/null
echo ps101899 | sudo -S pkill -P $PINPID > /dev/null 2>&1; echo ps101899 | sudo -S kill $PINPID > /dev/null 2>&1
cd results/trace_g2_pin; echo ps101899 | sudo -S perf script -i l2miss.data -F ip,sym,brstack > lbr_raw_dump.txt 2>/dev/null; echo ps101899 | sudo -S perf script -i l2miss.data -F ip,sym,brstacksym > lbr_symbolic_dump.txt 2>/dev/null; cd $PL
echo "[$(date +%T)] plans"
T=$LL/tools/prefetchit_trace_to_plan.py; OPTS="--target-ip-source sample-ip --target-coverage-pct 75 --site-budget-per-target 2 --depth 8 --depth-min 2 --prefetch-byte-offsets 0 --allow-unresolved-targets --nm llvm-nm-19"
timeout 900 python3 $T --trace-dir $PL/results/trace_g2_pin --binary $DB/out_utl_g/UserTimelineService --output $PI/main.raw.plan.json $OPTS > logs/plan2_main.log 2>&1
LIBS=""; for L in libjaegertracing.so.0.4.2 libmongoc-1.0.so.0.0.0 libbson-1.0.so.0.0.0 libthrift.so.0.12.0 libredis++.so.1.2.3; do [[ -f $DB/libs_utl_g/$L ]] || continue; timeout 900 python3 $T --trace-dir $PL/results/trace_g2_pin --binary $DB/libs_utl_g/$L --output $PI/$L.raw.plan.json $OPTS > logs/plan2_$L.log 2>&1 && LIBS="$LIBS $PI/$L.raw.plan.json"; done
docker run --rm --entrypoint bash dsb-deps-g -c 'for f in /usr/local/lib/*.so /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/libpthread.so.0 /usr/lib/x86_64-linux-gnu/libstdc++.so.6 /lib/x86_64-linux-gnu/libm.so.6; do [ -e "$f" ] || continue; nm -D --defined-only "$f" 2>/dev/null | awk -v f="$(basename $(readlink -f $f))" "\$2 ~ /[TWi]/ {print f, \$3}"; done' > $PI/dynsyms.txt 2>/dev/null
python3 $LL/tools/inline_fix_operands.py --main $PI/main.raw.plan.json --exe $DB/out_utl_g/UserTimelineService --dynsyms $PI/dynsyms.txt --libs $LIBS --static-prefixes /opt/src/hiredis,/opt/src/redis-plus-plus,/tmp/hiredis,/tmp/redis-plus-plus --out-main $PI/main.plan.json --out-libs $PI/libs.plan.json | tee logs/plan2_fix.log
echo "[$(date +%T)] pgo build"; cd $DB; bash rebuild_deps_env.sh dsb-deps-pgo $PI/libs.plan.json > $PL/logs/deps_pgo2.log 2>&1; rm -rf out_utl_pgo libs_utl_pgo libs_utl_pgonop; bash build_utl_variant.sh pgo dsb-deps-pgo "PREFETCHIT_PLAN=/dsb/postlink/plans/inline2/main.plan.json" > $PL/logs/build_utl_pgo2.log 2>&1; grep -E "prefetcht1|BUILD_UTL" $PL/logs/build_utl_pgo2.log | grep -v ": 0$"
cd $PL; ARMS="g=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g gP=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g@40:41-44"
if [[ -f $DB/out_utl_pgo/UserTimelineService.nop ]]; then mkdir -p $DB/out_utl_pgonop; cp $DB/out_utl_pgo/UserTimelineService.nop $DB/out_utl_pgonop/UserTimelineService; ARMS="$ARMS pgo=$DB/out_utl_pgo:$DB/libs_utl_pgo:dsb-deps-pgo pgo_nop=$DB/out_utl_pgonop:$DB/libs_utl_pgonop:dsb-deps-pgo pgoP=$DB/out_utl_pgo:$DB/libs_utl_pgo:dsb-deps-pgo@40:41-44 pgoP_nop=$DB/out_utl_pgonop:$DB/libs_utl_pgonop:dsb-deps-pgo@40:41-44"; fi
echo "[$(date +%T)] round10 arms: $ARMS"; ./dsb_g_ab2.sh results/round10 3 $ARMS > logs/round10.log 2>&1
echo "[$(date +%T)] CHAIN_INLINE_DONE"
