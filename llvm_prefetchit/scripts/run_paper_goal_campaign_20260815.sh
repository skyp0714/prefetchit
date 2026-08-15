#!/usr/bin/env bash
# Serial campaign queue for paper_goal_20260815. One measurement at a time.
set -uo pipefail

ROOT=/home/hnpark2/prefetchit
LLVM="${ROOT}/llvm_prefetchit"
OUT="${LLVM}/results/paper_goal_20260815"
PLANS="${OUT}/postgresql_static/plans"
LOG="${OUT}/campaign.log"
mkdir -p "${OUT}"

log() { printf '[%(%F %T)T] %s\n' -1 "$*" | tee -a "${LOG}"; }

# ---- stage 1: wait for postgres static plans -------------------------------
log "stage1: waiting for postgres static plans"
count_valid_plans() {
  local n=0 f
  while IFS= read -r f; do
    [[ "$(jq -r '.stats.selected_injections // 0' "${f}" 2>/dev/null)" -gt 0 ]] && n=$((n + 1))
  done < <(find "${PLANS}" -name prefetchit.plan.json 2>/dev/null)
  echo "${n}"
}
for _ in $(seq 1 240); do
  n="$(count_valid_plans)"
  ((n >= 3)) && break
  sleep 30
done
n="$(count_valid_plans)"
log "stage1: ${n} non-empty plans present"
# only build plan dirs whose plan actually has injections
for d in "${PLANS}"/*/; do
  f="${d}/prefetchit.plan.json"
  if [[ -s "${f}" ]] && [[ "$(jq -r '.stats.selected_injections // 0' "${f}")" -eq 0 ]]; then
    log "stage1: dropping empty plan $(basename "${d}")"
    rm -rf "${d}"
  fi
done

# ---- stage 2: build postgres static variants --------------------------------
if ((n >= 1)); then
  log "stage2: building postgres static variants"
  labels=""
  for d in "${PLANS}"/*/; do
    [[ -s "${d}/prefetchit.plan.json" ]] && labels="${labels} $(basename "${d}")"
  done
  BUILD_VARIANTS="${labels# }" \
  BUILD_ROOT="${LLVM}/work/pgo_goal_20260713/bins/postgresql_simple_c8_tune1/build" \
    bash "${LLVM}/scripts/build_postgresql_lbr_pgo_variants.sh" \
      "${PLANS}" "${OUT}/postgresql_static/bins" \
      >> "${LOG}" 2>&1
  log "stage2: build rc=$? summary:"
  cat "${OUT}/postgresql_static/bins/build_summary.csv" >> "${LOG}" 2>/dev/null
else
  log "stage2: SKIPPED (no plans)"
fi

# ---- stage 3: verilator cross-payload transfer ------------------------------
log "stage3: verilator cross-payload transfer"
bash "${LLVM}/scripts/run_verilator_crosspayload_transfer.sh" \
  >> "${OUT}/verilator_crosspayload_stdout.log" 2>&1
log "stage3: rc=$?"

# ---- stage 4: postgres paired evals -----------------------------------------
log "stage4: postgres paired evals"
run_pg() {
  local bin="$1" label="$2"
  [[ -x "${bin}" ]] || { log "stage4: missing ${bin}"; return 1; }
  DURATION=30 WARMUP_DURATION=20 QUERY_MODE=simple CLIENTS=8 REPS=5 \
    bash "${LLVM}/scripts/run_final_postgresql_paired.sh" \
      "${bin}" "${OUT}/postgresql_static/paired/${label}" "${label}" \
      >> "${LOG}" 2>&1
  log "stage4: ${label} rc=$?"
}
for d in "${OUT}/postgresql_static/bins/installs/"*/; do
  label="$(basename "${d}")"
  run_pg "${d}/bin/postgres" "${label}"
done
# same-day PGO reference (audited winner binary)
run_pg "${LLVM}/work/pgo_goal_20260713/bins/postgresql_simple_c8_tune1/installs/cov25_d8_32_b1_o0/bin/postgres" \
  "pgo_cov25_d8_32_b1_o0_ref"

# ---- stage 5: gem5 L2I MPKI screen ------------------------------------------
log "stage5: gem5 screen"
GEM5="${ROOT}/build/X86/gem5.opt"
SE="${ROOT}/benchmarks/gem5/configs/deprecated/example/se.py"
BUSY=/tmp/static_verify/busy_static
if [[ ! -x "${BUSY}" ]]; then
  cat > /tmp/static_verify/busy.c <<'EOF'
#include <stdio.h>
int main(void) {
    volatile double s = 0;
    for (long i = 0; i < 4000000000L; i++) s += (double)(i ^ (i >> 3)) * 1.0000001;
    printf("%f\n", s);
    return 0;
}
EOF
  clang -O2 -static /tmp/static_verify/busy.c -o "${BUSY}"
fi
for variant in gem5.opt gem5.opt.eventq-prefetch-v1; do
  bin="${ROOT}/build/X86/${variant}"
  [[ -x "${bin}" ]] || continue
  dir="${OUT}/gem5_screen/${variant}"
  mkdir -p "${dir}"
  ( cd "${dir}" && \
    timeout --signal=INT 180 taskset -c 7 perf stat -x, -o perf.csv \
      -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -- \
      "${bin}" --outdir="${dir}/m5out" "${SE}" -c "${BUSY}" \
        --cpu-type=X86O3CPU --caches --l2cache \
      > sim.log 2>&1 )
  log "stage5: ${variant} rc=$? (180s screen)"
done
python3 - "${OUT}/gem5_screen" <<'PY' >> "${LOG}" 2>&1
import csv, pathlib, sys
for perf in sorted(pathlib.Path(sys.argv[1]).glob("*/perf.csv")):
    ev = {}
    for row in csv.reader(perf.open()):
        if len(row) >= 3:
            try: ev[row[2]] = float(row[0])
            except ValueError: pass
    ins = ev.get("instructions", 0); miss = ev.get("L2I_CODE_RD_MISS", 0)
    print(f"gem5-screen {perf.parent.name}: instructions={ins:.3e} "
          f"l2i_mpki={1000*miss/ins if ins else 0:.3f}")
PY

log "campaign complete"
