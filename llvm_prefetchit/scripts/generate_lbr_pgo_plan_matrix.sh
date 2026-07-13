#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "usage: $0 BENCHMARK BINARY PROFILE_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
BENCHMARK="$1"
BINARY="$(readlink -f "$2")"
PROFILES="$(readlink -f "$3")"
OUT="$(readlink -m "$4")"
PLANNER="${ROOT}/tools/prefetchit_trace_to_plan.py"
EXTERNAL_PLANNER="${ROOT}/tools/prefetchit_external_got_plan.py"
MERGER="${ROOT}/tools/merge_prefetch_plans.py"
DERIVER="${ROOT}/tools/derive_prefetch_plan.py"

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
printf 'benchmark,label,coverage_pct,depth_min,depth_max,site_budget,byte_offsets,injections,prefetches,targets,plan\n' \
  > "${OUT}/plan_matrix.csv"

derive() {
  local coverage="$1" depth_min="$2" depth_max="$3" budget="$4" offsets="$5" label="$6"
  local input="${OUT}/base/cov${coverage}/combined.plan.json"
  local output="${OUT}/variants/${label}/prefetchit.plan.json"
  python3 "${DERIVER}" --input "${input}" --output "${output}" --label "${label}" \
    --max-site-rank "${budget}" --depth-min "${depth_min}" --depth-max "${depth_max}" \
    --byte-offsets "${offsets}" > "${OUT}/variants/${label}.log" 2>&1
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "${BENCHMARK}" "${label}" "${coverage}" "${depth_min}" "${depth_max}" \
    "${budget}" "${offsets}" \
    "$(jq -r '.stats.selected_injections' "${output}")" \
    "$(jq -r '.stats.planned_prefetches' "${output}")" \
    "$(jq -r '.stats.selected_targets_with_injections // .stats.selected_targets' "${output}")" \
    "${output}" >> "${OUT}/plan_matrix.csv"
}

for coverage in 25 50 75 100; do
  base="${OUT}/base/cov${coverage}"
  mkdir -p "${base}/internal" "${base}/external"
  python3 "${PLANNER}" "${trace_args[@]}" --binary "${BINARY}" \
    --validation-binary "${BINARY}" --output "${base}/internal/prefetchit.plan.json" \
    --summary-dir "${base}/internal" --top-k 999999 --target-coverage-pct "${coverage}" \
    --depth-min 1 --depth 32 --site-budget-per-target 32 --candidate-pool 0 \
    --selection-mode top-sites --target-ip-source lbr-to --allow-unresolved-targets \
    --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0 \
    > "${base}/internal/plan.log" 2>&1
  python3 "${EXTERNAL_PLANNER}" "${trace_args[@]}" --binary "${BINARY}" \
    --output "${base}/external/prefetchit.plan.json" --summary-dir "${base}/external" \
    --target-coverage-pct "${coverage}" --depth-min 1 --depth 32 \
    --site-budget-per-target 32 --prefetch-mnemonic prefetcht1 \
    --prefetch-byte-offsets 0 > "${base}/external/plan.log" 2>&1
  python3 "${MERGER}" --label "${BENCHMARK}_cov${coverage}_full" \
    --plan "${base}/internal/prefetchit.plan.json" \
    --plan "${base}/external/prefetchit.plan.json" \
    --output "${base}/combined.plan.json" > "${base}/merge.log" 2>&1

  for budget in 4 8 16 32; do
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

python3 - "${BENCHMARK}" "${PROFILES}" "${OUT}" <<'PY'
import csv, json, pathlib, sys

benchmark, profiles_raw, out_raw = sys.argv[1:]
profiles = pathlib.Path(profiles_raw)
out = pathlib.Path(out_raw)
rows = list(csv.DictReader((profiles / "profiles.csv").open()))
valid = [row for row in rows if row["status"] == "ok"]
audit = {"benchmark": benchmark, "profile_dir": str(profiles), "valid_profiles": valid}
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
