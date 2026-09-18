#!/bin/bash
# Build UserTimelineService (+ deps libs) with clang-19 and optional plan-free pass modes inside a dsb-deps image.
# Usage: build_utl_variant.sh <variant> <deps-image> ["PREFETCHIT_CALLEE_BURST_LINES=3 ..."]
# Output: out_utl_<variant>/UserTimelineService and libs_utl_<variant>/ (image's /usr/local/lib), plus NOP twins.
set -e
cd "$(dirname "$0")"
V=$1; IMG=$2; ENVS=${3:-}
ROOT=/home/hnpark2/prefetchit; PASSDIR=$ROOT/llvm_prefetchit/build; SN=$ROOT/benchmarks/DeathStarBench/socialNetwork
NOPTOOL=$ROOT/llvm_prefetchit/tools/make_nop_control_binary.py
PF=""; [[ -n "$ENVS" ]] && PF="-fpass-plugin=/pass/PrefetchITPass.so"
mkdir -p out_utl_$V
docker run --rm -v "$SN":/src -v "$PASSDIR":/pass -v "$PWD":/dsb --entrypoint bash $IMG -c "export ${ENVS:-PREFETCHIT_DUMMY=1} MAKE_TARGET=UserTimelineService && bash /dsb/build_service.sh /dsb/out_utl_$V -O2 -g -Wno-enum-constexpr-conversion -Wno-error $PF" > out_utl_$V/build.log 2>&1 || { tail -20 out_utl_$V/build.log; exit 1; }
docker rm -f libext_utl_$V 2>/dev/null || true
docker create --name libext_utl_$V $IMG >/dev/null; rm -rf libs_utl_$V; docker cp libext_utl_$V:/usr/local/lib ./libs_utl_$V; docker rm libext_utl_$V >/dev/null
n=$(objdump -d out_utl_$V/UserTimelineService | grep -cE "prefetcht1|prefetchit" || true); echo "UserTimelineService.$V: $n prefetcht1"
for so in libs_utl_$V/*.so.*; do [ -L "$so" ] && continue; m=$(objdump -d "$so" 2>/dev/null | grep -cE "prefetcht1|prefetchit" || true); echo "  $(basename $so): $m"; done
if [[ $n -gt 0 ]]; then
  python3 $NOPTOOL --input out_utl_$V/UserTimelineService --output out_utl_$V/UserTimelineService.nop; chmod 755 out_utl_$V/UserTimelineService.nop
  rm -rf libs_utl_${V}nop && cp -a libs_utl_$V libs_utl_${V}nop
  for so in libs_utl_${V}nop/*.so.*; do [ -L "$so" ] && continue; m=$(objdump -d "$so" 2>/dev/null | grep -cE "prefetcht1|prefetchit" || true); [[ $m -gt 0 ]] && { python3 $NOPTOOL --input "$so" --output "$so.nop" && mv "$so.nop" "$so"; chmod 755 "$so"; }; done
fi
echo "BUILD_UTL_DONE $V"
