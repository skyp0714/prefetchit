#!/bin/bash
# Build $SVCBIN (+ deps libs) with clang-19 and optional plan-free pass modes inside a dsb-deps image.
# Usage: build_utl_variant.sh <variant> <deps-image> ["PREFETCHIT_CALLEE_BURST_LINES=3 ..."]
# Output: out_${OUTPFX}_<variant>/$SVCBIN and libs_${OUTPFX}_<variant>/ (image's /usr/local/lib), plus NOP twins.
set -e
cd "$(dirname "$0")"
V=$1; IMG=$2; ENVS=${3:-}
SVCBIN=${SVCBIN:-UserTimelineService}; OUTPFX=${OUTPFX:-utl}   # SVCBIN=ComposePostService OUTPFX=cps for compose-post
ROOT=/home/hnpark2/prefetchit; PASSDIR=$ROOT/llvm_prefetchit/build; SN=$ROOT/benchmarks/DeathStarBench/socialNetwork
NOPTOOL=$ROOT/llvm_prefetchit/tools/make_nop_control_binary.py
PF=""; [[ -n "$ENVS" ]] && PF="-fpass-plugin=/pass/PrefetchITPass.so"
mkdir -p out_${OUTPFX}_$V
docker run --rm -v "$SN":/src -v "$PASSDIR":/pass -v "$PWD":/dsb --entrypoint bash $IMG -c "export ${ENVS:-PREFETCHIT_DUMMY=1} MAKE_TARGET=$SVCBIN FATSTATIC=${FATSTATIC:-0} && bash /dsb/build_service.sh /dsb/out_${OUTPFX}_$V -O2 -g -Wno-enum-constexpr-conversion -Wno-error $PF" > out_${OUTPFX}_$V/build.log 2>&1 || { tail -20 out_${OUTPFX}_$V/build.log; exit 1; }
docker rm -f libext_${OUTPFX}_$V 2>/dev/null || true
docker create --name libext_${OUTPFX}_$V $IMG >/dev/null; rm -rf libs_${OUTPFX}_$V; docker cp libext_${OUTPFX}_$V:/usr/local/lib ./libs_${OUTPFX}_$V; docker rm libext_${OUTPFX}_$V >/dev/null
n=$(objdump -d out_${OUTPFX}_$V/$SVCBIN | grep -cE "prefetcht1|prefetchit" || true); echo "$SVCBIN.$V: $n prefetcht1"
for so in libs_${OUTPFX}_$V/*.so.*; do [ -L "$so" ] && continue; m=$(objdump -d "$so" 2>/dev/null | grep -cE "prefetcht1|prefetchit" || true); echo "  $(basename $so): $m"; done
if [[ $n -gt 0 ]]; then
  python3 $NOPTOOL --input out_${OUTPFX}_$V/$SVCBIN --output out_${OUTPFX}_$V/$SVCBIN.nop; chmod 755 out_${OUTPFX}_$V/$SVCBIN.nop
  rm -rf libs_${OUTPFX}_${V}nop && cp -a libs_${OUTPFX}_$V libs_${OUTPFX}_${V}nop
  for so in libs_${OUTPFX}_${V}nop/*.so.*; do [ -L "$so" ] && continue; m=$(objdump -d "$so" 2>/dev/null | grep -cE "prefetcht1|prefetchit" || true); [[ $m -gt 0 ]] && { python3 $NOPTOOL --input "$so" --output "$so.nop" && mv "$so.nop" "$so"; chmod 755 "$so"; }; done
fi
echo "BUILD_UTL_DONE $V"
