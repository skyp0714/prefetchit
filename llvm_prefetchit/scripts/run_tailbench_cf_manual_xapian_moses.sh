#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LLVM_PREFETCH_DIR="${ROOT_DIR}/llvm_prefetchit"

RUN_ID="${RUN_ID:-tailbench_cf_manual_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/${RUN_ID}}"
WORK_ROOT="${WORK_ROOT:-${LLVM_PREFETCH_DIR}/work/${RUN_ID}}"
BENCHMARKS="${BENCHMARKS:-xapian moses}"
CF_VARIANTS="${CF_VARIANTS:-cf4_o0 cf4_o064 cf8_o0 cf8_o064}"
EVAL_REPS="${EVAL_REPS:-3}"
RUN_TO_COMPLETION="${RUN_TO_COMPLETION:-1}"
REQUEST_SECONDS="${REQUEST_SECONDS:-120}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-240}"
JOBS="${JOBS:-16}"

export RUN_ID OUT_DIR WORK_ROOT BENCHMARKS RUN_TO_COMPLETION REQUEST_SECONDS TIMEOUT_SECONDS JOBS

PREFETCHIT_SOURCE_ONLY=1 source "${LLVM_PREFETCH_DIR}/scripts/run_tailbench_highmpki_pgo.sh"

cf_entries_for_label() {
  case "$1" in
    cf4|cf4_*) echo 4 ;;
    cf8|cf8_*) echo 8 ;;
    cf16|cf16_*) echo 16 ;;
    *) echo 0 ;;
  esac
}

cf_offsets_for_label() {
  case "$1" in
    *_o064|*_o0_64|*_target_next) echo "0,64" ;;
    *) echo "0" ;;
  esac
}

prefetchit_post_setup_hook() {
  local key="$1"
  local label="$2"
  local work="$3"
  local src_dir="$4"
  local entries
  local offsets
  entries="$(cf_entries_for_label "${label}")"
  offsets="$(cf_offsets_for_label "${label}")"
  if [[ "${entries}" == "0" ]]; then
    return 0
  fi
  case "${key}" in
    moses)
      if ! python3 - "${src_dir}" "${entries}" "${offsets}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
entries = int(sys.argv[2])
offsets = [int(x) for x in sys.argv[3].split(",") if x]
offset_list = ", ".join(str(x) for x in offsets)

(root / "moses" / "CFPrefetch.h").write_text(f"""#ifndef MOSES_CF_PREFETCH_H
#define MOSES_CF_PREFETCH_H

namespace Moses {{

static __inline__ __attribute__((__always_inline__)) void CFPrefetchLine(const void *addr) {{
#if defined(__GNUC__) || defined(__clang__)
  if (!addr)
    return;
  const char *p = reinterpret_cast<const char *>(addr);
  static const unsigned offsets[] = {{{offset_list}}};
  for (unsigned j = 0; j < sizeof(offsets) / sizeof(offsets[0]); ++j)
    __builtin_prefetch(p + offsets[j], 0, 2);
#else
  (void)addr;
#endif
}}

static __inline__ __attribute__((__always_inline__)) void CFPrefetchVTableTargets(const void *obj) {{
#if defined(__GNUC__) || defined(__clang__)
  if (!obj)
    return;
  const void *const *vt = *reinterpret_cast<const void *const *const *>(obj);
  __builtin_prefetch(vt, 0, 2);
  for (unsigned i = 0; i < {entries}; ++i)
    CFPrefetchLine(vt[i]);
#else
  (void)obj;
#endif
}}

}}

#endif
""")

toc = root / "moses" / "TranslationOptionCollection.cpp"
text = toc.read_text()
if '#include "CFPrefetch.h"\n' not in text:
    text = text.replace('#include "DecodeGraph.h"\n', '#include "DecodeGraph.h"\n#include "CFPrefetch.h"\n', 1)
old = """      // do rest of decode steps
      int indexStep = 0;
      for (++iterStep ; iterStep != decodeGraph.end() ; ++iterStep) {
        const DecodeStep &decodeStep = **iterStep;
        PartialTranslOptColl* newPtoc = new PartialTranslOptColl;
"""
new = """      // do rest of decode steps
      int indexStep = 0;
      for (++iterStep ; iterStep != decodeGraph.end() ; ++iterStep) {
        const DecodeStep &decodeStep = **iterStep;
        CFPrefetchVTableTargets(&decodeStep);
        PartialTranslOptColl* newPtoc = new PartialTranslOptColl;
"""
if old in text:
    text = text.replace(old, new, 1)
