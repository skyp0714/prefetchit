#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${PREFETCHIT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
PATCH_DIR="${SCRIPT_DIR}/patches"
STRICT=0

if [[ "${1:-}" == "--strict" ]]; then
  STRICT=1
elif [[ -n "${1:-}" ]]; then
  ROOT="$(readlink -m "$1")"
fi

apply_git_patch() {
  local rel="$1" patch="$2" dest="${ROOT}/$1" file="${PATCH_DIR}/$2"
  if [[ ! -d "${dest}/.git" && ! -f "${dest}/.git" ]]; then
    if [[ "${STRICT}" == 1 ]]; then
      echo "[err] missing git checkout: ${dest}" >&2
      return 1
    fi
    echo "[skip] ${rel} is not installed"
    return
  fi
  if git -C "${dest}" apply --check "${file}"; then
    git -C "${dest}" apply "${file}"
    echo "[ok] applied ${patch} to ${rel}"
  elif git -C "${dest}" apply --reverse --check "${file}"; then
    echo "[ok] already applied ${patch} to ${rel}"
  else
    echo "[err] ${patch} does not apply cleanly to ${rel}" >&2
    return 1
  fi
}

apply_plain_patch() {
  local rel="$1" patch="$2" dest="${ROOT}/$1" file="${PATCH_DIR}/$2"
  if [[ ! -d "${dest}" ]]; then
    if [[ "${STRICT}" == 1 ]]; then
      echo "[err] missing source directory: ${dest}" >&2
      return 1
    fi
    echo "[skip] ${rel} is not installed"
    return
  fi
  if patch --batch --forward --dry-run --silent -d "${dest}" -p1 < "${file}"; then
    patch --batch --forward --silent -d "${dest}" -p1 < "${file}"
    echo "[ok] applied ${patch} to ${rel}"
  elif patch --batch --reverse --dry-run --silent -d "${dest}" -p1 < "${file}"; then
    echo "[ok] already applied ${patch} to ${rel}"
  else
    echo "[err] ${patch} does not apply cleanly to ${rel}" >&2
    return 1
  fi
}

apply_git_patch benchmarks/dcperf dcperf-local.patch
apply_git_patch benchmarks/tailbench tailbench-local.patch
apply_git_patch benchmarks/datacenter_sources/MicroSuite microsuite-local.patch
apply_git_patch benchmarks/chipyard chipyard-local.patch
apply_git_patch benchmarks/datacenter_sources/CacheLib cachelib-getdeps.patch
apply_git_patch benchmarks/datacenter_sources/haproxy haproxy-task-prefetch.patch
apply_git_patch benchmarks/datacenter_sources/postgres postgres-control-flow-prefetch.patch
apply_git_patch benchmarks/datacenter_sources/redis redis-command-prefetch.patch
apply_git_patch jit_prefetch/openjdk openjdk-prefetch-combined.patch
apply_plain_patch benchmarks/datacenter_sources/memcached-1.6.14 memcached-control-data-prefetch.patch

# DCPerf creates this nested checkout only when django_workload is installed.
apply_git_patch benchmarks/dcperf/benchmarks/django_workload/django-workload django-workload-local.patch

echo "[done] available migration patches are applied"
