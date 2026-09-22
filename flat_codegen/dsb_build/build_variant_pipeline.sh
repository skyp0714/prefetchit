#!/bin/bash
source "$(dirname "${BASH_SOURCE[0]}")/../scripts/project_env.sh"
# For each plan variant: (1) rebuild deps libs with pass+plan into image
# dsb-deps-<v>, (2) build PostStorageService with pass+plan in that image,
# (3) extract /usr/local/lib -> libs_<v>, (4) make layout-identical NOP
# twins (libs_<v>nop + variants/PostStorageService.<v>_nop) by in-place
# prefetch->NOP patching.
# Usage: build_variant_pipeline.sh <variant> [<variant> ...]
set -e
cd "$(dirname "$0")"
DSB=$PWD
PASSDIR=${PREFETCHIT_ROOT}/llvm_prefetchit/build
SN=${PREFETCHIT_ROOT}/benchmarks/DeathStarBench/socialNetwork
NOPTOOL=${PREFETCHIT_ROOT}/llvm_prefetchit/tools/make_nop_control_binary.py

for v in "$@"; do
  PLAN=$DSB/plan_$v/prefetchit.plan.json
  [ -f "$PLAN" ] || { echo "missing $PLAN"; exit 1; }
  echo "=== [$v] deps rebuild ==="
  if sudo docker image inspect dsb-deps-$v >/dev/null 2>&1; then
    echo "image dsb-deps-$v exists, skipping"
  else
    cp plan_$v/libs.plan.json plan_$v/libs.$v.plan.json
    bash rebuild_deps_g.sh dsb-deps-$v "plan_$v/libs.$v.plan.json"
  fi

  echo "=== [$v] main binary build ==="
  mkdir -p out_$v
  sudo docker run --rm \
    -v "$SN":/src -v "$PASSDIR":/pass -v "$DSB":/dsb \
    --entrypoint bash dsb-deps-$v -c \
    "export PREFETCHIT_PLAN=/dsb/plan_$v/main.plan.json MAKE_TARGET=PostStorageService && bash /dsb/build_service.sh /dsb/out_$v -fpass-plugin=/pass/PrefetchITPass.so -Wno-error=enum-constexpr-conversion"
  cp out_$v/PostStorageService variants/PostStorageService.${v}_inj

  echo "=== [$v] extract libs ==="
  sudo docker rm -f libext_$v 2>/dev/null || true
  sudo docker create --name libext_$v dsb-deps-$v >/dev/null
  rm -rf libs_$v
  sudo docker cp libext_$v:/usr/local/lib ./libs_$v
  sudo docker rm libext_$v >/dev/null
  sudo chown -R "$(id -u):$(id -g)" libs_$v

  echo "=== [$v] injection verification ==="
  tot=0
  for f in libs_$v/libmongoc-1.0.so.0.0.0 libs_$v/libbson-1.0.so.0.0.0 \
           libs_$v/libthrift.so.0.12.0 libs_$v/libjaegertracing.so.0.4.2 \
           libs_$v/libopentracing.so.1.5.1 variants/PostStorageService.${v}_inj; do
    [ -f "$f" ] || continue
    n=$(objdump -d "$f" 2>/dev/null | grep -c prefetcht1 || true)
    echo "  $f: $n prefetcht1"
    tot=$((tot+n))
  done
  [ "$tot" -gt 0 ] || { echo "VERIFY_FAILED: zero prefetches in $v"; exit 1; }

  echo "=== [$v] NOP twins ==="
  rm -rf libs_${v}nop && cp -a libs_$v libs_${v}nop
  for so in libs_${v}nop/*.so.*; do
    [ -L "$so" ] && continue
    n=$(objdump -d "$so" 2>/dev/null | grep -c prefetcht1 || true)
    if [ "$n" -gt 0 ]; then
      echo "  patching $so ($n prefetches)"
      python3 "$NOPTOOL" --input "$so" --output "$so.nop" && mv "$so.nop" "$so"
      chmod 755 "$so"
    fi
  done
  python3 "$NOPTOOL" --input variants/PostStorageService.${v}_inj \
    --output variants/PostStorageService.${v}_nop
  chmod 755 variants/PostStorageService.${v}_nop
  echo "=== [$v] DONE ==="
done
echo ALL_VARIANTS_DONE