else:
    raise SystemExit("DecodeStep loop pattern not found")
toc.write_text(text)

hyp = root / "moses" / "Hypothesis.cpp"
text = hyp.read_text()
if '#include "CFPrefetch.h"\n' not in text:
    text = text.replace('#include "LMList.h"\n', '#include "LMList.h"\n#include "CFPrefetch.h"\n', 1)
old = """  for (unsigned i = 0; i < sfs.size(); ++i) {
    if (!sfs[i]->ComputeValueInTranslationOption()) {
      EvaluateWith(sfs[i]);
    }
  }
"""
new = """  for (unsigned i = 0; i < sfs.size(); ++i) {
    if (i + 1 < sfs.size())
      CFPrefetchVTableTargets(sfs[i + 1]);
    if (!sfs[i]->ComputeValueInTranslationOption()) {
      CFPrefetchVTableTargets(sfs[i]);
      EvaluateWith(sfs[i]);
    }
  }
"""
if old in text:
    text = text.replace(old, new, 1)
else:
    raise SystemExit("stateless feature loop pattern not found")
old = """  for (unsigned i = 0; i < ffs.size(); ++i) {
    m_ffStates[i] = ffs[i]->Evaluate(
                      *this,
                      m_prevHypo ? m_prevHypo->m_ffStates[i] : NULL,
                      &m_currScoreBreakdown);
  }
"""
new = """  for (unsigned i = 0; i < ffs.size(); ++i) {
    if (i + 1 < ffs.size())
      CFPrefetchVTableTargets(ffs[i + 1]);
    CFPrefetchVTableTargets(ffs[i]);
    m_ffStates[i] = ffs[i]->Evaluate(
                      *this,
                      m_prevHypo ? m_prevHypo->m_ffStates[i] : NULL,
                      &m_currScoreBreakdown);
  }
"""
if old in text:
    text = text.replace(old, new, 1)
else:
    raise SystemExit("stateful feature loop pattern not found")
hyp.write_text(text)
PY
      then
        return 1
      fi
      ;;
    xapian)
      if ! python3 - "${src_dir}" "${entries}" "${offsets}" <<'PY'
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
entries = int(sys.argv[2])
offsets = [int(x) for x in sys.argv[3].split(",") if x]
offset_list = ", ".join(str(x) for x in offsets)
matcher = root / "xapian-core-1.2.13" / "matcher"

if not matcher.exists():
    subprocess.check_call(["tar", "-xf", "xapian-core-1.2.13.tar.gz"], cwd=str(root))
    matcher = root / "xapian-core-1.2.13" / "matcher"

(matcher / "cfprefetch.h").write_text(f"""#ifndef OM_HGUARD_CFPREFETCH_H
#define OM_HGUARD_CFPREFETCH_H

static __inline__ __attribute__((__always_inline__)) void
xapian_cf_prefetch_line(const void *addr)
{{
#if defined(__GNUC__) || defined(__clang__)
    if (!addr)
        return;
    const char *p = reinterpret_cast<const char *>(addr);
    static const unsigned offsets[] = {{{offset_list}}};
    for (unsigned j = 0; j < sizeof(offsets) / sizeof(offsets[0]); ++j)
        __builtin_prefetch(p + offsets[j], 0, 2);
#else
    (void)addr;
#endif
}}

static __inline__ __attribute__((__always_inline__)) void
xapian_cf_prefetch_vtable_targets(const void *obj)
{{
#if defined(__GNUC__) || defined(__clang__)
    if (!obj)
        return;
    const void *const *vt = *reinterpret_cast<const void *const *const *>(obj);
    __builtin_prefetch(vt, 0, 2);
    for (unsigned i = 0; i < {entries}; ++i)
        xapian_cf_prefetch_line(vt[i]);
#else
    (void)obj;
#endif
}}

#endif
""")

branch = matcher / "branchpostlist.h"
text = branch.read_text()
if '#include "cfprefetch.h"\n' not in text:
    text = text.replace('#include "postlist.h"\n', '#include "postlist.h"\n#include "cfprefetch.h"\n', 1)
text = text.replace('    PostList *p = pl->next(w_min);\n',
                    '    xapian_cf_prefetch_vtable_targets(pl);\n    PostList *p = pl->next(w_min);\n', 1)
text = text.replace('    PostList *p = pl->skip_to(did, w_min);\n',
                    '    xapian_cf_prefetch_vtable_targets(pl);\n    PostList *p = pl->skip_to(did, w_min);\n', 1)
