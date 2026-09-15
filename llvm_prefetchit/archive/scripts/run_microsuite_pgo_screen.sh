#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 BENCHMARK BIN_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNNER="${ROOT}/scripts/run_final_microsuite_variant.sh"
BENCHMARK="$1"
BINS="$(readlink -f "$2")"
OUT="$(readlink -m "$3")"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-5}"
EXPECTED_MID_TIDS="${EXPECTED_MID_TIDS:-0}"
DEFAULT_LABELS='baseline cov25_d1_32_b16_o0 cov25_d1_32_b16_o064 cov50_d1_32_b16_o0 cov50_d1_32_b16_o064 baseline cov75_d1_32_b16_o0 cov75_d1_32_b16_o064 cov100_d1_32_b16_o0 cov100_d1_32_b16_o064 baseline'
LABELS="${SCREEN_LABELS:-${DEFAULT_LABELS}}"

mkdir -p "${OUT}"
printf 'run_order,label,attempt,status,qps,l2i_mpki,cpu_migrations,mid_tids,summary\n' > "${OUT}/runs.csv"
run_order=0
failed_labels=()
for label in ${LABELS}; do
  run_order=$((run_order + 1))
  binary="${BINS}/mid_tier_server.${label}"
  [[ -x "${binary}" ]] || { echo "missing binary: ${binary}" >&2; exit 2; }
  status=failed
  for attempt in $(seq 1 "${MAX_ATTEMPTS}"); do
    run="${OUT}/run$(printf '%02d' "${run_order}")_${label}_attempt${attempt}"
    rm -rf "${run}"
    set +e
    "${RUNNER}" "${BENCHMARK}" "${label}" "${binary}" "${run}"
    runner_rc=$?
    set -e
    if [[ "${runner_rc}" -ne 0 || ! -s "${run}/summary.json" ]]; then
      printf '%s,%s,%s,runner_failed,nan,nan,nan,0,%s\n' \
        "${run_order}" "${label}" "${attempt}" "${run}/summary.json" \
        | tee -a "${OUT}/runs.csv"
      continue
    fi
    valid="$(jq -r '.valid' "${run}/summary.json")"
    qps="$(jq -r '.qps' "${run}/summary.json")"
    mpki="$(jq -r '.l2i_mpki' "${run}/summary.json")"
    migrations="$(jq -r '.cpu_migrations' "${run}/summary.json")"
    tids="$(jq -r '.mid_tids' "${run}/summary.json")"
    status=failed
    if [[ "${valid}" == 1 ]] && \
      ((EXPECTED_MID_TIDS == 0 || tids == EXPECTED_MID_TIDS)); then
      status=ok
    fi
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
      "${run_order}" "${label}" "${attempt}" "${status}" "${qps}" \
      "${mpki}" "${migrations}" "${tids}" "${run}/summary.json" \
      | tee -a "${OUT}/runs.csv"
    [[ "${status}" == ok ]] && break
  done
  if [[ "${status}" != ok ]]; then
    echo "no valid run for ${label}; continuing screen" >&2
    failed_labels+=("${label}")
  fi
done

python3 - "${OUT}" <<'PY'
import csv
import json
import math
import pathlib
import statistics
import sys
from collections import defaultdict

out = pathlib.Path(sys.argv[1])
rows = list(csv.DictReader((out / "runs.csv").open()))
valid = [row for row in rows if row["status"] == "ok"]
grouped = defaultdict(list)
for row in valid:
    grouped[row["label"]].append(row)
baseline_qps = statistics.mean(float(row["qps"]) for row in grouped["baseline"])
baseline_mpki = statistics.mean(float(row["l2i_mpki"]) for row in grouped["baseline"])
summary = []
for label, group in grouped.items():
    qps = [float(row["qps"]) for row in group]
    mpki = [float(row["l2i_mpki"]) for row in group]
    summary.append(
        {
            "label": label,
            "n": len(group),
            "qps_mean": statistics.mean(qps),
            "qps_stdev": statistics.stdev(qps) if len(qps) > 1 else 0.0,
            "speedup": statistics.mean(qps) / baseline_qps,
            "l2i_mpki_mean": statistics.mean(mpki),
            "l2i_mpki_stdev": statistics.stdev(mpki) if len(mpki) > 1 else 0.0,
            "l2i_reduction_pct": 100.0 * (baseline_mpki - statistics.mean(mpki)) / baseline_mpki
            if baseline_mpki
            else math.nan,
        }
    )
summary.sort(key=lambda row: (row["label"] != "baseline", -row["speedup"]))
fields = list(summary[0])
with (out / "screen_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(summary)
(out / "screen_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

bracketed = []
for index, row in enumerate(valid):
    if row["label"] == "baseline":
        continue
    previous = next(
        (valid[pos] for pos in range(index - 1, -1, -1)
         if valid[pos]["label"] == "baseline"),
        None,
    )
    following = next(
        (valid[pos] for pos in range(index + 1, len(valid))
         if valid[pos]["label"] == "baseline"),
        None,
    )
    if previous is None or following is None:
        continue
    bracket_qps = statistics.mean(
        [float(previous["qps"]), float(following["qps"])]
    )
    bracket_mpki = statistics.mean(
        [float(previous["l2i_mpki"]), float(following["l2i_mpki"])]
    )
    candidate_qps = float(row["qps"])
    candidate_mpki = float(row["l2i_mpki"])
    bracketed.append(
        {
            "run_order": int(row["run_order"]),
            "label": row["label"],
            "previous_baseline_qps": float(previous["qps"]),
            "following_baseline_qps": float(following["qps"]),
            "bracket_baseline_qps": bracket_qps,
            "qps": candidate_qps,
            "bracket_speedup": candidate_qps / bracket_qps,
            "bracket_baseline_l2i_mpki": bracket_mpki,
            "l2i_mpki": candidate_mpki,
            "bracket_l2i_reduction_pct": (
                100.0 * (bracket_mpki - candidate_mpki) / bracket_mpki
                if bracket_mpki else math.nan
            ),
        }
    )
if bracketed:
    bracketed.sort(key=lambda row: -row["bracket_speedup"])
    fields = list(bracketed[0])
    with (out / "bracket_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(bracketed)
    (out / "bracket_summary.json").write_text(
        json.dumps(bracketed, indent=2) + "\n"
    )
PY

cat "${OUT}/screen_summary.csv"
if [[ -s "${OUT}/bracket_summary.csv" ]]; then
  cat "${OUT}/bracket_summary.csv"
fi
if ((${#failed_labels[@]} > 0)); then
  printf 'labels without a valid run: %s\n' "${failed_labels[*]}" >&2
  exit 1
fi
