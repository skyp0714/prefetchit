#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "usage: $0 BENCHMARK BINARY PROFILE_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
BENCHMARK="$1"
BINARY="$(readlink -f "$2")"
SOURCE_BINARY="$(readlink -f "${SOURCE_BINARY:-${BINARY}}")"
PROFILES="$(readlink -f "$3")"
OUT="$(readlink -m "$4")"
PLANNER="${ROOT}/tools/prefetchit_trace_to_plan.py"
EXTERNAL_PLANNER="${ROOT}/tools/prefetchit_external_got_plan.py"
MERGER="${ROOT}/tools/merge_prefetch_plans.py"
DERIVER="${ROOT}/tools/derive_prefetch_plan.py"
READELF="${READELF:-llvm-readelf-19}"
SELECTION_MODE="${SELECTION_MODE:-top-sites}"
EXCLUDE_SITE_TARGET_SAME_CACHELINE="${EXCLUDE_SITE_TARGET_SAME_CACHELINE:-1}"
POST_FILTER_SITE_BUDGET="${POST_FILTER_SITE_BUDGET:-1}"

case "${SELECTION_MODE}" in
  top-sites|greedy) ;;
  *)
    echo "unsupported SELECTION_MODE=${SELECTION_MODE}; expected top-sites or greedy" >&2
    exit 2
    ;;
esac

case "${EXCLUDE_SITE_TARGET_SAME_CACHELINE}" in
  0|1) ;;
  *)
    echo "EXCLUDE_SITE_TARGET_SAME_CACHELINE must be 0 or 1" >&2
    exit 2
    ;;
esac
case "${POST_FILTER_SITE_BUDGET}" in
  0|1) ;;
  *)
    echo "POST_FILTER_SITE_BUDGET must be 0 or 1" >&2
    exit 2
    ;;
esac

[[ -x "${BINARY}" && -x "${SOURCE_BINARY}" ]] || {
  echo "missing executable binary: validation=${BINARY} source=${SOURCE_BINARY}" >&2
  exit 2
}

if [[ "${SOURCE_BINARY}" != "${BINARY}" ]]; then
  validation_sections="$(${READELF} -SW "${BINARY}")"
  source_sections="$(${READELF} -SW "${SOURCE_BINARY}")"
  validation_text="$(awk '$2 == ".text" {print $4 ":" $6}' <<< "${validation_sections}")"
  source_text="$(awk '$2 == ".text" {print $4 ":" $6}' <<< "${source_sections}")"
  [[ -n "${validation_text}" && "${validation_text}" == "${source_text}" ]] || {
    echo "source/validation .text layout mismatch: ${source_text} != ${validation_text}" >&2
    exit 2
  }
  diff -q \
    <(nm -n --defined-only "${BINARY}" | awk '$2 ~ /^[tTwW]$/ {print $1, $2, $3}') \
    <(nm -n --defined-only "${SOURCE_BINARY}" | awk '$2 ~ /^[tTwW]$/ {print $1, $2, $3}') \
    >/dev/null || {
      echo "source/validation text symbol maps differ" >&2
      exit 2
    }
  grep -q '\.debug_line' <<< "${source_sections}" || {
    echo "source binary has no DWARF line table: ${SOURCE_BINARY}" >&2
    exit 2
  }
fi

mapfile -t traces < <(awk -F, '$3 == "ok" {print $8}' "${PROFILES}/profiles.csv")
if [[ "${#traces[@]}" -lt 3 ]]; then
  echo "need at least three valid traces in ${PROFILES}/profiles.csv" >&2
  exit 2
fi
trace_args=()
for trace in "${traces[@]}"; do
  [[ -s "${trace}/lbr_symbolic_dump.txt" && -s "${trace}/lbr_raw_dump.txt" ]] || {
    echo "missing LBR dumps in ${trace}" >&2
    exit 2
  }
  trace_args+=(--trace-dir "${trace}")
done

mkdir -p "${OUT}/base" "${OUT}/variants"
{
  printf 'validation_binary=%s\n' "${BINARY}"
  printf 'validation_sha256=%s\n' "$(sha256sum "${BINARY}" | awk '{print $1}')"
  printf 'source_binary=%s\n' "${SOURCE_BINARY}"
  printf 'source_sha256=%s\n' "$(sha256sum "${SOURCE_BINARY}" | awk '{print $1}')"
  printf 'selection_mode=%s\n' "${SELECTION_MODE}"
} > "${OUT}/binary_layout.conf"
printf 'benchmark,label,coverage_pct,depth_min,depth_max,site_budget,byte_offsets,exclude_same_cacheline,injections,prefetches,targets,filtered_same_cacheline,plan\n' \
  > "${OUT}/plan_matrix.csv"