text = text.replace('    PostList *p = pl->check(did, w_min, valid);\n',
                    '    xapian_cf_prefetch_vtable_targets(pl);\n    PostList *p = pl->check(did, w_min, valid);\n', 1)
branch.write_text(text)

multi = matcher / "multimatch.cc"
text = multi.read_text()
if '#include "cfprefetch.h"\n' not in text:
    text = text.replace('#include "mergepostlist.h"\n', '#include "mergepostlist.h"\n#include "cfprefetch.h"\n', 1)
text = text.replace("""\t\tSubMatch * submatch = leaves[leaf].get();
\t\tif (!submatch || submatch->prepare_match(nowait, stats)) {
""", """\t\tSubMatch * submatch = leaves[leaf].get();
\t\txapian_cf_prefetch_vtable_targets(submatch);
\t\tif (!submatch || submatch->prepare_match(nowait, stats)) {
""", 1)
text = text.replace("""\t    pl = leaves[i]->get_postlist_and_term_info(this,
""", """\t    xapian_cf_prefetch_vtable_targets(leaves[i].get());
\t    pl = leaves[i]->get_postlist_and_term_info(this,
""", 1)
multi.write_text(text)
PY
      then
        return 1
      fi
      ;;
  esac
  echo "${key},${label},${entries},${offsets},${work},${src_dir}" >> "${OUT_DIR}/manual_patches.csv"
}

