#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${PREFETCHIT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
WITH_BENCHMARKS=0
APPLY_PATCHES=0
COPY_SPEC_CONFIGS=0

usage() {
  cat <<'EOF'
Usage: bootstrap.sh [options]

  --root PATH          Destination PrefetchIT root (default: parent of llvm_prefetchit)
  --with-benchmarks    Clone/download pinned benchmark source trees
  --apply-patches      Apply the saved benchmark/JDK source patches
  --copy-spec-configs  Copy PrefetchIT configs into installed SPEC CPU trees
  -h, --help           Show this help

The script never downloads traces, result trees, benchmark datasets, or build outputs.
It refuses to replace a dirty checkout.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$(readlink -m "${2:?missing --root value}")"; shift 2 ;;
    --with-benchmarks) WITH_BENCHMARKS=1; shift ;;
    --apply-patches) APPLY_PATCHES=1; shift ;;
    --copy-spec-configs) COPY_SPEC_CONFIGS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[err] unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

mkdir -p "${ROOT}"

clone_component() {
  local rel="$1" url="$2" branch="$3" revision="$4" dest="${ROOT}/$1"
  if [[ "${revision}" == "SELF" ]]; then
    return
  fi
  if [[ -e "${dest}" && ! -d "${dest}/.git" ]]; then
    echo "[err] refusing non-git destination: ${dest}" >&2
    return 1
  fi
  if [[ ! -d "${dest}/.git" ]]; then
    mkdir -p "$(dirname "${dest}")"
    git clone --filter=blob:none "${url}" "${dest}"
  elif [[ -n "$(git -C "${dest}" status --porcelain)" ]]; then
    echo "[err] refusing dirty component checkout: ${dest}" >&2
    return 1
  fi
  git -C "${dest}" fetch --all --tags --prune
  git -C "${dest}" cat-file -e "${revision}^{commit}"
  git -C "${dest}" checkout -B "${branch}" "${revision}"
  if git -C "${dest}" show-ref --verify --quiet "refs/remotes/origin/${branch}"; then
    git -C "${dest}" branch --set-upstream-to="origin/${branch}" "${branch}" >/dev/null
  fi
  echo "[ok] ${rel} @ ${revision}"
}

while IFS=$'\t' read -r rel url branch revision role; do
  [[ -z "${rel}" || "${rel}" == \#* ]] && continue
  clone_component "${rel}" "${url}" "${branch}" "${revision}"
done < "${SCRIPT_DIR}/repos.lock.tsv"

clone_benchmark() {
  local rel="$1" url="$2" revision="$3" mode="$4" dest="${ROOT}/$1"
  if [[ -e "${dest}" && ! -d "${dest}/.git" ]]; then
    echo "[err] refusing non-git benchmark destination: ${dest}" >&2
    return 1
  fi
  if [[ ! -d "${dest}/.git" ]]; then
    mkdir -p "$(dirname "${dest}")"
    git clone --filter=blob:none --no-checkout "${url}" "${dest}"
  elif [[ -n "$(git -C "${dest}" status --porcelain)" ]]; then
    echo "[err] refusing dirty benchmark checkout: ${dest}" >&2
    return 1
  fi
  git -C "${dest}" fetch origin "${revision}"
  git -C "${dest}" checkout --detach "${revision}"
  if [[ "${mode}" == "recursive" ]]; then
    git -C "${dest}" submodule update --init --recursive
  fi
  echo "[ok] ${rel} @ ${revision}"
}

install_archive() {
  local rel="$1" url="$2" checksum="$3" dest="${ROOT}/$1"
  local cache="${ROOT}/.cache/prefetchit/$(basename "${url}")"
  if [[ -d "${dest}" ]]; then
    echo "[ok] archive source already exists: ${rel}"
    return
  fi
  mkdir -p "$(dirname "${dest}")" "$(dirname "${cache}")"
  curl -fL --retry 3 -o "${cache}" "${url}"
  printf '%s  %s\n' "${checksum}" "${cache}" | sha256sum --check --status
  tar -xf "${cache}" -C "$(dirname "${dest}")"
  [[ -d "${dest}" ]] || { echo "[err] archive did not create ${dest}" >&2; return 1; }
  echo "[ok] ${rel} sha256=${checksum}"
}

create_gem5_variant() {
  local rel="$1" revision="$2" patch_name="$3" dest="${ROOT}/$1"
  local base="${ROOT}/benchmarks/gem5" patch_file="${SCRIPT_DIR}/patches/${patch_name}"
  if [[ ! -e "${dest}" ]]; then
    mkdir -p "$(dirname "${dest}")"
    git -C "${base}" worktree add --detach "${dest}" "${revision}"
  fi
  if git -C "${dest}" apply --check "${patch_file}"; then
    git -C "${dest}" apply "${patch_file}"
  elif ! git -C "${dest}" apply --reverse --check "${patch_file}"; then
    echo "[err] ${patch_name} does not apply to ${rel}" >&2
    return 1
  fi
  echo "[ok] ${rel} with ${patch_name}"
}

if [[ "${WITH_BENCHMARKS}" == 1 ]]; then
  while IFS=$'\t' read -r rel kind url revision patch_name mode; do
    [[ -z "${rel}" || "${rel}" == \#* ]] && continue
    case "${kind}" in
      git) clone_benchmark "${rel}" "${url}" "${revision}" "${mode}" ;;
      archive) install_archive "${rel}" "${url}" "${revision}" ;;
      variant) create_gem5_variant "${rel}" "${revision}" "${patch_name}" ;;
      post-install|spec-iso) echo "[defer] ${rel}: ${kind}" ;;
      *) echo "[err] unsupported benchmark kind ${kind}" >&2; exit 1 ;;
    esac
  done < "${SCRIPT_DIR}/benchmarks.lock.tsv"
fi

if [[ "${APPLY_PATCHES}" == 1 ]]; then
  PREFETCHIT_ROOT="${ROOT}" "${SCRIPT_DIR}/apply_patches.sh"
fi

if [[ "${COPY_SPEC_CONFIGS}" == 1 ]]; then
  for suite in spec2017 spec2026; do
    year="${suite#spec}"
    src="${SCRIPT_DIR}/config/${suite}"
    dest="${ROOT}/benchmarks/cpu${year}/config"
    if [[ -d "${dest}" ]]; then
      cp -f "${src}"/*.cfg "${dest}/"
      echo "[ok] copied ${suite} configs"
    else
      echo "[defer] install SPEC CPU${year}, then rerun --copy-spec-configs"
    fi
  done
fi

echo "[done] bootstrap completed under ${ROOT}"
