#!/usr/bin/env bash
# Verilator-like stream: 12 MB main function with taken forward jumps every 160 B (skip 32 B),
# calls every 300 B into 2500 straight-line helpers of 800 B, plus a data stream (DATA_MB).
# Compares: base, NOP twin, seq-only, seq+callee-burst, burst-only, at several D.
set -euo pipefail
OUTCSV="${1:?csv}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="${CORE:-71}"; REPS="${REPS:-10}"; CODE_MB="${CODE_MB:-12}"; DATA_MB="${DATA_MB:-16}"
COMMON=(--jump-every 160 --jump-skip 32 --call-every 300 --callee-bytes 800 --callees 2500 --data-mb "${DATA_MB}")
BUILD="${HERE}/build_vlike"; mkdir -p "${BUILD}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
[[ -s "${OUTCSV}" ]] || echo "variant,distance,spacing,burst_lines,burst_lead,sec_per_rep,instructions,cycles,l2i_misses,l2i_mpki,ipc" > "${OUTCSV}"
build() { local name="$1"; shift; [[ -x "${BUILD}/${name}" ]] && return
  python3 "${HERE}/gen_seq_stream.py" --code-mb "${CODE_MB}" --out "${BUILD}/${name}.s" "${COMMON[@]}" "$@" >/dev/null
  clang-19 -O1 -o "${BUILD}/${name}" "${HERE}/main.c" "${BUILD}/${name}.s"; rm -f "${BUILD}/${name}.s"; }
run() { local name="$1" d="$2" s="$3" bl="$4" ld="$5"; local perf="${BUILD}/${name}.perf.csv"
  DATA_MB="${DATA_MB}" taskset -c "${CORE}" perf stat -x, -o "${perf}" -e instructions,cycles,"${EVENT}" -- "${BUILD}/${name}" "${REPS}" > "${BUILD}/${name}.out"
  python3 - "${OUTCSV}" "${name}" "$d" "$s" "$bl" "$ld" "${BUILD}/${name}.out" "${perf}" <<'PY'
import csv, re, sys
out, name, d, s, bl, ld, res, perf = sys.argv[1:]
spr = float(re.search(r"sec_per_rep=([0-9.]+)", open(res).read()).group(1))
ev = {}
for row in csv.reader(open(perf)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins, cyc, miss = ev.get("instructions", 0), ev.get("cycles", 0), ev.get("L2I_CODE_RD_MISS", 0)
with open(out, "a", newline="") as f:
    csv.writer(f).writerow([name, d, s, bl, ld, f"{spr:.5f}", int(ins), int(cyc), int(miss), f"{1000*miss/ins if ins else 0:.3f}", f"{ins/cyc if cyc else 0:.3f}"])
print(f"{name:32s} sec/rep={spr:.4f} MPKI={1000*miss/ins:.2f} IPC={ins/cyc:.3f}")
PY
}
build base --distance 0;                                   run base 0 0 0 0
build nop_s64_b4 --distance 4096 --spacing 64 --burst-lines 4 --burst-lead 256 --nop;  run nop_s64_b4 0 64 4 256
for d in 1024 2048 4096 8192; do
  build "seq_d${d}_s64"  --distance "$d" --spacing 64;    run "seq_d${d}_s64" "$d" 64 0 0
  build "seq_d${d}_s128" --distance "$d" --spacing 128;   run "seq_d${d}_s128" "$d" 128 0 0
done
for bl in 4 8 13; do for ld in 0 256 1024; do
  build "seqburst_d4096_s128_b${bl}_l${ld}" --distance 4096 --spacing 128 --burst-lines "$bl" --burst-lead "$ld"; run "seqburst_d4096_s128_b${bl}_l${ld}" 4096 128 "$bl" "$ld"
done; done
build burst_only_b8_l256 --distance 0 --burst-lines 8 --burst-lead 256; run burst_only_b8_l256 0 0 8 256