summarize_manual() {
  python3 - "${OUT_DIR}" <<'PY'
import csv
import math
import os
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

out = Path(sys.argv[1])
runs = out / "eval_runs" / "runs.csv"
build = out / "build.csv"
summary = out / "manual_summary.md"
summary_csv = out / "manual_summary.csv"

def fnum(x):
    try:
        return float(x)
    except Exception:
        return float("nan")

rows = []
if runs.exists():
    with runs.open(newline="") as f:
        rows = list(csv.DictReader(f))

groups = defaultdict(list)
variant_labels = []
for item in os.environ.get("CF_VARIANTS", "").split():
    if item and item not in variant_labels:
        variant_labels.append(item)
for item in ("cf4", "cf8", "cf16", "cf4_o0", "cf4_o064", "cf8_o0", "cf8_o064", "cf16_o0", "cf16_o064"):
    if item not in variant_labels:
        variant_labels.append(item)
for r in rows:
    name = r.get("benchmark", "")
    for label in ["clangbase"] + variant_labels:
        suffix = "_" + label
        if name.endswith(suffix):
            groups[(name[:-len(suffix)], label)].append(r)
            break

prefetch_counts = {}
if build.exists():
    with build.open(newline="") as f:
        for r in csv.DictReader(f):
            bench = r.get("benchmark")
            label = r.get("label")
            count = r.get("prefetch_count", "")
            workdir = Path(r.get("workdir", ""))
            if label != "clangbase":
                libs = []
                if bench == "xapian":
                    libdir = workdir / "tailbench" / "xapian" / "xapian-core-1.2.13" / "install" / "lib"
                    libs.extend(libdir.glob("libxapian.so*"))
                elif bench == "moses":
                    libs.extend((workdir / "tailbench" / "moses" / "bin").glob("*.so"))
                deduped = []
                seen = set()
                for lib in libs:
                    try:
                        key = lib.resolve()
                    except Exception:
                        key = lib
                    if key not in seen:
                        seen.add(key)
                        deduped.append(lib)
                libs = deduped
                total_count = 0
                saw_lib = False
                for lib in libs:
                    if not lib.exists():
                        continue
                    saw_lib = True
                    try:
                        text = subprocess.check_output(["llvm-objdump-19", "-d", "-Mintel", str(lib)], text=True, stderr=subprocess.DEVNULL)
                        total_count += len(re.findall(r"\\bprefetch(?:t[012]|nta|it[01])\\b", text))
                    except Exception:
                        pass
                if saw_lib:
                    count = str(total_count)
            prefetch_counts[(bench, label)] = count

def median(vals):
    vals = [v for v in vals if not math.isnan(v)]
    return statistics.median(vals) if vals else float("nan")

benches = sorted({bench for bench, _ in groups})
labels = ["clangbase"] + variant_labels
csv_rows = []
lines = [
    "# TailBench Xapian/Moses Manual Control-Flow Prefetch",
    "",
    f"- Result dir: `{out}`",
    f"- Eval mode: fixed request count, `RUN_TO_COMPLETION=1`, `REQUEST_SECONDS=120`.",
    "",
    "| bench | label | reps | median runtime s | speedup vs base | median derived qps | qps speedup | median L2I MPKI | median IPC | prefetch instr | CPUs | migrations |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
]
for bench in benches:
    base_elapsed = median([fnum(r.get("elapsed_s")) for r in groups.get((bench, "clangbase"), [])])
    base_qps = median([fnum(r.get("derived_qps")) for r in groups.get((bench, "clangbase"), [])])
    for label in labels:
        rs = groups.get((bench, label), [])
        if not rs:
            continue
        elapsed = median([fnum(r.get("elapsed_s")) for r in rs])
        qps = median([fnum(r.get("derived_qps")) for r in rs])
        mpki = median([fnum(r.get("l2i_mpki")) for r in rs])
        ipc = median([fnum(r.get("ipc")) for r in rs])
        speed = base_elapsed / elapsed if base_elapsed > 0 and elapsed > 0 else float("nan")
        qspeed = qps / base_qps if base_qps > 0 and qps > 0 else float("nan")
        cpus = ";".join(sorted({r.get("observed_unique_psrs", "") for r in rs if r.get("observed_unique_psrs", "")}))
        mig = median([fnum(r.get("cpu_migrations")) for r in rs])
        pf = prefetch_counts.get((bench, label), "")
        lines.append("| {} | {} | {} | {:.3f} | {} | {:.3f} | {} | {:.3f} | {:.3f} | {} | {} | {:.0f} |".format(
            bench, label, len(rs), elapsed,
            f"{speed:.6f}" if not math.isnan(speed) else "",
            qps,
            f"{qspeed:.6f}" if not math.isnan(qspeed) else "",
            mpki, ipc, pf, cpus, mig if not math.isnan(mig) else float("nan")))
        csv_rows.append({
            "bench": bench,
            "label": label,
            "reps": len(rs),
            "median_elapsed_s": f"{elapsed:.6f}" if not math.isnan(elapsed) else "",
            "speedup_vs_base": f"{speed:.9f}" if not math.isnan(speed) else "",
            "median_derived_qps": f"{qps:.6f}" if not math.isnan(qps) else "",
            "qps_speedup_vs_base": f"{qspeed:.9f}" if not math.isnan(qspeed) else "",
            "median_l2i_mpki": f"{mpki:.6f}" if not math.isnan(mpki) else "",
            "median_ipc": f"{ipc:.6f}" if not math.isnan(ipc) else "",
            "prefetch_instr": pf,
            "observed_cpus": cpus,
            "median_migrations": f"{mig:.0f}" if not math.isnan(mig) else "",
        })

summary.write_text("\n".join(lines) + "\n")
with summary_csv.open("w", newline="") as f:
    fields = ["bench", "label", "reps", "median_elapsed_s", "speedup_vs_base", "median_derived_qps",
              "qps_speedup_vs_base", "median_l2i_mpki", "median_ipc", "prefetch_instr",
              "observed_cpus", "median_migrations"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(csv_rows)
PY
}

main_manual() {
  mkdir -p "${OUT_DIR}" "${WORK_ROOT}" "${OUT_DIR}/build_logs"
  echo "benchmark,label,entries,offsets,workdir,srcdir" > "${OUT_DIR}/manual_patches.csv"
  log "manual cf out=${OUT_DIR}"
  log "manual cf work=${WORK_ROOT}"
  log "manual cf benchmarks=${BENCHMARKS} variants=${CF_VARIANTS} eval_reps=${EVAL_REPS}"

  for bench in ${BENCHMARKS}; do
    build_one "${bench}" "clangbase" "" || continue
    for label in ${CF_VARIANTS}; do
      build_one "${bench}" "${label}" "" || true
    done
  done

  for rep in $(seq 1 "${EVAL_REPS}"); do
    log "manual cf eval rep=${rep}"
    for bench in ${BENCHMARKS}; do
      key="$(bench_key "${bench}")"
      if [[ -d "${WORK_ROOT}/${key}_clangbase" ]]; then
        eval_variant "${key}" "clangbase" "${WORK_ROOT}/${key}_clangbase" || true
      fi
      for label in ${CF_VARIANTS}; do
        if [[ -d "${WORK_ROOT}/${key}_${label}" ]]; then
          eval_variant "${key}" "${label}" "${WORK_ROOT}/${key}_${label}" || true
        fi
      done
    done
    summarize_manual
  done
  summarize_manual
  log "manual cf done summary=${OUT_DIR}/manual_summary.md"
}

main_manual "$@"
