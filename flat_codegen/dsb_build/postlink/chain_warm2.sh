#!/usr/bin/env bash
# After round 11: round 12 = paced large warm-ups (N=512/1024 lines per wake, 32-line batches with pauses), unpinned, with twins.
PL=/home/hnpark2/prefetchit/flat_codegen/dsb_build/postlink; DB=/home/hnpark2/prefetchit/flat_codegen/dsb_build; cd $PL
until grep -q AB_DONE logs/round11.log 2>/dev/null; do sleep 10; done
B=$DB/out_utl_g:$DB/libs_utl_g:dsb-deps-g; L=/dsb/postlink/warmup
echo "[$(date +%T)] round12 start"
./dsb_warm_ab2.sh results/round12 3 g=$B:-:-:64:0:20000:0 wp512=$B:$L/libwarmup_p.so:$L/list_top1024.txt:512:0:20000:8 wp512_nop=$B:$L/libwarmup_p_nop.so:$L/list_top1024.txt:512:0:20000:8 wp1024=$B:$L/libwarmup_p.so:$L/list_top1024.txt:1024:0:20000:8 wp1024_nop=$B:$L/libwarmup_p_nop.so:$L/list_top1024.txt:1024:0:20000:8 > logs/round12.log 2>&1
echo "[$(date +%T)] CHAIN_WARM2_DONE"