derive() {
  local coverage="$1" depth_min="$2" depth_max="$3" budget="$4" offsets="$5" label="$6"
  local input="${OUT}/base/cov${coverage}/combined.plan.json"
  local output="${OUT}/variants/${label}/prefetchit.plan.json"
  local filter_args=() budget_args=()
  if [[ "${EXCLUDE_SITE_TARGET_SAME_CACHELINE}" == 1 ]]; then
    filter_args+=(--exclude-site-target-same-cacheline)
  fi
  if [[ "${POST_FILTER_SITE_BUDGET}" == 1 ]]; then
    budget_args+=(--sites-per-target-after-filter "${budget}")
  else
    budget_args+=(--max-site-rank "${budget}")
  fi
  python3 "${DERIVER}" --input "${input}" --output "${output}" --label "${label}" \
    --depth-min "${depth_min}" --depth-max "${depth_max}" \
    --byte-offsets "${offsets}" "${filter_args[@]}" "${budget_args[@]}" \
    > "${OUT}/variants/${label}.log" 2>&1
  printf '%s,%s,%s,%s,%s,%s,"%s",%s,%s,%s,%s,%s,%s\n' \
    "${BENCHMARK}" "${label}" "${coverage}" "${depth_min}" "${depth_max}" \
    "${budget}" "${offsets}" "${EXCLUDE_SITE_TARGET_SAME_CACHELINE}" \
    "$(jq -r '.stats.selected_injections' "${output}")" \
    "$(jq -r '.stats.planned_prefetches' "${output}")" \
    "$(jq -r '.stats.selected_targets_with_injections // .stats.selected_targets' "${output}")" \
    "$(jq -r '.stats.same_cacheline_injections_filtered' "${output}")" \
    "${output}" >> "${OUT}/plan_matrix.csv"
}

for coverage in 25 50 75 100; do
  base="${OUT}/base/cov${coverage}"
  mkdir -p "${base}/internal" "${base}/external"
  if [[ "${REUSE_INTERNAL:-0}" != 1 || ! -s "${base}/internal/prefetchit.plan.json" ]]; then
    python3 "${PLANNER}" "${trace_args[@]}" --binary "${SOURCE_BINARY}" \
      --validation-binary "${BINARY}" --output "${base}/internal/prefetchit.plan.json" \
      --summary-dir "${base}/internal" --top-k 999999 --target-coverage-pct "${coverage}" \
      --depth-min 1 --depth 32 --site-budget-per-target 32 --candidate-pool 0 \
      --selection-mode "${SELECTION_MODE}" --target-ip-source lbr-to --allow-unresolved-targets \
      --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0 \
      > "${base}/internal/plan.log" 2>&1
  fi
  if [[ "${REUSE_EXTERNAL:-0}" != 1 || ! -s "${base}/external/prefetchit.plan.json" ]]; then
    python3 "${EXTERNAL_PLANNER}" "${trace_args[@]}" --binary "${BINARY}" \
      --output "${base}/external/prefetchit.plan.json" --summary-dir "${base}/external" \
      --target-coverage-pct "${coverage}" --depth-min 1 --depth 32 \
      --site-budget-per-target 32 --selection-mode "${SELECTION_MODE}" \
      --prefetch-mnemonic prefetcht1 \
      --prefetch-byte-offsets 0 > "${base}/external/plan.log" 2>&1
  fi
  python3 "${MERGER}" --label "${BENCHMARK}_cov${coverage}_full" \
    --plan "${base}/internal/prefetchit.plan.json" \
    --plan "${base}/external/prefetchit.plan.json" \
    --output "${base}/combined.plan.json" > "${base}/merge.log" 2>&1

  for budget in 1 2 4 8 16 32; do
    derive "${coverage}" 1 32 "${budget}" 0 "cov${coverage}_d1_32_b${budget}_o0"
    derive "${coverage}" 1 32 "${budget}" 0,64 "cov${coverage}_d1_32_b${budget}_o064"
  done
done

for depth in 8 16; do
  derive 100 1 "${depth}" 16 0 "cov100_d1_${depth}_b16_o0"
  derive 100 1 "${depth}" 16 0,64 "cov100_d1_${depth}_b16_o064"
done
for depth_min in 4 8; do
  derive 100 "${depth_min}" 32 16 0 "cov100_d${depth_min}_32_b16_o0"
  derive 100 "${depth_min}" 32 16 0,64 "cov100_d${depth_min}_32_b16_o064"
done

# Lower-coverage plans are usually the best overhead/timeliness tradeoff. Keep
# explicit earlier-history variants so screens can remove depth-1--3 sites.
for coverage in 25 50; do
  for depth_min in 4 8; do
    for budget in 1 2 4 8; do
      derive "${coverage}" "${depth_min}" 32 "${budget}" 0 \
        "cov${coverage}_d${depth_min}_32_b${budget}_o0"
      derive "${coverage}" "${depth_min}" 32 "${budget}" 0,64 \
        "cov${coverage}_d${depth_min}_32_b${budget}_o064"
    done
  done
done

python3 - "${BENCHMARK}" "${PROFILES}" "${OUT}" "${BINARY}" "${SOURCE_BINARY}" <<'PY'
import csv, json, pathlib, sys

benchmark, profiles_raw, out_raw, validation_binary, source_binary = sys.argv[1:]
profiles = pathlib.Path(profiles_raw)
out = pathlib.Path(out_raw)
rows = list(csv.DictReader((profiles / "profiles.csv").open()))
valid = [row for row in rows if row["status"] == "ok"]
audit = {
    "benchmark": benchmark,
    "profile_dir": str(profiles),
    "validation_binary": validation_binary,
    "source_binary": source_binary,
    "valid_profiles": valid,
}
for coverage in (25, 50, 75, 100):
    base = out / "base" / f"cov{coverage}"
    audit[f"cov{coverage}"] = {
        "internal": json.loads((base / "internal" / "prefetchit.plan.json").read_text())["stats"],
        "external": json.loads((base / "external" / "prefetchit.plan.json").read_text())["stats"],
        "combined": json.loads((base / "combined.plan.json").read_text())["stats"],
    }
(out / "audit_summary.json").write_text(json.dumps(audit, indent=2) + "\n")
PY

cat "${OUT}/plan_matrix.csv"
